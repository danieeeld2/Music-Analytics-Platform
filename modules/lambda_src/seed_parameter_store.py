"""
One-time helper script to upload the SoundCloud credentials currently sitting in the local .env file into Parameter Store, so the Lambda (or any local run pointed at AWS) can read them from there instead.

Run manually, once, whenever these values need to be (re)seeded in Parameter Store, for example after the first get_initial_token.py run, or if the parameters are ever deleted by mistake.

Usage:
    python3 seed_parameter_store.py
"""

import os
import boto3
from dotenv import load_dotenv

load_dotenv()

ssm = boto3.client("ssm", region_name="eu-west-1")

PARAMETERS = {
    "/music-analytics/soundcloud/client_id": "SOUNDCLOUD_CLIENT_ID",
    "/music-analytics/soundcloud/client_secret": "SOUNDCLOUD_CLIENT_SECRET",
    "/music-analytics/soundcloud/refresh_token": "SOUNDCLOUD_REFRESH_TOKEN",
}


def seed_parameters():
    """
    Reads each SoundCloud credential from the local .env and uploads it to Parameter Store as a SecureString, overwriting any existing value.
    """
    for param_name, env_var in PARAMETERS.items():
        value = os.environ.get(env_var)

        if not value:
            print(f"Skipping {param_name}: {env_var} not found in .env")
            continue

        ssm.put_parameter(
            Name=param_name,
            Value=value,
            Type="SecureString",
            Overwrite=True
        )
        print(f"Uploaded {param_name}")


if __name__ == "__main__":
    seed_parameters()