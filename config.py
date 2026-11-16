"""
Configuration Manager for GTA 6 Autonomous Shorts Engine.
Handles environment variables, constants, paths, and persistent state.
"""

import json
import logging
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional
# Base directory
BASE_DIR = Path(__file__).resolve().parent

# Try loading dotenv with python-dotenv, fallback to built-in parser
try:
    from dotenv import load_dotenv
    load_dotenv(BASE_DIR / ".env")
except ImportError:
    env_path = BASE_DIR / ".env"
    if env_path.exists():
        try:
            with open(env_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        k, v = line.split("=", 1)
                        k = k.strip()
                        v = v.strip().strip("'\"")
                        if k not in os.environ:
                            os.environ[k] = v
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Directories
# ---------------------------------------------------------------------------
TEMP_DIR = BASE_DIR / "temp"
OUTPUT_DIR = BASE_DIR / "output"
STREAMERS_FILE = BASE_DIR / "streamers.json"
CHANNELS_FILE = BASE_DIR / "channels.json"
HISTORY_FILE = BASE_DIR / "history.json"

TEMP_DIR.mkdir(parents=True, exist_ok=True)
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------------------
# Environment Variables & API Keys
# ---------------------------------------------------------------------------
GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "").strip()
YOUTUBE_API_KEY: str = os.getenv("YOUTUBE_API_KEY", "").strip()

# YouTube OAuth2 Credentials
YOUTUBE_CLIENT_ID: str = os.getenv("YOUTUBE_CLIENT_ID", "").strip()
YOUTUBE_CLIENT_SECRET: str = os.getenv("YOUTUBE_CLIENT_SECRET", "").strip()
YOUTUBE_REFRESH_TOKEN: str = os.getenv("YOUTUBE_REFRESH_TOKEN", "").strip()

# ---------------------------------------------------------------------------
# Thresholds & Operational Settings
# ---------------------------------------------------------------------------
MIN_VIEWERS: int = int(os.getenv("MIN_VIEWERS", "2000"))
MIN_VIRAL_SCORE: int = int(os.getenv("MIN_VIRAL_SCORE", "8"))
DEFAULT_CLIP_DURATION: int = int(os.getenv("DEFAULT_CLIP_DURATION", "48"))  # Seconds (40-55)
MAX_SHORTS_PER_RUN: int = int(os.getenv("MAX_SHORTS_PER_RUN", "2"))
UPLOAD_PRIVACY_STATUS: str = os.getenv("UPLOAD_PRIVACY_STATUS", "public").lower()
AUTO_UPLOAD: bool = os.getenv("AUTO_UPLOAD", "true").lower() in ("true", "1", "yes")

# Game Keywords for title matching
TARGET_GAME: str = os.getenv("TARGET_GAME", "Grand Theft Auto VI")
GAME_KEYWORDS_RAW: str = os.getenv(
    "GAME_KEYWORDS",
    "gta 6,gta vi,grand theft auto 6,grand theft auto vi,gta online,gta v,gta",
)
GAME_KEYWORDS: List[str] = [k.strip().lower() for k in GAME_KEYWORDS_RAW.split(",") if k.strip()]

# Whisper Configuration
WHISPER_MODEL: str = os.getenv("WHISPER_MODEL", "base")

# ---------------------------------------------------------------------------
# Logging Configuration
# ---------------------------------------------------------------------------
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s [%(levelname)s] [%(name)s] %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger("GTA6Engine")

# ---------------------------------------------------------------------------
# Configuration Loaders & Persistence
# ---------------------------------------------------------------------------
def load_streamers() -> List[Dict[str, Any]]:
    """Loads the VIP streamers configuration list."""
    if not STREAMERS_FILE.exists():
        logger.warning(f"Streamers file not found at {STREAMERS_FILE}")
        return []
    try:
        with open(STREAMERS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Failed to load streamers.json: {e}")
        return []


def load_channels() -> List[Dict[str, Any]]:
    """Loads the target upload channels configuration."""
    if not CHANNELS_FILE.exists():
        logger.warning(f"Channels file not found at {CHANNELS_FILE}")
        return []
    try:
        with open(CHANNELS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Failed to load channels.json: {e}")
        return []


def load_history() -> Dict[str, Any]:
    """Loads the processed video and clip history."""
    if not HISTORY_FILE.exists():
        return {"version": "1.0", "processed_videos": {}, "clips_published": []}
    try:
        with open(HISTORY_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.warning(f"Failed to read history.json, resetting to default: {e}")
        return {"version": "1.0", "processed_videos": {}, "clips_published": []}


def save_history(history_data: Dict[str, Any]) -> bool:
    """Atomically saves the updated history state."""
    temp_file = HISTORY_FILE.with_suffix(".tmp")
    try:
        with open(temp_file, "w", encoding="utf-8") as f:
            json.dump(history_data, f, indent=2, ensure_ascii=False)
        temp_file.replace(HISTORY_FILE)
        logger.info(f"Updated history successfully ({len(history_data.get('clips_published', []))} total clips logged).")
        return True
    except Exception as e:
        logger.error(f"Failed to save history: {e}")
        if temp_file.exists():
            temp_file.unlink(missing_ok=True)
        return False


def is_clip_processed(video_id: str, start_time: float, end_time: float) -> bool:
    """Checks whether this timestamp range or video has already been clipped."""
    history = load_history()
    processed = history.get("processed_videos", {})
    if video_id not in processed:
        return False

    intervals = processed[video_id].get("clips", [])
    for interval in intervals:
        c_start = interval.get("start", 0)
        c_end = interval.get("end", 0)
        # Check for significant overlap (>15 seconds overlap)
        overlap = max(0, min(end_time, c_end) - max(start_time, c_start))
        if overlap > 15:
            return True
    return False


def record_clip_in_history(
    video_id: str,
    streamer_name: str,
    stream_title: str,
    clip_start: float,
    clip_end: float,
    short_title: str,
    short_id: Optional[str] = None,
    viral_score: int = 8,
) -> None:
    """Records a newly published clip in history.json."""
    from datetime import datetime, timezone

    history = load_history()
    now_iso = datetime.now(timezone.utc).isoformat()
    history["last_updated"] = now_iso

    if "processed_videos" not in history:
        history["processed_videos"] = {}

    if video_id not in history["processed_videos"]:
        history["processed_videos"][video_id] = {
            "streamer": streamer_name,
            "title": stream_title,
            "first_scouted": now_iso,
            "clips": [],
        }

    clip_record = {
        "start": clip_start,
        "end": clip_end,
        "duration": round(clip_end - clip_start, 2),
        "short_title": short_title,
        "short_id": short_id,
        "viral_score": viral_score,
        "created_at": now_iso,
    }

    history["processed_videos"][video_id]["clips"].append(clip_record)

    if "clips_published" not in history:
        history["clips_published"] = []

    history["clips_published"].append({
        "video_id": video_id,
        "short_id": short_id,
        "streamer": streamer_name,
        "title": short_title,
        "published_at": now_iso,
        "viral_score": viral_score,
    })

    save_history(history)
