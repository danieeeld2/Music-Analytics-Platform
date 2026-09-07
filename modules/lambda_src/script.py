import requests as r
import os
from datetime import date, datetime
import psycopg2
import boto3
import json
from dotenv import load_dotenv

load_dotenv()

# Two different clients on purpose: SoundCloud credentials live in Parameter Store (free, no rotation needed), while the RDS password lives in Secrets Manager because that's where AWS puts it automatically when manage_master_user_password is enabled in Terraform. 
# Merging both into Secrets Manager would add real monthly cost for the SoundCloud parameters with no actual benefit.
ssm = boto3.client("ssm", region_name = "eu-west-1") #ParameterStore
secretsmanager = boto3.client("secretsmanager", region_name="eu-west-1") #SecretsManager

# See API documentation for checking this URLs
TOKEN_URL = "https://secure.soundcloud.com/oauth/token"

def connect():
    """
    Authenticates against SoundCloud API using the Refresh Token flow.
    Docs: https://developers.soundcloud.com/docs/api/guide#authentication - See Refreshing Tokens part

    Reads client_id, client_secret and refresh_token from Parameter Store.

    Returns:
        tuple[str, str]: (access_token, refresh_token). the refresh_token must be persisted, replacing the old one

    Raises:
        ValueError: If client_id or client_secret or refresh_token are missing
        RuntimeError: If the token request fails (non 200)
    """
    # Read secrets from ParameterStore with boto3
    client_id = ssm.get_parameter(
        Name="/music-analytics/soundcloud/client_id",
        WithDecryption=True
    )['Parameter']['Value']
    client_secret = ssm.get_parameter(
        Name="/music-analytics/soundcloud/client_secret",
        WithDecryption=True
    )['Parameter']['Value']
    refresh_token = ssm.get_parameter(
        Name="/music-analytics/soundcloud/refresh_token",
        WithDecryption=True
    )['Parameter']['Value']

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

def save_refresh_token(token):
    """
    Overwrites the SOUNDCLOUD_REFRESH_TOKEN parameter in Parameter Store with the new value, since SoundCloud invalidates the old token on every use.

    Args:
        token (str): The new refresh_token to persist.
    """
    ssm.put_parameter(
        Name="/music-analytics/soundcloud/refresh_token",
        Value=token,
        Type="SecureString",
        Overwrite=True
    )

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
    Transforms the raw /me/tracks API response into the rows needed for the `tracks` and `track_snapshots` tables.

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

def get_db_connection():
    """
    Opens a connection to the Postgres database. Host is read from an environment variable (set by Terraform as a Lambda env var), and credentials are read from the Secrets Manager secret auto-generated by RDS (manage_master_user_password).

    Returns:
        psycopg2.extensions.connection: An open database connection.

    Raises:
        ValueError: If the DB_HOST env var or the DB secret ARN are missing.
    """
    db_host = os.environ.get("DB_HOST")
    db_secret_arn = os.environ.get("DB_SECRET_ARN")

    if not db_host or not db_secret_arn:
        raise ValueError("Missing DB_HOST or DB_SECRET_ARN environment variables")

    secret_response = secretsmanager.get_secret_value(SecretId=db_secret_arn)
    secret = json.loads(secret_response["SecretString"])

    connection = psycopg2.connect(
        host=db_host,
        port=5432,
        dbname="soundcloud_data_db",
        user=secret["username"],
        password=secret["password"],
    )

    return connection

def insert_tracks(bd_connection, tracks_rows):
    """
    Inserts new tracks into the `tracks` table.

    Args:
        bd_connection: An open psycopg2 connection
        tracks_row (list[dict]): Rows produced by parse_track()
    """
    with bd_connection.cursor() as c:
        for row in tracks_rows:
            c.execute(
                """
                INSERT INTO tracks (track_id, title, genre, created_at)
                VALUES (%(track_id)s, %(title)s, %(genre)s, %(created_at)s)
                ON CONFLICT (track_id) DO NOTHING;
                """,
                row
            )
    bd_connection.commit()

def insert_track_snapshots(bd_connection, snapshot_rows):
    """
    Inserts a new snapshot from a existent track into the `track_snapshots` table.

    Args:
        bd_connection: An open psycopg2 connection
        snapshot_rows (list[dict]): Rows produced by parse_track()
    """
    with bd_connection.cursor() as c:
        for row in snapshot_rows:
            c.execute(
                """
                INSERT INTO track_snapshots (track_id, snapshot_date, playback_count, favoritings_count, reposts_count, comment_count, download_count)
                VALUES (%(track_id)s, %(snapshot_date)s, %(playback_count)s, %(favoritings_count)s,%(reposts_count)s, %(comment_count)s, %(download_count)s)
                ON CONFLICT (track_id, snapshot_date) DO NOTHING;
                """,
                row
            )
    bd_connection.commit()

def insert_account_snapshot(bd_connection, account_row):
    """
    Inserts a new snapshot from the account into the `account_snapshots` table.

    Args:
        bd_connection: An open psycopg2 connection
        account_row (dict): Row produced by parse_profile()
    """
    with bd_connection.cursor() as c:
        c.execute(
            """
            INSERT INTO account_snapshots (snapshot_date, followers_count, followings_count, public_favorites_count, reposts_count)
            VALUES (%(snapshot_date)s, %(followers_count)s, %(followings_count)s, %(public_favorites_count)s, %(reposts_count)s)
            ON CONFLICT (snapshot_date) DO NOTHING;
            """,
            account_row
        )
    bd_connection.commit()

def lambda_handler(event, context):
    """
    Entry point for the Lambda function. Runs the full daily ingestion pipeline: authenticate, fetch data from SoundCloud, and store it in RDS.

    Args:
        event: Event data passed by the trigger (unused, this Lambda is triggered by a plain EventBridge schedule with no payload).
        context: Lambda runtime information (unused).

    Returns:
        dict: statusCode 200 on success, 500 on failure, with a body describing the outcome.
    """
    try:
        access_token, refresh_token = connect()

        account_row = parse_profile(get_my_profile(access_token))
        tracks_rows, snapshots_rows = parse_tracks(get_my_tracks(access_token))

        with get_db_connection() as connection:
            insert_tracks(connection, tracks_rows)
            insert_track_snapshots(connection, snapshots_rows)
            insert_account_snapshot(connection, account_row)

        return {"statusCode": 200, "body": "Ingestion completed successfully"}

    except Exception as e:
        print(f"Ingestion failed: {e}")
        return {"statusCode": 500, "body": f"Ingestion failed: {e}"}


if __name__ == "__main__":
    # For trying locally
    lambda_handler(None, None)
