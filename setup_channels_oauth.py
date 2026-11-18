"""
Multi-Channel YouTube OAuth2 Setup & Verification Helper (setup_channels_oauth.py).
Connects VicePulse (@VicePulseHub) and LEONIDA 6 (@Leonida6Shorts) to the autonomous engine.
Generates channel-specific refresh tokens, saves token files, updates .env,
and outputs GitHub Secrets values.

Includes Incognito auto-launch and state-safe code extraction fallback.
"""

import argparse
import json
import os
import re
import sys
import urllib.parse
import webbrowser
from pathlib import Path
from google_auth_oauthlib.flow import InstalledAppFlow
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube",
]

BASE_DIR = Path(__file__).resolve().parent
CHANNELS_FILE = BASE_DIR / "channels.json"
ENV_FILE = BASE_DIR / ".env"
CLIENT_SECRETS_FILE = BASE_DIR / "client_secrets.json"


def load_channels_config():
    """Load channel targets from channels.json."""
    if not CHANNELS_FILE.exists():
        print(f"[-] Error: {CHANNELS_FILE} not found.")
        sys.exit(1)
    with open(CHANNELS_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def get_client_config():
    """Load OAuth2 client credentials from file or .env."""
    if CLIENT_SECRETS_FILE.exists():
        return str(CLIENT_SECRETS_FILE), None

    client_id = os.getenv("YOUTUBE_CLIENT_ID", "").strip()
    client_secret = os.getenv("YOUTUBE_CLIENT_SECRET", "").strip()

    if client_id and client_secret:
        return None, {
            "installed": {
                "client_id": client_id,
                "client_secret": client_secret,
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "redirect_uris": ["http://localhost:8080/"],
            }
        }

    print("[-] Missing client_secrets.json and YOUTUBE_CLIENT_ID/SECRET in .env.")
    sys.exit(1)


def update_env_variable(key: str, value: str):
    """Safely updates or appends an environment variable in .env."""
    if not ENV_FILE.exists():
        ENV_FILE.write_text(f"{key}={value}\n", encoding="utf-8")
        return

    content = ENV_FILE.read_text(encoding="utf-8")
    pattern = rf"^{re.escape(key)}=.*$"
    if re.search(pattern, content, flags=re.MULTILINE):
        new_content = re.sub(pattern, f"{key}={value}", content, flags=re.MULTILINE)
    else:
        new_content = content.rstrip() + f"\n{key}={value}\n"
    ENV_FILE.write_text(new_content, encoding="utf-8")


def get_channel_info_from_token(client_id: str, client_secret: str, refresh_token: str):
    """Queries YouTube API to verify which channel the token is attached to."""
    try:
        creds = Credentials(
            token=None,
            refresh_token=refresh_token,
            token_uri="https://oauth2.googleapis.com/token",
            client_id=client_id,
            client_secret=client_secret,
            scopes=SCOPES,
        )
        service = build("youtube", "v3", credentials=creds)
        res = service.channels().list(part="snippet,statistics", mine=True).execute()
        items = res.get("items", [])
        if items:
            item = items[0]
            snippet = item.get("snippet", {})
            stats = item.get("statistics", {})
            return {
                "title": snippet.get("title", "Unknown"),
                "id": item.get("id", ""),
                "custom_url": snippet.get("customUrl", ""),
                "subscribers": stats.get("subscriberCount", "0"),
                "videos": stats.get("videoCount", "0"),
            }
    except Exception as e:
        return {"error": str(e)}
    return None


def get_incognito_browser_name():
    """Registers and returns the name of an incognito browser if available."""
    chrome_paths = [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    ]
    edge_paths = [
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    ]

    for p in chrome_paths:
        if os.path.exists(p):
            try:
                webbrowser.register("chrome_incognito", None, webbrowser.BackgroundBrowser([p, "--incognito"]))
                return "chrome_incognito"
            except Exception:
                pass

    for p in edge_paths:
        if os.path.exists(p):
            try:
                webbrowser.register("edge_inprivate", None, webbrowser.BackgroundBrowser([p, "-inprivate"]))
                return "edge_inprivate"
            except Exception:
                pass

    return None


def authorize_channel(channel_target: dict):
    """Runs OAuth authorization with Incognito auto-launch and state-safe verification."""
    channel_name = channel_target["channel_name"]
    expected_id = channel_target.get("channel_id", "")
    handle = channel_target.get("handle", "")
    token_file_name = channel_target.get("token_file", f"token_{channel_name.lower().replace(' ', '_')}.json")
    env_var_name = channel_target.get("env_refresh_token", f"YOUTUBE_REFRESH_TOKEN_{channel_name.upper().replace(' ', '_')}")

    print("\n" + "=" * 75)
    print(f"👉 AUTHORIZING CHANNEL: {channel_name} ({handle})")
    print(f"   Target Channel ID:   {expected_id}")
    print("=" * 75)

    secrets_path, client_config = get_client_config()
    if secrets_path:
        flow = InstalledAppFlow.from_client_secrets_file(secrets_path, SCOPES)
    else:
        flow = InstalledAppFlow.from_client_config(client_config, SCOPES)

    incognito_browser = get_incognito_browser_name()

    prompt_msg = (
        "\n[+] INCOGNITO WINDOW OPENED AUTOMATICALLY!\n"
        "---------------------------------------------------------------------------\n"
        "👉 If not opened, copy this exact link into Incognito (Ctrl+Shift+N):\n"
        "{url}\n"
        "---------------------------------------------------------------------------\n"
        "📋 INSTRUCTIONS:\n"
        "  1. Log in with: koshtiraj2004@gmail.com\n"
        f"  2. Select Brand Account: **{channel_name}**\n"
        "  3. Check all permission boxes & click Continue / Allow.\n"
        "  4. Google will redirect back to localhost:8080.\n\n"
        "[+] Waiting for Google authorization redirect on http://localhost:8080/ ..."
    )

    credentials = None
    try:
        credentials = flow.run_local_server(
            port=8080,
            browser=incognito_browser,
            authorization_prompt_message=prompt_msg,
            prompt="consent",
            access_type="offline",
        )
    except Exception as e:
        print(f"\n[!] Local server notification: {e}")

    # Fallback: if local server had state warning or redirect issue, extract code directly
    if not credentials or not getattr(credentials, "refresh_token", None):
        print("\n" + "!" * 75)
        print("MANUAL FALLBACK:")
        print("If your browser redirected to localhost:8080, copy the URL from address bar:")
        print("(Looks like: http://localhost:8080/?state=...&code=4/0A...)")
        print("!" * 75)
        user_input = input("Paste Redirect URL (or press Enter to cancel): ").strip()
        if user_input:
            try:
                parsed = urllib.parse.urlparse(user_input)
                qs = urllib.parse.parse_qs(parsed.query)
                code = qs.get("code", [None])[0] or user_input
                print(f"[+] Exchanging code directly for tokens (bypassing state check)...")
                flow.fetch_token(code=code)
                credentials = flow.credentials
            except Exception as fe:
                print(f"[-] Token exchange error: {fe}")

    if not credentials or not getattr(credentials, "refresh_token", None):
        print(f"\n[-] ERROR: Authorization failed for {channel_name}. No refresh token obtained.")
        return False

    client_id = credentials.client_id
    client_secret = credentials.client_secret
    refresh_token = credentials.refresh_token

    # Verify channel identity via API
    print("\n[+] Verifying channel identity via YouTube Data API...")
    info = get_channel_info_from_token(client_id, client_secret, refresh_token)

    if info and "id" in info:
        actual_name = info["title"]
        actual_id = info["id"]
        actual_url = info.get("custom_url", "")
        print(f"    ✅ Authenticated Channel: '{actual_name}' (ID: {actual_id}, Handle: {actual_url})")

        if expected_id and actual_id != expected_id:
            print("\n" + "⚠️" * 35)
            print(f"WARNING: Selected '{actual_name}' (ID: {actual_id})")
            print(f"does not match target '{channel_name}' (ID: {expected_id})!")
            print("Did you select a different channel in Google Account selector?")
            print("⚠️" * 35 + "\n")
        else:
            print(f"    🎉 Verified! Correct channel connected: '{channel_name}'!")

    # Save to channel token file
    token_path = BASE_DIR / token_file_name
    with open(token_path, "w", encoding="utf-8") as f:
        json.dump(
            {
                "channel_name": channel_name,
                "channel_id": info.get("id", expected_id) if info else expected_id,
                "client_id": client_id,
                "client_secret": client_secret,
                "refresh_token": refresh_token,
            },
            f,
            indent=2,
        )
    print(f"[+] Saved credentials to '{token_file_name}'")

    # Update .env
    update_env_variable(env_var_name, refresh_token)
    update_env_variable("YOUTUBE_CLIENT_ID", client_id)
    update_env_variable("YOUTUBE_CLIENT_SECRET", client_secret)
    print(f"[+] Updated .env with {env_var_name}")

    print("\n" + "-" * 75)
    print(f"📋 GITHUB SECRET VALUE FOR {env_var_name}:")
    print(f"{refresh_token}")
    print("-" * 75 + "\n")
    return True


def check_status():
    """Tests and displays authentication status for all configured channels."""
    channels = load_channels_config()
    secrets_path, client_config = get_client_config()
    client_id = os.getenv("YOUTUBE_CLIENT_ID", "")
    client_secret = os.getenv("YOUTUBE_CLIENT_SECRET", "")

    if secrets_path:
        with open(secrets_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            client_data = data.get("installed") or data.get("web") or {}
            client_id = client_data.get("client_id", client_id)
            client_secret = client_data.get("client_secret", client_secret)

    print("=" * 75)
    print("YOUTUBE CHANNELS CONNECTION STATUS CHECK")
    print("=" * 75)

    for ch in channels:
        name = ch["channel_name"]
        expected_id = ch.get("channel_id", "")
        handle = ch.get("handle", "")
        token_file = ch.get("token_file", "")
        env_var = ch.get("env_refresh_token", "")

        refresh_token = os.getenv(env_var, "").strip()
        token_path = BASE_DIR / token_file if token_file else None

        if not refresh_token and token_path and token_path.exists():
            try:
                with open(token_path, "r", encoding="utf-8") as tf:
                    tdata = json.load(tf)
                    refresh_token = tdata.get("refresh_token", "")
            except Exception:
                pass

        print(f"\n📌 Channel: {name} ({handle}) [ID: {expected_id}]")
        if not refresh_token:
            print("   Status: ❌ NOT CONNECTED (Missing refresh token)")
            print(f"   Action: Run 'python setup_channels_oauth.py --channel \"{name}\"'")
            continue

        info = get_channel_info_from_token(client_id, client_secret, refresh_token)
        if info and "id" in info:
            print(f"   Status:        ✅ CONNECTED & AUTHENTICATED")
            print(f"   Live Title:    {info['title']}")
            print(f"   Channel ID:    {info['id']}")
            print(f"   Handle:        {info.get('custom_url', 'N/A')}")
            print(f"   Subscribers:   {info.get('subscribers', '0')}")
            print(f"   Total Videos:  {info.get('videos', '0')}")
            if expected_id and info["id"] != expected_id:
                print(f"   ⚠️ WARNING: Connected ID does not match expected ID ({expected_id})")
        else:
            err = info.get("error", "Unknown error") if info else "Failed to verify"
            print(f"   Status: ⚠️ TOKEN PRESENT BUT VERIFICATION FAILED: {err}")

    print("\n" + "=" * 75)


def main():
    parser = argparse.ArgumentParser(description="Multi-Channel YouTube OAuth Connection Setup")
    parser.add_argument("--channel", type=str, help="Channel name to authorize (e.g. 'VicePulse' or 'LEONIDA 6')")
    parser.add_argument("--all", action="store_true", help="Authorize all configured channels sequentially")
    parser.add_argument("--check", action="store_true", help="Check status of all connected channels")

    args = parser.parse_args()

    # Load existing .env
    from config import BASE_DIR
    try:
        from dotenv import load_dotenv
        load_dotenv(BASE_DIR / ".env", override=True)
    except Exception:
        pass

    channels = load_channels_config()

    if args.check:
        check_status()
        return

    if args.channel:
        target = next((c for c in channels if c["channel_name"].lower() == args.channel.lower()), None)
        if not target:
            print(f"[-] Channel '{args.channel}' not found in channels.json.")
            print(f"    Available: {[c['channel_name'] for c in channels]}")
            sys.exit(1)
        authorize_channel(target)
        return

    if args.all:
        for ch in channels:
            success = authorize_channel(ch)
            if not success:
                print(f"[-] Stopping batch authorization after failure on {ch['channel_name']}.")
                break
        return

    # Interactive menu
    print("=" * 75)
    print("GTA 6 SHORTS ENGINE — MULTI-CHANNEL OAUTH2 SETUP")
    print("=" * 75)
    print("Select an option:")
    print("  [1] Connect 'VicePulse' (@VicePulseHub)")
    print("  [2] Connect 'LEONIDA 6' (@Leonida6Shorts)")
    print("  [3] Connect BOTH channels sequentially")
    print("  [4] Check connection status of all channels")
    print("  [0] Exit")
    print("-" * 75)

    choice = input("Enter choice [1-4, 0]: ").strip()
    if choice == "1":
        target = next((c for c in channels if "vicepulse" in c["channel_name"].lower()), channels[0])
        authorize_channel(target)
    elif choice == "2":
        target = next((c for c in channels if "leonida" in c["channel_name"].lower()), channels[1])
        authorize_channel(target)
    elif choice == "3":
        for ch in channels:
            success = authorize_channel(ch)
            if not success:
                break
    elif choice == "4":
        check_status()
    else:
        print("Exiting.")


if __name__ == "__main__":
    main()
