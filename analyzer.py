"""
Highlight & Peak Detection Engine (analyzer.py).
Detects viral moments without downloading the full multi-hour video.
Combines:
  1. Live Chat Velocity & Keyword Spikes (LMAOO, WTF, 💀, NO WAY, CLUTCH).
  2. Audio Decibel & RMS Energy Spikes (streamer screams, loud laughter, explosions).
Produces candidate 40-55 second highlight windows with exact start and end timestamps.
"""

import json
import math
import os
import re
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from config import (
    DEFAULT_CLIP_DURATION,
    TEMP_DIR,
    is_clip_processed,
    logger,
)

# Viral keywords and emojis with weighting
VIRAL_KEYWORDS = {
    "💀": 3.0,
    "😭": 2.5,
    "lmao": 2.0,
    "lmaooo": 3.0,
    "wtf": 3.0,
    "no way": 3.5,
    "noway": 3.0,
    "hacker": 2.5,
    "clutch": 3.0,
    "omg": 2.0,
    "brooo": 2.5,
    "dead": 2.0,
    "pog": 2.0,
    "w": 1.5,
    "l": 1.5,
    "clip it": 4.0,
    "clip that": 4.0,
    "clip": 2.5,
    "sheesh": 2.5,
    "caught in 4k": 3.5,
    "cooked": 2.5,
    "banned": 3.0,
    "rage": 2.5,
    "scream": 2.5,
}


@dataclass
class HighlightCandidate:
    """Represents a detected peak moment candidate for Short conversion."""
    video_id: str
    start_time: float       # In seconds
    end_time: float         # In seconds
    duration: float        # Total duration in seconds
    score: float           # Normalized virality score (0 - 100)
    spike_type: str        # 'chat_velocity', 'audio_rms', or 'hybrid'
    peak_timestamp: float  # Exact moment of maximum climax
    keywords_found: List[str]
    reason: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class HighlightAnalyzer:
    """Detects peak moments using chat velocity and audio intensity analysis."""

    def __init__(self, target_duration: int = DEFAULT_CLIP_DURATION):
        self.target_duration = target_duration

    def download_live_chat(self, video_url: str, video_id: str) -> Optional[Path]:
        """
        Attempts to download live chat replay JSON for the video using yt-dlp.
        Returns path to .live_chat.json or None if chat replay is not available.
        """
        output_base = TEMP_DIR / f"{video_id}_chat"
        expected_chat_file = TEMP_DIR / f"{video_id}_chat.live_chat.json"

        if expected_chat_file.exists() and expected_chat_file.stat().st_size > 1000:
            logger.info(f"Using cached live chat replay: {expected_chat_file.name}")
            return expected_chat_file

        logger.info(f"Downloading live chat replay for {video_id}...")
        cmd = [
            "yt-dlp",
            "--skip-download",
            "--sub-langs", "live_chat",
            "--write-sub",
            "-o", str(output_base),
            video_url,
        ]

        try:
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
            if expected_chat_file.exists() and expected_chat_file.stat().st_size > 1000:
                logger.info(f"Live chat replay downloaded: {expected_chat_file.stat().st_size / 1024:.1f} KB")
                return expected_chat_file

            # Check if any .json was written with matching base
            for f in TEMP_DIR.glob(f"{video_id}_chat*.json"):
                if f.stat().st_size > 1000:
                    return f

            logger.info("Live chat replay not available for this stream (stream may be live or chat disabled).")
            return None
        except Exception as e:
            logger.warning(f"Failed to fetch live chat: {e}")
            return None

    def analyze_chat_velocity(self, chat_path: Path, video_id: str) -> List[HighlightCandidate]:
        """
        Parses live chat JSON to compute messages/second and viral keyword density.
        Returns candidate highlight windows centered on velocity peaks.
        """
        logger.info(f"Analyzing chat velocity from {chat_path.name}...")
        bucket_size = 5.0  # 5-second buckets
        buckets: Dict[int, Dict[str, Any]] = {}

        try:
            with open(chat_path, "r", encoding="utf-8", errors="ignore") as f:
                for line in f:
                    if not line.strip():
                        continue
                    try:
                        entry = json.loads(line)
                        action = entry.get("replayChatItemAction", {})
                        actions = action.get("actions", [])
                        if not actions:
                            continue

                        offset_msec = int(action.get("videoOffsetTimeMsec", 0))
                        offset_sec = max(0.0, offset_msec / 1000.0)

                        # Extract text runs
                        text = ""
                        for a in actions:
                            item = (
                                a.get("addChatItemAction", {}).get("item", {})
                                .get("liveChatTextMessageRenderer", {})
                            )
                            runs = item.get("message", {}).get("runs", [])
                            for r in runs:
                                text += " " + r.get("text", "")

                        text_lower = text.lower()
                        bucket_idx = int(offset_sec // bucket_size)

                        if bucket_idx not in buckets:
                            buckets[bucket_idx] = {
                                "timestamp": bucket_idx * bucket_size,
                                "count": 0,
                                "keywords": [],
                                "keyword_score": 0.0,
                            }

                        buckets[bucket_idx]["count"] += 1

                        for kw, weight in VIRAL_KEYWORDS.items():
                            if kw in text_lower:
                                buckets[bucket_idx]["keywords"].append(kw)
                                buckets[bucket_idx]["keyword_score"] += weight

                    except Exception:
                        continue

            if not buckets:
                logger.info("No chat messages successfully parsed.")
                return []

            max_bucket = max(buckets.keys())
            time_series_scores: List[float] = []
            timestamps: List[float] = []

            for i in range(max_bucket + 1):
                b = buckets.get(i, {"count": 0, "keyword_score": 0.0, "timestamp": i * bucket_size})
                # Score combines raw velocity + keyword multiplier
                score = (b["count"] * 1.5) + (b["keyword_score"] * 3.0)
                time_series_scores.append(score)
                timestamps.append(i * bucket_size)

            scores_arr = np.array(time_series_scores, dtype=np.float32)
            if len(scores_arr) < 5 or np.max(scores_arr) <= 0:
                return []

            mean = float(np.mean(scores_arr))
            std = float(np.std(scores_arr))
            threshold = mean + (1.8 * std)

            logger.info(f"Chat velocity statistics: Mean={mean:.2f}, Std={std:.2f}, Threshold={threshold:.2f}")

            # Find local peaks above threshold
            candidates: List[HighlightCandidate] = []
            min_peak_distance = int(60 / bucket_size)  # Keep peaks at least 60s apart

            sorted_indices = np.argsort(scores_arr)[::-1]
            chosen_timestamps: List[float] = []

            for idx in sorted_indices:
                if scores_arr[idx] < threshold:
                    break

                peak_time = timestamps[idx]
                # Check distance from already selected peaks
                if any(abs(peak_time - ct) < 60 for ct in chosen_timestamps):
                    continue

                chosen_timestamps.append(peak_time)

                # Format 48-second highlight window:
                # 30 seconds buildup + climax + 18 seconds reaction
                start_time = max(0.0, peak_time - 30.0)
                end_time = start_time + self.target_duration

                if is_clip_processed(video_id, start_time, end_time):
                    logger.debug(f"Skipping peak at {peak_time:.1f}s (already clipped in history).")
                    continue

                # Gather top keywords in this window
                window_keywords = []
                w_start_b = int(start_time // bucket_size)
                w_end_b = int(end_time // bucket_size)
                for b_i in range(w_start_b, w_end_b + 1):
                    if b_i in buckets:
                        window_keywords.extend(buckets[b_i]["keywords"])

                unique_keywords = list(dict.fromkeys(window_keywords))[:8]
                normalized_score = min(100.0, float((scores_arr[idx] / (threshold + 1e-5)) * 50.0))

                candidate = HighlightCandidate(
                    video_id=video_id,
                    start_time=round(start_time, 2),
                    end_time=round(end_time, 2),
                    duration=round(end_time - start_time, 2),
                    score=round(normalized_score, 1),
                    spike_type="chat_velocity",
                    peak_timestamp=round(peak_time, 2),
                    keywords_found=unique_keywords,
                    reason=(
                        f"Chat velocity spike of {scores_arr[idx]:.1f} pts at {peak_time:.1f}s "
                        f"with keywords: {', '.join(unique_keywords[:4]) or 'LMAO/WTF'}"
                    ),
                )
                candidates.append(candidate)

                if len(candidates) >= 5:
                    break

            logger.info(f"Identified {len(candidates)} chat velocity candidates.")
            return candidates

        except Exception as e:
            logger.error(f"Error during chat velocity calculation: {e}")
            return []

    def download_audio_segment(
        self, video_url: str, video_id: str, start_sec: Optional[float] = None, duration_sec: Optional[float] = None
    ) -> Optional[Path]:
        """
        Downloads lightweight compressed audio stream (m4a/aac) without video.
        Uses yt-dlp section downloading to minimize network and disk overhead.
        """
        suffix = f"_{int(start_sec)}_{int(duration_sec)}" if start_sec is not None else "_full"
        output_file = TEMP_DIR / f"{video_id}{suffix}.m4a"

        if output_file.exists() and output_file.stat().st_size > 10000:
            return output_file

        logger.info(f"Downloading lightweight audio slice for {video_id}...")
        cmd = [
            "yt-dlp",
            "-f", "ba[ext=m4a]/ba[abr<=96]/ba",
            "--no-warnings",
            "-o", str(output_file),
        ]

        if start_sec is not None and duration_sec is not None:
            end_sec = start_sec + duration_sec
            cmd.extend(["--download-sections", f"*{start_sec}-{end_sec}"])

        cmd.append(video_url)

        try:
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
            if output_file.exists() and output_file.stat().st_size > 5000:
                logger.info(f"Audio downloaded: {output_file.stat().st_size / 1024:.1f} KB")
                return output_file
            logger.warning(f"Audio download failed. Stderr: {res.stderr[:200]}")
            return None
        except Exception as e:
            logger.error(f"Error downloading audio: {e}")
            return None

    def analyze_audio_decibels(
        self, audio_path: Path, video_id: str, offset_seconds: float = 0.0
    ) -> List[HighlightCandidate]:
        """
        Computes RMS decibel volume levels across audio to find screaming / reaction peaks.
        Uses FFmpeg raw PCM stream decoded into NumPy arrays for blazing-fast CPU computation.
        """
        logger.info(f"Analyzing audio decibel levels in {audio_path.name}...")
        sample_rate = 16000
        cmd = [
            "ffmpeg",
            "-v", "error",
            "-i", str(audio_path),
            "-f", "f32le",
            "-acodec", "pcm_f32le",
            "-ac", "1",
            "-ar", str(sample_rate),
            "-",
        ]

        try:
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            raw_audio, _ = proc.communicate(timeout=90)
            if not raw_audio:
                logger.warning("Empty audio decoded from FFmpeg.")
                return []

            samples = np.frombuffer(raw_audio, dtype=np.float32)
            if len(samples) < sample_rate * 5:
                return []

            # Compute RMS over 0.5-second windows
            window_size = int(sample_rate * 0.5)
            hop_size = int(sample_rate * 0.25)
            num_windows = (len(samples) - window_size) // hop_size

            rms_values = []
            time_offsets = []

            for i in range(num_windows):
                start = i * hop_size
                win = samples[start : start + window_size]
                rms = np.sqrt(np.mean(win**2) + 1e-12)
                db = 20.0 * math.log10(rms)
                rms_values.append(db)
                time_offsets.append(offset_seconds + (start / sample_rate))

            db_arr = np.array(rms_values, dtype=np.float32)
            # Clip minimum silence floor to -60 dB
            db_arr = np.clip(db_arr, -60.0, 0.0)

            mean_db = float(np.mean(db_arr))
            max_db = float(np.max(db_arr))
            std_db = float(np.std(db_arr))
            threshold_db = mean_db + (2.0 * std_db)

            logger.info(
                f"Audio Volume stats: Mean={mean_db:.1f} dB, Max={max_db:.1f} dB, "
                f"Std={std_db:.1f} dB, Threshold={threshold_db:.1f} dB"
            )

            candidates: List[HighlightCandidate] = []
            chosen_times: List[float] = []

            sorted_indices = np.argsort(db_arr)[::-1]
            for idx in sorted_indices:
                if db_arr[idx] < threshold_db or db_arr[idx] < -18.0:
                    break

                peak_time = time_offsets[idx]
                if any(abs(peak_time - ct) < 60 for ct in chosen_times):
                    continue

                chosen_times.append(peak_time)

                start_time = max(0.0, peak_time - 32.0)
                end_time = start_time + self.target_duration

                if is_clip_processed(video_id, start_time, end_time):
                    continue

                volume_jump = db_arr[idx] - mean_db
                score = min(100.0, float(50.0 + (volume_jump * 2.5)))

                candidates.append(
                    HighlightCandidate(
                        video_id=video_id,
                        start_time=round(start_time, 2),
                        end_time=round(end_time, 2),
                        duration=round(end_time - start_time, 2),
                        score=round(score, 1),
                        spike_type="audio_rms",
                        peak_timestamp=round(peak_time, 2),
                        keywords_found=["[Loud Scream/Reaction]"],
                        reason=(
                            f"Decibel spike of {db_arr[idx]:.1f} dB ({volume_jump:+.1f} dB above baseline) "
                            f"at {peak_time:.1f}s"
                        ),
                    )
                )

                if len(candidates) >= 5:
                    break

            logger.info(f"Identified {len(candidates)} audio decibel spike candidates.")
            return candidates

        except Exception as e:
            logger.error(f"Error during audio RMS calculation: {e}")
            return []

    def get_stream_duration(self, video_url: str) -> float:
        """Retrieves total duration of the stream/VOD in seconds via yt-dlp."""
        cmd = ["yt-dlp", "--dump-json", "--skip-download", video_url]
        try:
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
            if res.returncode == 0 and res.stdout.strip():
                info = json.loads(res.stdout.strip().split("\n")[0])
                return float(info.get("duration", 0.0) or 0.0)
        except Exception:
            pass
        return 0.0

    def find_best_highlights(self, video_url: str, video_id: str) -> List[HighlightCandidate]:
        """
        Master detection pipeline:
        1. Tries chat velocity spike detection first (highest correlation with humor/clutch).
        2. If chat unavailable or few candidates, downloads recent audio and computes RMS decibel spikes.
        3. Returns combined, de-duplicated candidate windows sorted by virality score.
        """
        all_candidates: List[HighlightCandidate] = []

        # 1. Attempt chat velocity detection
        chat_path = self.download_live_chat(video_url, video_id)
        if chat_path:
            chat_candidates = self.analyze_chat_velocity(chat_path, video_id)
            all_candidates.extend(chat_candidates)

        # 2. If chat yielded fewer than 2 candidates, run audio decibel spike detection
        if len(all_candidates) < 2:
            logger.info("Chat replay yielded few candidates. Initiating audio decibel spike scan...")
            total_duration = self.get_stream_duration(video_url)

            # Analyze the most recent 25-35 minutes if it's a long stream/VOD
            if total_duration > 1800:
                scan_start = max(0.0, total_duration - 1800.0)
                scan_duration = 1800.0
            else:
                scan_start = 0.0
                scan_duration = min(total_duration, 1800.0) if total_duration > 0 else 900.0

            audio_path = self.download_audio_segment(
                video_url, video_id, start_sec=scan_start, duration_sec=scan_duration
            )
            if audio_path:
                audio_candidates = self.analyze_audio_decibels(
                    audio_path, video_id, offset_seconds=scan_start
                )
                all_candidates.extend(audio_candidates)

        # 3. Fallback: If both fail (e.g. stream just started), create a high-probability recent window
        if not all_candidates:
            logger.warning("No spikes detected via chat or audio. Synthesizing recent stream window fallback.")
            total_duration = self.get_stream_duration(video_url)
            climax_time = max(30.0, total_duration - 90.0) if total_duration > 120 else 30.0
            start_time = max(0.0, climax_time - 25.0)
            end_time = start_time + self.target_duration

            all_candidates.append(
                HighlightCandidate(
                    video_id=video_id,
                    start_time=round(start_time, 2),
                    end_time=round(end_time, 2),
                    duration=round(end_time - start_time, 2),
                    score=65.0,
                    spike_type="fallback",
                    peak_timestamp=round(climax_time, 2),
                    keywords_found=["GTA 6 Action"],
                    reason="Recent stream climax fallback window.",
                )
            )

        # Sort candidates by virality score descending
        all_candidates.sort(key=lambda c: c.score, reverse=True)

        logger.info(f"Highlight detection complete: {len(all_candidates)} candidate windows generated.")
        for idx, c in enumerate(all_candidates[:3], 1):
            logger.info(f" Candidate #{idx} [{c.spike_type} | Score: {c.score}]: {c.start_time}s - {c.end_time}s ({c.reason})")

        return all_candidates


if __name__ == "__main__":
    analyzer = HighlightAnalyzer()
    print("[Analyzer Self-Test] Highlight Analyzer initialized successfully.")
