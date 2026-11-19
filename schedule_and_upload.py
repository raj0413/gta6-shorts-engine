"""
schedule_and_upload.py - YouTube Shorts Publishing & Scheduling Controller.
Uploads selected shorts immediately or schedules them for peak viral times.
"""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from config import BASE_DIR, logger
from uploader import YouTubeUploader

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

# Streamer metadata map for attribution
STREAMER_META = {
    "CarryisLive": {
        "name": "CarryisLive",
        "handle": "@CarryisLive",
        "stream_url": "https://www.youtube.com/watch?v=jbcZwy3CuIQ",
    },
    "GamerFleet": {
        "name": "GamerFleet",
        "handle": "@GamerFleet",
        "stream_url": "https://www.youtube.com/watch?v=h3qEwM6k074",
    },
}

def publish_video(
    channel_name: str,
    video_path: Path,
    title: str,
    streamer_key: str,
    publish_at: Optional[str] = None,
    tags: Optional[list] = None,
    description: str = "",
):
    """Publish or schedule a single video to the target channel."""
    uploader = YouTubeUploader(channel_name=channel_name)
    meta = STREAMER_META.get(streamer_key, {
        "name": streamer_key,
        "handle": f"@{streamer_key}",
        "stream_url": "https://www.youtube.com",
    })
    
    if not tags:
        tags = ["GTA 6", "Shorts", "GTA VI", "Grand Theft Auto", "Gaming", "Viral"]

    print(f"\n=======================================================")
    action_type = f"SCHEDULING FOR {publish_at}" if publish_at else "PUBLISHING PUBLIC NOW"
    print(f"👉 [{channel_name}] {action_type}")
    print(f"   Video: {video_path.name}")
    print(f"   Title: {title}")
    print(f"=======================================================")

    result = uploader.upload_short(
        video_path=video_path,
        title=title,
        streamer_name=meta["name"],
        streamer_handle=meta["handle"],
        stream_url=meta["stream_url"],
        description=description or f"Insane GTA 6 moments with {meta['name']}! Drop a like & subscribe for daily clips!",
        tags=tags,
        publish_at=publish_at,
    )

    if result.success:
        print(f"✅ SUCCESS! Video ID: {result.video_id}")
        print(f"   Shorts URL: {result.short_url}")
        if result.scheduled_time:
            print(f"   📅 Scheduled to go Public at: {result.scheduled_time}")
        else:
            print(f"   🚀 Published Public Status: {result.privacy_status}")
    else:
        print(f"❌ FAILED: {result.error}")
        
    return result

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--channel", required=True, choices=["VicePulse", "LEONIDA 6"])
    parser.add_argument("--video", required=True, type=str)
    parser.add_argument("--title", required=True, type=str)
    parser.add_argument("--streamer", required=True, type=str)
    parser.add_argument("--publish-at", type=str, default=None, help="RFC 3339 timestamp (e.g. 2026-11-19T13:00:00Z)")
    parser.add_argument("--dry-run", action="store_true")
    
    args = parser.parse_args()
    vid_file = Path(args.video)
    if not vid_file.is_absolute():
        vid_file = BASE_DIR / vid_file
        
    publish_video(
        channel_name=args.channel,
        video_path=vid_file,
        title=args.title,
        streamer_key=args.streamer,
        publish_at=args.publish_at,
    )
