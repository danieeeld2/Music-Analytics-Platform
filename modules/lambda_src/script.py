import requests as r
from dotenv import load_dotenv
import os
from datetime import date, datetime

load_dotenv() # Load .env variables

# See API documentation for checking this URLs
TOKEN_URL = "https://secure.soundcloud.com/oauth/token"

def connect():
    """
    Authenticates against SoundCloud API using Client Credentials flow.
    Docs: https://developers.soundcloud.com/docs/api/guide#authentication - See Refreshing Tokens part

    Returns:
        tuple[str, str]: (access_token, refresh_token). the refresh_token must be persisted, replacing the old one

    Raises:
        ValueError: If client_id or client_secret or refresh_token are missing
        RuntimeError: If the token request fails (non 200)
    """
    # Read .env secrets
    client_id = os.environ.get("SOUNDCLOUD_CLIENT_ID")
    client_secret = os.environ.get("SOUNDCLOUD_CLIENT_SECRET")
    refresh_token = os.environ.get("SOUNDCLOUD_REFRESH_TOKEN")

    if not client_id or not client_secret or not refresh_token:
        raise ValueError("Missing API Key parameters")

    # Get Access Token
    response = r.post(
        TOKEN_URL,
        data = {
            "grant_type" : "refresh_token",
            "client_id" : client_id,
            "client_secret" : client_secret,
            "refresh_token" : refresh_token
        },
        headers = {"accept" : "application/json; charset=utf-8"}
    )

    if response.status_code != 200:
        raise RuntimeError(f"Failed to authenticate: {response.status_code} - {response.text}")

    access_token = response.json()["access_token"]
    new_refresh_token = response.json()["refresh_token"]

    save_refresh_token(new_refresh_token)

    return access_token, new_refresh_token

def save_refresh_token(token, env_path=".env"):
    """
    Overwrites SOUNDCLOUD_REFRESH_TOKEN in .env file with new value, since SoundCloud invalidates the old
    token on every use

    Args:
        token (str): The new token
        env_path (str): Path to .env file
    """
    with open(env_path, "r") as f:
        lines = f.readlines()

    # Ensure every line ends with a newline
    lines = [line if line.endswith("\n") else line + "\n" for line in lines]

    updated_lines = []
    found = False

    for line in lines:
        if line.startswith("SOUNDCLOUD_REFRESH_TOKEN="):
            updated_lines.append(f"SOUNDCLOUD_REFRESH_TOKEN={token}\n")
            found = True
        else:
            updated_lines.append(line)

    if not found:
        updated_lines.append(f"SOUNDCLOUD_REFRESH_TOKEN={token}\n")

    with open(env_path, "w") as f:
        f.writelines(updated_lines)

def get_my_tracks(access_token):
    """
    API call to endpoint /me/tracks — fetches the list of the authenticated
    user's tracks, including per-track engagement counters.

    Args:
        access_token (str): Authentication token generated at connect() (valid for 1 hour)

    Returns:
        dict: Parsed JSON response. Key fields per track (inside "collection"):
            id, title, playback_count, favoritings_count, reposts_count,
            comment_count, download_count, created_at.

    Raises:
        RuntimeError: If the request fails (non-200 response).
    """
    url = 'https://api.soundcloud.com/me/tracks?limit=200&sort=desc&linked_partitioning=true'
    token = "OAuth " + access_token

    response = r.get(
        url,
        headers = {
            "accept" : "application/json; charset=utf-8",
            "Authorization" : token
        }
    )

    if response.status_code != 200:
        raise RuntimeError(f"Failed to fetch tracks: {response.status_code} - {response.text}")

    return response.json()

def get_my_profile(access_token):
    """
    API call to endpoint /me — fetches the authenticated user's own profile
    and account-level counters.

    Args:
        access_token (str): Authentication token generated at connect() (valid for 1 hour)

    Returns:
        dict: Parsed JSON response. Key fields:
            followers_count, followings_count, public_favorites_count, reposts_count.

    Raises:
        RuntimeError: If the request fails (non-200 response).
    """
    url = 'https://api.soundcloud.com/me'
    token = "OAuth " + access_token

    response = r.get(
        url,
        headers = {
            "accept" : "application/json; charset=utf-8",
            "Authorization" : token
        }
    )

    if response.status_code != 200:
        raise RuntimeError(f"Failed to fetch tracks: {response.status_code} - {response.text}")

    return response.json()

def parse_tracks(tracks_response):
    """
    Transforms the raw /me/tracks API response into the rows needed for the
    `tracks` and `track_snapshots` tables.

    Args:
        tracks_response (dict): The raw JSON returned by get_my_tracks().

    Returns:
        tuple[list[dict], list[dict]]: (tracks_rows, snapshot_rows)
    """
    today = date.today()
    tracks_rows = []
    snapshots_rows = []

    for track in tracks_response["collection"]:
        # Add track row for Tracks Table (General Information of the Track)
        tracks_rows.append({
            "track_id": track["id"],
            "title": track["title"],
            "genre": track["genre"] or None,
            "created_at": datetime.strptime(track["created_at"], "%Y/%m/%d %H:%M:%S %z")
        })

        # Add track row for Snapshots Table (Today's Numbers of the Track)
        snapshots_rows.append({
            "track_id": track["id"],
            "snapshot_date": today,
            "playback_count": track["playback_count"],
            "favoritings_count": track["favoritings_count"],
            "reposts_count": track["reposts_count"],
            "comment_count": track["comment_count"],
            "download_count": track["download_count"]
        })

    return tracks_rows, snapshots_rows

def parse_profile(profile_response):
    """
    Transforms the raw /me API response into the row needed for the
    `account_snapshots` table.

    Args:
        profile_response (dict): The raw JSON returned by get_my_profile().

    Returns:
        dict: A single row ready to insert into account_snapshots.
    """
    profile = {
        "snapshot_date": date.today(),
        "followers_count": profile_response["followers_count"],
        "followings_count": profile_response["followings_count"],
        "public_favorites_count": profile_response["public_favorites_count"],
        "reposts_count": profile_response["reposts_count"]
    }

    return profile

if __name__ == "__main__":
    access_token, refresh_token = connect()

    profile = parse_profile(get_my_profile(access_token))
    tracks, snapshots = parse_tracks(get_my_tracks(access_token))

    print(profile)
    print(f"\n\n----------\n\n")
    print(tracks)
    print(f"\n\n----------\n\n")
    print(snapshots)

