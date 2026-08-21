"""
================================================================================
WHY DOES THIS SCRIPT EXIST?
================================================================================

This script exists to solve one problem: our daily data-fetching script (the
one that will run automatically inside AWS Lambda) needs permission to read
your SoundCloud account data (your tracks, play counts, likes, etc.).

However, OAuth2 (the standard way applications ask for permission to access
user data) requires the user to explicitly approve the application at least
once. Automated code running without user interaction cannot simply log in
as you.

That is the purpose of this script: it performs the initial login and
authorization manually, only once.

--------------------------------------------------------------------------------
THE BIG PICTURE: TWO DIFFERENT TOKENS
--------------------------------------------------------------------------------

OAuth2 (and SoundCloud's implementation of it) gives us two different tokens:

1. access_token
   - This is the token used to make API calls (for example, "give me my
     tracks"). You can think of it as a temporary access key.
   - It expires quickly (around 1 hour for SoundCloud). This is useful from a
     security perspective because, if the token is exposed, the time window
     in which it can be used is limited.

2. refresh_token
   - This is a longer-lived token whose purpose is to obtain a new
     access_token when the current one expires, without requiring the user
     to log in again.
   - You can think of it as a token used to renew the access_token.
   - IMPORTANT: SoundCloud provides a new refresh_token every time one is
     used. The previous one stops working. Therefore, our daily script must
     always save the newest refresh_token it receives, otherwise the next
     execution will fail because it will try to use an already-used token.

The purpose of this script is to obtain the FIRST refresh_token, which starts
this whole process. After that, this script should not need to be run again
unless the authorization becomes invalid for some reason.

--------------------------------------------------------------------------------
STEP BY STEP: WHAT ACTUALLY HAPPENS WHEN YOU RUN THIS SCRIPT
--------------------------------------------------------------------------------

STEP 1 — Generate the PKCE values
    We create two related values:
      - code_verifier: a random secret string known only to this script.
      - code_challenge: a value derived from that secret, which can be safely
        included in the authorization URL.

    Why do we need this? In the next step, we are going to open a SoundCloud
    URL in the browser. The URL is not a private place, so we should not put
    the original secret directly in it.

    Instead, we include the code_challenge in the URL. Later, in Step 4, we
    send the original code_verifier directly to SoundCloud's server.
    SoundCloud can then check that both values match and verify that the
    authorization request belongs to this script.

STEP 2 — Build a special SoundCloud URL and open it in your browser
    This URL contains your app's client_id, the code_challenge from Step 1,
    and a redirect_uri (basically, "once you're done, send the browser back
    to THIS address").

    You open this URL, SoundCloud asks you to log in (if you are not already
    logged in) and shows a screen asking you to allow the application to
    access your account. You click Allow.

STEP 3 — SoundCloud redirects your browser, you copy a code
    After you click "Allow", SoundCloud redirects your browser to the
    redirect_uri we specified (http://localhost:8080/callback). Since we do
    not actually have a web server running there, the browser will show a
    "can't connect" error page. This is completely expected.

    What matters is not the error page, but the URL in the address bar,
    which now looks like:

        http://localhost:8080/callback?code=XXXXX&state=YYYYY

    The "code" is a short-lived, one-time-use value that proves you approved
    the authorization request. We copy it manually and paste it into this
    script.

STEP 4 — Exchange the code and our secret for the real tokens
    This script sends the "code" from Step 3, together with the original
    code_verifier from Step 1, directly to SoundCloud's server.

    SoundCloud checks that everything matches and, if everything is correct,
    returns our first access_token and refresh_token.

STEP 5 — Save the refresh_token somewhere safe
    We print the refresh_token so it can be copied into the local .env file.
    Later, this same value will be stored in AWS Parameter Store, so the daily
    Lambda function can read it and automatically renew the access_token.

--------------------------------------------------------------------------------
WHY CAN'T THE DAILY LAMBDA JUST DO ALL OF THIS BY ITSELF?
--------------------------------------------------------------------------------

Because Steps 2 and 3 require user interaction in a real browser. The user
has to log in and explicitly click "Allow" to give the application access
to the account.

This is a deliberate part of the OAuth2 authorization process. The initial
authorization therefore cannot be fully automated.

That is why this script is separate from the daily ingestion script: this one
requires a human and a browser, and only runs once. The daily script only needs
the refresh_token and can run without user interaction, renewing the
access_token on every execution.

See docs/adr/07-... .md for the architectural reasoning behind this design.
================================================================================
"""


import os
import secrets
import hashlib
import base64
import requests as r
from dotenv import load_dotenv

load_dotenv()

# See API documentation for checking this URLs
TOKEN_URL = "https://secure.soundcloud.com/oauth/token"
AUTHORIZE_URL = "https://secure.soundcloud.com/authorize"

# You must configurate it at Registered Apps
REDIRECT_URI = "http://localhost:8080/callback" 

def generate_pkce_pair():
    """
    Read ADR-07 for more details
    """
    code_verifier = secrets.token_urlsafe(64)

    challenge_bytes = hashlib.sha256(code_verifier.encode("utf-8")).digest()
    code_challenge = base64.urlsafe_b64encode(challenge_bytes).decode("utf-8").rstrip("=")

    return code_verifier, code_challenge


def build_authorize_url(client_id, code_challenge):
    """
    Builds the URL the user must open in a browser to approve access.
    """
    state = secrets.token_urlsafe(16) 
    params = (
        f"client_id={client_id}"
        f"&redirect_uri={REDIRECT_URI}"
        f"&response_type=code"
        f"&code_challenge={code_challenge}"
        f"&code_challenge_method=S256"
        f"&state={state}"
    )
    return f"{AUTHORIZE_URL}?{params}"


def exchange_code_for_tokens(code, code_verifier, client_id, client_secret):
    """
    Exchanges the authorization code for the initial access_token + refresh_token.
    """
    response = r.post(
        TOKEN_URL,
        data={
            "grant_type": "authorization_code",
            "client_id": client_id,
            "client_secret": client_secret,
            "redirect_uri": REDIRECT_URI,
            "code_verifier": code_verifier,
            "code": code,
        },
        headers={"accept": "application/json; charset=utf-8"},
    )

    if response.status_code != 200:
        raise RuntimeError(f"Token exchange failed: {response.status_code} - {response.text}")

    return response.json()


if __name__ == "__main__":
    client_id = os.environ.get("SOUNDCLOUD_CLIENT_ID")
    client_secret = os.environ.get("SOUNDCLOUD_CLIENT_SECRET")

    code_verifier, code_challenge = generate_pkce_pair()

    auth_url = build_authorize_url(client_id, code_challenge)
    print("\nOpen this URL in your browser and approve access:\n")
    print(auth_url)

    code = input("\nPaste the 'code' value from the redirected URL: ").strip()

    tokens = exchange_code_for_tokens(code, code_verifier, client_id, client_secret)

    print("\nAccess token:", tokens["access_token"][:15], "...")
    print("Refresh token:", tokens["refresh_token"])
    print("\nCopy the refresh_token above into your .env as SOUNDCLOUD_REFRESH_TOKEN")