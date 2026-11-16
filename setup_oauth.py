"""
YouTube OAuth2 Setup Helper (setup_oauth.py).
Run this utility ONCE locally to generate your persistent YouTube Refresh Token.
You can then paste this Refresh Token into your .env file or GitHub Secrets
for 100% autonomous, cloud-based Shorts publishing.
"""

import json
import os
import sys
from pathlib import Path
from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube",
]


def run_oauth_setup():
    print("=" * 70)
    print("GTA 6 SHORTS ENGINE - YOUTUBE OAUTH2 AUTHORIZATION SETUP")
    print("=" * 70)
    print("\nThis helper generates your headless YouTube Refresh Token.\n")

    client_secrets_file = Path("client_secrets.json")

    client_id = os.getenv("YOUTUBE_CLIENT_ID", "").strip()
    client_secret = os.getenv("YOUTUBE_CLIENT_SECRET", "").strip()

    if client_secrets_file.exists():
        print(f"[+] Found '{client_secrets_file.name}'. Initializing authorization flow...")
        flow = InstalledAppFlow.from_client_secrets_file(str(client_secrets_file), SCOPES)
    elif client_id and client_secret:
        print("[+] Found Client ID and Secret in environment variables.")
        client_config = {
            "installed": {
                "client_id": client_id,
                "client_secret": client_secret,
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "redirect_uris": ["http://localhost:8080/"],
            }
        }
        flow = InstalledAppFlow.from_client_config(client_config, SCOPES)
    else:
        print("[!] No 'client_secrets.json' found. Enter credentials manually from Google Cloud Console:")
        client_id = input("Enter YouTube Client ID: ").strip()
        client_secret = input("Enter YouTube Client Secret: ").strip()

        if not client_id or not client_secret:
            print("[-] Client ID and Client Secret are required. Aborting.")
            sys.exit(1)

        client_config = {
            "installed": {
                "client_id": client_id,
                "client_secret": client_secret,
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "redirect_uris": ["http://localhost:8080/"],
            }
        }
        flow = InstalledAppFlow.from_client_config(client_config, SCOPES)

    print("\n[+] Opening browser for Google Account authentication...")
    print("    Sign in to the Google account owning your YouTube Shorts channel.\n")

    try:
        credentials = flow.run_local_server(
            port=8080,
            prompt="consent",
            access_type="offline",
        )
    except Exception as e:
        print(f"[-] Local server flow failed: {e}")
        print("[*] Trying console authorization flow instead...")
        credentials = flow.run_console()

    refresh_token = credentials.refresh_token
    if not refresh_token:
        print("\n[!] WARNING: No refresh token returned. Did you approve offline access?")
        print("    Try revoking permissions in Google Security and running this script again.")
        return

    # Output instructions
    print("\n" + "=" * 70)
    print("SUCCESS! YOUTUBE REFRESH TOKEN GENERATED")
    print("=" * 70)
    print("\nCopy and paste these values into your '.env' and GitHub Secrets:\n")
    print(f"YOUTUBE_CLIENT_ID={credentials.client_id}")
    print(f"YOUTUBE_CLIENT_SECRET={credentials.client_secret}")
    print(f"YOUTUBE_REFRESH_TOKEN={refresh_token}")
    print("\n" + "=" * 70)

    # Save to local token.json
    token_file = Path("token.json")
    with open(token_file, "w", encoding="utf-8") as f:
        json.dump(
            {
                "client_id": credentials.client_id,
                "client_secret": credentials.client_secret,
                "refresh_token": refresh_token,
            },
            f,
            indent=2,
        )
    print(f"[+] Saved backup credentials to '{token_file.name}' (already in .gitignore).\n")


if __name__ == "__main__":
    run_oauth_setup()
