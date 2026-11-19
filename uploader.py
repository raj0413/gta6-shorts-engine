"""
YouTube Data API v3 OAuth2 Auto-Publisher (uploader.py).
Publishes rendered Shorts directly to YouTube using headless OAuth2 refresh tokens.
Supports Multi-Channel publishing (e.g. VicePulse and LEONIDA 6).
Zero browser interaction required — 100% cloud & GitHub Actions compatible.
Includes resumable chunked uploading with exponential backoff error recovery.
"""

import json
import os
import random
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload

from config import (
    BASE_DIR,
    UPLOAD_PRIVACY_STATUS,
    YOUTUBE_CLIENT_ID,
    YOUTUBE_CLIENT_SECRET,
    YOUTUBE_REFRESH_TOKEN,
    get_channel_config,
    load_channels,
    logger,
)

YOUTUBE_UPLOAD_SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube",
]
MAX_RETRIES = 5
RETRIABLE_STATUS_CODES = [500, 502, 503, 504]


@dataclass
class UploadResult:
    """Represents the outcome of a YouTube Short publication."""
    success: bool
    video_id: Optional[str]
    short_url: Optional[str]
    title: str
    privacy_status: str
    channel_name: str = "Default"
    scheduled_time: Optional[str] = None
    error: Optional[str] = None


class YouTubeUploader:
    """Headless YouTube Publisher using OAuth2 persistent refresh tokens."""

    def __init__(
        self,
        channel: Optional[Dict[str, Any]] = None,
        channel_name: Optional[str] = None,
        client_id: Optional[str] = None,
        client_secret: Optional[str] = None,
        refresh_token: Optional[str] = None,
        privacy_status: Optional[str] = None,
    ):
        if channel is None and channel_name:
            channel = get_channel_config(channel_name)

        self.channel = channel or {}
        self.channel_name = self.channel.get("channel_name", channel_name or "Default")
        self.channel_id = self.channel.get("channel_id", "")

        resolved_refresh = refresh_token
        resolved_client_id = client_id or YOUTUBE_CLIENT_ID
        resolved_client_secret = client_secret or YOUTUBE_CLIENT_SECRET

        # 1. Check channel-specific env variable
        env_var_name = self.channel.get("env_refresh_token")
        if not resolved_refresh and env_var_name:
            resolved_refresh = os.getenv(env_var_name, "").strip()

        # 2. Check channel-specific token JSON file
        token_file_name = self.channel.get("token_file")
        if token_file_name:
            token_path = BASE_DIR / token_file_name
            if token_path.exists():
                try:
                    with open(token_path, "r", encoding="utf-8") as f:
                        tdata = json.load(f)
                        if not resolved_refresh:
                            resolved_refresh = tdata.get("refresh_token")
                        if not resolved_client_id:
                            resolved_client_id = tdata.get("client_id")
                        if not resolved_client_secret:
                            resolved_client_secret = tdata.get("client_secret")
                except Exception as e:
                    logger.warning(f"Error reading token file {token_path}: {e}")

        # 3. Fallback to default token.json if still not resolved
        if not resolved_refresh:
            default_token_path = BASE_DIR / "token.json"
            if default_token_path.exists():
                try:
                    with open(default_token_path, "r", encoding="utf-8") as f:
                        tdata = json.load(f)
                        resolved_refresh = tdata.get("refresh_token")
                        if not resolved_client_id:
                            resolved_client_id = tdata.get("client_id")
                        if not resolved_client_secret:
                            resolved_client_secret = tdata.get("client_secret")
                except Exception:
                    pass

        self.client_id = resolved_client_id or YOUTUBE_CLIENT_ID
        self.client_secret = resolved_client_secret or YOUTUBE_CLIENT_SECRET
        self.refresh_token = resolved_refresh or YOUTUBE_REFRESH_TOKEN

        ch_privacy = self.channel.get("default_privacy")
        self.privacy_status = (privacy_status or ch_privacy or UPLOAD_PRIVACY_STATUS).lower()
        self._youtube_service = None

    def is_configured(self) -> bool:
        """Checks if all required OAuth2 credentials are present."""
        return bool(self.client_id and self.client_secret and self.refresh_token)

    def _get_authenticated_service(self):
        """Constructs an authorized YouTube service using persistent refresh token."""
        if self._youtube_service is not None:
            return self._youtube_service

        if not self.is_configured():
            raise ValueError(
                f"YouTube OAuth2 credentials missing for channel '{self.channel_name}'. "
                f"Ensure client credentials and refresh token are set."
            )

        try:
            creds = Credentials(
                token=None,
                refresh_token=self.refresh_token,
                token_uri="https://oauth2.googleapis.com/token",
                client_id=self.client_id,
                client_secret=self.client_secret,
                scopes=YOUTUBE_UPLOAD_SCOPES,
            )

            # Force token refresh to verify credentials
            creds.refresh(Request())
            logger.info(f"OAuth2 access token successfully refreshed for channel '{self.channel_name}'.")

            self._youtube_service = build("youtube", "v3", credentials=creds)
            return self._youtube_service

        except Exception as e:
            logger.error(f"Failed to authenticate YouTube API client for '{self.channel_name}': {e}")
            raise e

    def build_description(
        self,
        curator_description: str,
        streamer_name: str,
        streamer_handle: str,
        stream_url: str,
    ) -> str:
        """Builds standardized high-CTR description with attribution and fair use."""
        template = self.channel.get("description_template")
        if not template:
            channels = load_channels()
            if channels:
                template = channels[0].get("description_template", "")

        if template:
            try:
                return template.format(
                    streamer_name=streamer_name,
                    streamer_handle=streamer_handle,
                    stream_url=stream_url,
                )
            except Exception:
                pass

        return (
            f"{curator_description}\n\n"
            f"👑 Featured Streamer: {streamer_name} ({streamer_handle})\n"
            f"📺 Original Live Stream: {stream_url}\n\n"
            f"⚠️ Fair Use Notice: Content curated under fair use policy for entertainment, "
            f"critique, and commentary highlights. All rights belong to original creators.\n\n"
            f"#Shorts #GTA6 #Gaming #GrandTheftAuto #Viral"
        )

    def upload_short(
        self,
        video_path: Path,
        title: str,
        streamer_name: str,
        streamer_handle: str,
        stream_url: str,
        description: str,
        tags: List[str],
        category_id: Optional[str] = None,
        publish_at: Optional[str] = None,
    ) -> UploadResult:
        """
        Uploads a rendered 9:16 vertical Short to YouTube using resumable chunked upload.
        If publish_at (ISO 8601 string, e.g. '2026-11-19T13:30:00Z') is provided,
        the video will be uploaded as private and scheduled to go public at that time.
        """
        if not video_path.exists():
            return UploadResult(
                success=False,
                video_id=None,
                short_url=None,
                title=title,
                privacy_status=self.privacy_status,
                channel_name=self.channel_name,
                error=f"Video file not found at {video_path}",
            )

        if not self.is_configured():
            logger.warning(
                f"YouTube OAuth credentials not provided for channel '{self.channel_name}'. "
                f"Video rendered successfully, skipping upload (Dry Run mode)."
            )
            return UploadResult(
                success=True,
                video_id="DRY_RUN_ID",
                short_url=f"local://{video_path.name}",
                title=title,
                privacy_status="local_only",
                channel_name=self.channel_name,
            )

        try:
            youtube = self._get_authenticated_service()

            final_description = self.build_description(
                curator_description=description,
                streamer_name=streamer_name,
                streamer_handle=streamer_handle,
                stream_url=stream_url,
            )

            # Ensure #Shorts is in title or description for Shorts shelf placement
            clean_title = title.strip()
            if "#Shorts" not in clean_title and "#shorts" not in clean_title:
                clean_title = f"{clean_title[:50]} #Shorts"

            # Merge channel tags with AI tags
            channel_tags = self.channel.get("default_tags", [])
            merged_tags = list(tags)
            for ct in channel_tags:
                if ct not in merged_tags:
                    merged_tags.append(ct)

            target_category = category_id or self.channel.get("default_category_id", "20")

            status_payload = {
                "privacyStatus": "private" if publish_at else self.privacy_status,
                "selfDeclaredMadeForKids": False,
            }
            if publish_at:
                status_payload["publishAt"] = publish_at

            body = {
                "snippet": {
                    "title": clean_title[:100],
                    "description": final_description[:4900],
                    "tags": merged_tags[:30],
                    "categoryId": target_category,
                },
                "status": status_payload,
            }

            sched_info = f" [Scheduled: {publish_at}]" if publish_at else f" ({status_payload['privacyStatus']})"
            logger.info(
                f"Initiating resumable upload to '{self.channel_name}' for '{clean_title}'{sched_info}..."
            )

            # 5MB chunk size for reliable upload
            media = MediaFileUpload(
                str(video_path),
                mimetype="video/mp4",
                resumable=True,
                chunksize=5 * 1024 * 1024,
            )

            request = youtube.videos().insert(
                part="snippet,status",
                body=body,
                media_body=media,
            )

            response = None
            retry = 0

            while response is None:
                try:
                    status, response = request.next_chunk()
                    if status:
                        progress = int(status.progress() * 100)
                        logger.info(f"[{self.channel_name}] Upload progress: {progress}%")
                except (HttpError, OSError, Exception) as e:
                    if isinstance(e, HttpError) and e.resp.status not in RETRIABLE_STATUS_CODES:
                        raise e
                    retry += 1
                    if retry > MAX_RETRIES:
                        raise e
                    sleep_time = (2 ** retry) + random.random()
                    logger.warning(
                        f"[{self.channel_name}] Network/HTTP hiccup ({e}). Retrying chunk upload ({retry}/{MAX_RETRIES}) in {sleep_time:.1f}s..."
                    )
                    time.sleep(sleep_time)

            video_id = response.get("id")
            short_url = f"https://www.youtube.com/shorts/{video_id}"
            logger.info(f"[{self.channel_name}] SHORT PUBLISHED SUCCESSFULLY! URL: {short_url}")

            return UploadResult(
                success=True,
                video_id=video_id,
                short_url=short_url,
                title=clean_title,
                privacy_status="private" if publish_at else self.privacy_status,
                channel_name=self.channel_name,
                scheduled_time=publish_at,
            )

        except Exception as e:
            logger.error(f"[{self.channel_name}] YouTube upload failed: {e}")
            return UploadResult(
                success=False,
                video_id=None,
                short_url=None,
                title=title,
                privacy_status=self.privacy_status,
                channel_name=self.channel_name,
                error=str(e),
            )


def get_channel_uploaders(target_channel: Optional[str] = None) -> List[YouTubeUploader]:
    """
    Returns configured YouTubeUploader instances.
    If target_channel is given, returns that specific channel's uploader.
    Otherwise, returns uploaders for all enabled channels from channels.json.
    """
    channels = load_channels()
    if target_channel:
        ch = get_channel_config(target_channel)
        if ch:
            return [YouTubeUploader(channel=ch)]
        logger.warning(f"Target channel '{target_channel}' not found. Using default credentials.")
        return [YouTubeUploader()]

    enabled_channels = [ch for ch in channels if ch.get("enabled", True)]
    if enabled_channels:
        return [YouTubeUploader(channel=ch) for ch in enabled_channels]

    return [YouTubeUploader()]


if __name__ == "__main__":
    uploaders = get_channel_uploaders()
    for u in uploaders:
        print(f"[Uploader] Channel: '{u.channel_name}' | Configured: {u.is_configured()} (Privacy: {u.privacy_status})")
