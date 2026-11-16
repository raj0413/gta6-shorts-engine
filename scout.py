"""
Stream Radar & Live Detection Module (scout.py).
Monitors VIP streamer channels and YouTube searches to discover high-viewer GTA 6 live streams.
Supports both YouTube Data API v3 and high-speed scraping fallback (zero-quota dependency).
"""

import json
import re
import subprocess
import time
from dataclasses import asdict, dataclass
from typing import Any, Dict, List, Optional
import requests

from config import (
    DEFAULT_CLIP_DURATION,
    GAME_KEYWORDS,
    MIN_VIEWERS,
    STREAMERS_FILE,
    TARGET_GAME,
    YOUTUBE_API_KEY,
    is_clip_processed,
    load_history,
    load_streamers,
    logger,
)


@dataclass
class LiveStream:
    """Represents an active, verified live stream ready for analysis."""
    video_id: str
    streamer_name: str
    channel_id: str
    streamer_handle: str
    title: str
    url: str
    concurrent_viewers: int
    facecam_position: str
    facecam_box: List[float]  # [x, y, width, height] normalized
    language: str = "en"
    is_active_live: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class StreamScout:
    """Radar engine that scans target channels and global searches for GTA 6 streams."""

    def __init__(self, api_key: Optional[str] = None, min_viewers: int = MIN_VIEWERS):
        self.api_key = api_key or YOUTUBE_API_KEY
        self.min_viewers = min_viewers
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
            ),
            "Accept-Language": "en-US,en;q=0.9",
        })

    def is_game_relevant(self, title: str, description: str = "") -> bool:
        """Verifies if the stream title or description matches GTA / target game keywords."""
        content = f"{title} {description}".lower()
        return any(keyword in content for keyword in GAME_KEYWORDS)

    def probe_streamer_scraping(self, streamer: Dict[str, Any]) -> Optional[LiveStream]:
        """Probes a streamer's live endpoint using yt-dlp to extract live status and viewer count."""
        name = streamer.get("name", "Unknown")
        live_url = streamer.get("live_url") or f"https://www.youtube.com/{streamer.get('handle')}/live"
        logger.info(f"Scouting streamer '{name}' via URL: {live_url}")

        cmd = [
            "yt-dlp",
            "--dump-json",
            "--no-playlist",
            "--no-warnings",
            "--skip-download",
            live_url,
        ]

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=25,
            )
            if result.returncode != 0 or not result.stdout.strip():
                logger.debug(f"Streamer '{name}' is currently offline or unreachable.")
                return None

            info = json.loads(result.stdout.strip().split("\n")[0])
            is_live = info.get("is_live") or info.get("live_status") == "is_live"
            if not is_live:
                logger.debug(f"Streamer '{name}' returned content but is not currently LIVE.")
                return None

            title = info.get("title", "")
            viewers = info.get("concurrent_view_count") or 0
            video_id = info.get("id", "")
            video_url = f"https://www.youtube.com/watch?v={video_id}"

            logger.info(
                f"LIVE DETECTED! Streamer: {name} | Title: '{title}' | Viewers: {viewers:,}"
            )

            # Check viewer count threshold
            if viewers < self.min_viewers:
                logger.info(
                    f"Skipping '{name}': {viewers:,} viewers is below threshold ({self.min_viewers:,})."
                )
                return None

            # Check game relevance
            if not self.is_game_relevant(title, info.get("description", "")):
                logger.info(
                    f"Skipping '{name}': Title '{title}' does not match GTA 6 / game keywords."
                )
                return None

            return LiveStream(
                video_id=video_id,
                streamer_name=name,
                channel_id=info.get("channel_id", streamer.get("channel_id", "")),
                streamer_handle=streamer.get("handle", ""),
                title=title,
                url=video_url,
                concurrent_viewers=viewers,
                facecam_position=streamer.get("facecam_position", "top-right"),
                facecam_box=streamer.get("facecam_box", [0.70, 0.03, 0.28, 0.36]),
                language=streamer.get("language", "en"),
                is_active_live=True,
            )

        except subprocess.TimeoutExpired:
            logger.warning(f"Timeout while probing streamer '{name}'.")
            return None
        except Exception as e:
            logger.warning(f"Error checking streamer '{name}': {e}")
            return None

    def probe_streamer_api(self, streamer: Dict[str, Any]) -> Optional[LiveStream]:
        """Probes a channel using YouTube Data API v3."""
        if not self.api_key:
            return None

        channel_id = streamer.get("channel_id")
        if not channel_id:
            return None

        name = streamer.get("name", "Unknown")
        try:
            # 1. Search for active live broadcast in channel
            search_url = "https://www.googleapis.com/youtube/v3/search"
            params = {
                "part": "snippet",
                "channelId": channel_id,
                "eventType": "live",
                "type": "video",
                "key": self.api_key,
                "maxResults": 1,
            }
            resp = self.session.get(search_url, params=params, timeout=10)
            if resp.status_code != 200:
                logger.warning(f"YouTube API error ({resp.status_code}): {resp.text[:200]}")
                return None

            data = resp.json()
            items = data.get("items", [])
            if not items:
                return None

            item = items[0]
            video_id = item["id"]["videoId"]
            title = item["snippet"]["title"]
            desc = item["snippet"].get("description", "")

            # 2. Fetch liveStreamingDetails for concurrent viewer count
            video_url = "https://www.googleapis.com/youtube/v3/videos"
            vparams = {
                "part": "liveStreamingDetails,snippet",
                "id": video_id,
                "key": self.api_key,
            }
            vresp = self.session.get(video_url, params=vparams, timeout=10)
            if vresp.status_code != 200:
                return None

            vdata = vresp.json()
            vitems = vdata.get("items", [])
            if not vitems:
                return None

            details = vitems[0].get("liveStreamingDetails", {})
            concurrent_viewers = int(details.get("concurrentViewers", 0))

            if concurrent_viewers < self.min_viewers:
                logger.info(
                    f"API: Channel '{name}' live with {concurrent_viewers:,} viewers (below {self.min_viewers:,})."
                )
                return None

            if not self.is_game_relevant(title, desc):
                logger.info(f"API: Channel '{name}' stream '{title}' is not playing GTA 6.")
                return None

            return LiveStream(
                video_id=video_id,
                streamer_name=name,
                channel_id=channel_id,
                streamer_handle=streamer.get("handle", ""),
                title=title,
                url=f"https://www.youtube.com/watch?v={video_id}",
                concurrent_viewers=concurrent_viewers,
                facecam_position=streamer.get("facecam_position", "top-right"),
                facecam_box=streamer.get("facecam_box", [0.70, 0.03, 0.28, 0.36]),
                language=streamer.get("language", "en"),
                is_active_live=True,
            )

        except Exception as e:
            logger.warning(f"API exception while probing '{name}': {e}")
            return None

    def search_live_gta_streams(self, max_results: int = 5) -> List[LiveStream]:
        """Performs a global search for top GTA 6 live streams beyond the VIP watchlist."""
        discovered: List[LiveStream] = []
        logger.info(f"Running global live search for '{TARGET_GAME}' streams...")

        # Strategy 1: YouTube Data API v3 search
        if self.api_key:
            try:
                search_url = "https://www.googleapis.com/youtube/v3/search"
                params = {
                    "part": "snippet",
                    "q": "GTA 6 OR \"Grand Theft Auto VI\" OR GTA VI",
                    "eventType": "live",
                    "type": "video",
                    "order": "viewCount",
                    "maxResults": max_results,
                    "key": self.api_key,
                }
                resp = self.session.get(search_url, params=params, timeout=12)
                if resp.status_code == 200:
                    video_ids = [item["id"]["videoId"] for item in resp.json().get("items", []) if "videoId" in item.get("id", {})]
                    if video_ids:
                        vresp = self.session.get(
                            "https://www.googleapis.com/youtube/v3/videos",
                            params={
                                "part": "snippet,liveStreamingDetails",
                                "id": ",".join(video_ids),
                                "key": self.api_key,
                            },
                            timeout=12,
                        )
                        if vresp.status_code == 200:
                            for item in vresp.json().get("items", []):
                                vid = item["id"]
                                title = item["snippet"]["title"]
                                channel = item["snippet"]["channelTitle"]
                                details = item.get("liveStreamingDetails", {})
                                viewers = int(details.get("concurrentViewers", 0))

                                if viewers >= self.min_viewers and self.is_game_relevant(title):
                                    discovered.append(
                                        LiveStream(
                                            video_id=vid,
                                            streamer_name=channel,
                                            channel_id=item["snippet"]["channelId"],
                                            streamer_handle=f"@{re.sub(r'[^a-zA-Z0-9_]', '', channel)}",
                                            title=title,
                                            url=f"https://www.youtube.com/watch?v={vid}",
                                            concurrent_viewers=viewers,
                                            facecam_position="top-right",
                                            facecam_box=[0.70, 0.03, 0.28, 0.36],
                                            language="en",
                                            is_active_live=True,
                                        )
                                    )
            except Exception as e:
                logger.warning(f"Error during API global live search: {e}")

        # Strategy 2: yt-dlp search fallback if API produced zero results
        if not discovered:
            try:
                cmd = [
                    "yt-dlp",
                    "--dump-json",
                    "--flat-playlist",
                    "--playlist-items",
                    str(max_results),
                    "ytsearch5:GTA 6 live stream",
                ]
                res = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", timeout=25)
                if res.returncode == 0 and res.stdout.strip():
                    for line in res.stdout.strip().split("\n"):
                        if not line.strip():
                            continue
                        try:
                            info = json.loads(line)
                            vid = info.get("id")
                            title = info.get("title", "")
                            channel = info.get("uploader") or info.get("channel", "Top Streamer")
                            if vid and self.is_game_relevant(title):
                                # Probe individual stream info for accurate live status
                                individual = self.probe_video_details(vid)
                                if individual:
                                    discovered.append(individual)
                        except Exception:
                            continue
            except Exception as e:
                logger.debug(f"yt-dlp search fallback error: {e}")

        return discovered

    def probe_video_details(self, video_id: str) -> Optional[LiveStream]:
        """Probes a specific video ID or URL to check if it's currently live or a high-viewer stream."""
        url = f"https://www.youtube.com/watch?v={video_id}"
        cmd = ["yt-dlp", "--dump-json", "--no-warnings", "--skip-download", url]
        try:
            res = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", timeout=20)
            if res.returncode != 0 or not res.stdout.strip():
                return None
            info = json.loads(res.stdout.strip().split("\n")[0])
            is_live = info.get("is_live") or info.get("live_status") == "is_live"
            viewers = info.get("concurrent_view_count") or info.get("view_count") or 0
            title = info.get("title", "")
            channel = info.get("channel") or info.get("uploader", "Streamer")

            if viewers >= self.min_viewers:
                return LiveStream(
                    video_id=video_id,
                    streamer_name=channel,
                    channel_id=info.get("channel_id", ""),
                    streamer_handle=f"@{re.sub(r'[^a-zA-Z0-9_]', '', channel)}",
                    title=title,
                    url=url,
                    concurrent_viewers=viewers,
                    facecam_position="top-right",
                    facecam_box=[0.70, 0.03, 0.28, 0.36],
                    language="en",
                    is_active_live=is_live,
                )
        except Exception:
            pass
        return None

    def scout_all(self, target_streamer: Optional[str] = None) -> List[LiveStream]:
        """
        Executes complete scouting routine:
        1. Checks enabled VIP streamers from streamers.json.
        2. Falls back to global YouTube GTA 6 search if no VIP streamer is live.
        Filters out already-clipped streams.
        """
        streamers = load_streamers()
        active_streams: List[LiveStream] = []

        if target_streamer:
            streamers = [
                s for s in streamers
                if s["name"].lower() == target_streamer.lower()
                or s["handle"].lower() == target_streamer.lower()
            ]
            if not streamers:
                logger.info(f"Streamer '{target_streamer}' not found in VIP list. Creating ad-hoc profile.")
                streamers = [{
                    "name": target_streamer,
                    "handle": f"@{target_streamer.lstrip('@')}",
                    "live_url": f"https://www.youtube.com/@{target_streamer.lstrip('@')}/live",
                    "facecam_position": "top-right",
                    "facecam_box": [0.70, 0.03, 0.28, 0.36],
                    "enabled": True,
                }]

        logger.info(f"Radar active: Scanning {len(streamers)} VIP streamers for live streams...")

        for s in streamers:
            if not s.get("enabled", True):
                continue

            stream: Optional[LiveStream] = None
            # Try YouTube API first if key provided
            if self.api_key:
                stream = self.probe_streamer_api(s)

            # Fallback to direct scraping if API produced no result
            if not stream:
                stream = self.probe_streamer_scraping(s)

            if stream:
                active_streams.append(stream)

        # If no VIP streamer is currently live, initiate global search
        if not active_streams and not target_streamer:
            logger.info("No VIP streamer currently live playing GTA 6. Initiating global radar search...")
            active_streams = self.search_live_gta_streams(max_results=5)

        logger.info(f"Scout complete. Found {len(active_streams)} eligible live streams.")
        return active_streams


if __name__ == "__main__":
    # Self-test scout radar
    scout = StreamScout()
    results = scout.scout_all()
    print(f"\n[Scout Self-Test Result] Detected {len(results)} active streams:")
    for st in results:
        print(f" -> {st.streamer_name} ({st.concurrent_viewers:,} viewers): {st.title} [{st.url}]")
