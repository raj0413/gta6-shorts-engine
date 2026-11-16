"""
YouTube Data API v3 OAuth2 Auto-Publisher (uploader.py).
Publishes rendered Shorts directly to YouTube using headless OAuth2 refresh tokens.
Zero browser interaction required — 100% cloud & GitHub Actions compatible.
Includes resumable chunked uploading with exponential backoff error recovery.
"""

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
    UPLOAD_PRIVACY_STATUS,
    YOUTUBE_CLIENT_ID,
    YOUTUBE_CLIENT_SECRET,
    YOUTUBE_REFRESH_TOKEN,
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
    error: Optional[str] = None


class YouTubeUploader:
    """Headless YouTube Publisher using OAuth2 persistent refresh tokens."""

    def __init__(
        self,
        client_id: Optional[str] = None,
        client_secret: Optional[str] = None,
        refresh_token: Optional[str] = None,
        privacy_status: str = UPLOAD_PRIVACY_STATUS,
    ):
        self.client_id = client_id or YOUTUBE_CLIENT_ID
        self.client_secret = client_secret or YOUTUBE_CLIENT_SECRET
        self.refresh_token = refresh_token or YOUTUBE_REFRESH_TOKEN
        self.privacy_status = privacy_status.lower()
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
                "YouTube OAuth2 credentials missing. Ensure YOUTUBE_CLIENT_ID, "
                "YOUTUBE_CLIENT_SECRET, and YOUTUBE_REFRESH_TOKEN are set."
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
            logger.info("OAuth2 access token successfully refreshed.")

            self._youtube_service = build("youtube", "v3", credentials=creds)
            return self._youtube_service

        except Exception as e:
            logger.error(f"Failed to authenticate YouTube API client: {e}")
            raise e

    def build_description(
        self,
        curator_description: str,
        streamer_name: str,
        streamer_handle: str,
        stream_url: str,
    ) -> str:
        """Builds standardized high-CTR description with attribution and fair use."""
        channels = load_channels()
        template = ""
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
        category_id: str = "20",  # 20 = Gaming
    ) -> UploadResult:
        """
        Uploads a rendered 9:16 vertical Short to YouTube using resumable chunked upload.
        """
        if not video_path.exists():
            return UploadResult(
                success=False,
                video_id=None,
                short_url=None,
                title=title,
                privacy_status=self.privacy_status,
                error=f"Video file not found at {video_path}",
            )

        if not self.is_configured():
            logger.warning(
                "YouTube OAuth credentials not provided. Video rendered successfully, "
                "skipping upload (Dry Run mode)."
            )
            return UploadResult(
                success=True,
                video_id="DRY_RUN_ID",
                short_url=f"local://{video_path.name}",
                title=title,
                privacy_status="local_only",
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

            body = {
                "snippet": {
                    "title": clean_title[:100],
                    "description": final_description[:4900],
                    "tags": tags[:30],
                    "categoryId": category_id,
                },
                "status": {
                    "privacyStatus": self.privacy_status,
                    "selfDeclaredMadeForKids": False,
                },
            }

            logger.info(f"Initiating resumable upload for '{clean_title}' to YouTube ({self.privacy_status})...")

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
                        logger.info(f"Upload progress: {progress}%")
                except HttpError as e:
                    if e.resp.status in RETRIABLE_STATUS_CODES:
                        retry += 1
                        if retry > MAX_RETRIES:
                            raise e
                        sleep_time = (2 ** retry) + random.random()
                        logger.warning(f"Retrying upload after status {e.resp.status} in {sleep_time:.1f}s...")
                        time.sleep(sleep_time)
                    else:
                        raise e

            video_id = response.get("id")
            short_url = f"https://www.youtube.com/shorts/{video_id}"
            logger.info(f"YOUTUBE SHORT PUBLISHED SUCCESSFULLY! URL: {short_url}")

            return UploadResult(
                success=True,
                video_id=video_id,
                short_url=short_url,
                title=clean_title,
                privacy_status=self.privacy_status,
            )

        except Exception as e:
            logger.error(f"YouTube upload failed: {e}")
            return UploadResult(
                success=False,
                video_id=None,
                short_url=None,
                title=title,
                privacy_status=self.privacy_status,
                error=str(e),
            )


if __name__ == "__main__":
    uploader = YouTubeUploader()
    configured = uploader.is_configured()
    print(f"[Uploader Self-Test] Configured: {configured} (Privacy: {uploader.privacy_status})")
