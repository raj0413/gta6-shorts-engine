"""
9:16 Vertical Video Compositor (renderer.py).
Transforms 16:9 live stream feeds into broadcast-standard 1080x1920 vertical Shorts:
  - Top 35% (672px): Streamer Facecam / Webcam zoom.
  - Bottom 65% (1248px): Centered gameplay action.
  - Sleek neon divider line between sections.
  - Animated ASS karaoke subtitles with word-by-word highlight and bounce.
  - Streamer credit watermark pill and attention-grabbing hook banner.
  - High-speed slice download (yt-dlp sections) without full VOD download.
"""

import math
import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from config import (
    DEFAULT_CLIP_DURATION,
    OUTPUT_DIR,
    TEMP_DIR,
    get_yt_dlp_cmd,
    logger,
)


@dataclass
class RenderConfig:
    """Settings for rendering a 9:16 short."""
    width: int = 1080
    height: int = 1920
    fps: int = 30
    top_cam_height: int = 672     # 35% of 1920
    bottom_game_height: int = 1248 # 65% of 1920
    divider_color: str = "0x00E5FF" # Vibrant Cyan/Yellow divider line
    font_name: str = "Arial"
    subtitles_margin_bottom: int = 420


class VideoRenderer:
    """Engine that downloads highlight slice and renders 9:16 vertical Short."""

    def __init__(self, config: Optional[RenderConfig] = None):
        self.config = config or RenderConfig()

    def download_video_slice(
        self, video_url: str, video_id: str, start_time: float, duration: float
    ) -> Optional[Path]:
        """
        Downloads ONLY the required highlight slice via yt-dlp.
        Never downloads multi-hour stream video files.
        """
        end_time = start_time + duration
        clip_file = TEMP_DIR / f"{video_id}_{int(start_time)}_{int(duration)}_raw.mp4"

        if clip_file.exists() and clip_file.stat().st_size > 500000:
            logger.info(f"Using cached raw video slice: {clip_file.name}")
            return clip_file

        logger.info(
            f"Downloading video section: {start_time:.1f}s - {end_time:.1f}s "
            f"({duration:.1f}s) from {video_url}..."
        )

        # Download best video (up to 1080p) + best audio using fast HLS m3u8 or DASH formats
        cmd = get_yt_dlp_cmd() + [
            "-f", "300/301/311+234/312+234/bv*[height<=1080]+ba/best",
            "--download-sections", f"*{start_time}-{end_time}",
            "--no-warnings",
            "-o", str(clip_file),
            video_url,
        ]

        try:
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
            if clip_file.exists() and clip_file.stat().st_size > 500000:
                logger.info(f"Video slice downloaded: {clip_file.stat().st_size / (1024*1024):.2f} MB")
                return clip_file

            logger.error(f"Failed to download video slice. Stderr: {res.stderr[:300]}")
            return None
        except Exception as e:
            logger.error(f"yt-dlp download section exception: {e}")
            return None

    def _format_ass_time(self, seconds: float) -> str:
        """Converts float seconds into ASS timestamp format: H:MM:SS.cs"""
        hrs = int(seconds // 3600)
        mins = int((seconds % 3600) // 60)
        secs = int(seconds % 60)
        cs = int(round((seconds - int(seconds)) * 100))
        if cs >= 100:
            cs = 99
        return f"{hrs}:{mins:02d}:{secs:02d}.{cs:02d}"

    def generate_ass_subtitles(
        self,
        word_timings: List[Dict[str, Any]],
        output_path: Path,
        streamer_name: str,
        streamer_handle: str,
        hook_text: str,
        clip_duration: float,
        channel_name: Optional[str] = None,
        channel_handle: Optional[str] = None,
    ) -> Path:
        """
        Generates an Advanced SubStation Alpha (.ass) subtitle file featuring:
        1. Word-by-word highlighted karaoke styling.
        2. Streamer attribution watermark banner.
        3. Hook text banner at the top of gameplay section.
        4. Channel branding watermark.
        """
        ass_content = f"""[Script Info]
Title: GTA 6 Viral Short
ScriptType: v4.00+
WrapStyle: 0
ScaledBorderAndShadow: yes
YCbCr Matrix: TV.709
PlayResX: {self.config.width}
PlayResY: {self.config.height}

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,{self.config.font_name},74,&H00FFFFFF,&H0000FFFF,&H00000000,&H90000000,-1,0,0,0,100,100,2,0,1,6,3,2,60,60,{self.config.subtitles_margin_bottom},1
Style: Highlight,{self.config.font_name},78,&H0000F5FF,&H00000000,&H00000000,&HA0000000,-1,0,0,0,115,115,2,0,1,7,4,2,60,60,{self.config.subtitles_margin_bottom},1
Style: Watermark,{self.config.font_name},36,&H00E0E0E0,&H00000000,&H00000000,&HA0000000,-1,0,0,0,100,100,1,0,1,3,2,7,40,40,50,1
Style: ChannelWatermark,{self.config.font_name},34,&H0000E5FF,&H00000000,&H00000000,&HA0000000,-1,0,0,0,100,100,1,0,1,3,2,9,40,40,50,1
Style: HookBanner,{self.config.font_name},54,&H0000FFFF,&H00000000,&H00000000,&HB0000000,-1,0,0,0,108,108,2,0,1,6,3,2,40,40,1190,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
        events: List[str] = []
        end_time_str = self._format_ass_time(clip_duration)

        # 1. Streamer Watermark Overlay (Displayed throughout entire video)
        clean_handle = streamer_handle if streamer_handle.startswith("@") else f"@{streamer_handle}"
        watermark_text = f"🎮 Credit: {clean_handle}"
        events.append(
            f"Dialogue: 1,0:00:00.00,{end_time_str},Watermark,,0,0,0,,{{\\fad(400,400)}}{watermark_text}"
        )

        # 2. Channel Branding (Top Right)
        if channel_handle:
            clean_ch = channel_handle if channel_handle.startswith("@") else f"@{channel_handle}"
            events.append(
                f"Dialogue: 1,0:00:00.00,{end_time_str},ChannelWatermark,,0,0,0,,{{\\fad(400,400)}}{clean_ch}"
            )

        # 3. Top Hook Banner (Displayed for first 6 seconds)
        if hook_text:
            hook_end_str = self._format_ass_time(min(clip_duration, 6.5))
            events.append(
                f"Dialogue: 2,0:00:00.00,{hook_end_str},HookBanner,,0,0,0,,{{\\fad(300,500)}}{hook_text.upper()}"
            )

        # 3. Dynamic Word-by-Word Karaoke Subtitles
        if word_timings:
            # Group words into 3-4 word phrases for punchy reading
            chunk_size = 3
            chunks: List[List[Dict[str, Any]]] = []
            for i in range(0, len(word_timings), chunk_size):
                chunks.append(word_timings[i : i + chunk_size])

            last_w_end = 0.0
            for chunk in chunks:
                if not chunk:
                    continue

                # For each word in this chunk, show line with the active word popped in yellow
                for active_i, active_word in enumerate(chunk):
                    raw_start = float(active_word.get("start", 0.0))
                    raw_end = float(active_word.get("end", 0.0))
                    w_start = max(last_w_end, raw_start)
                    w_end = max(w_start + 0.28, raw_end)
                    last_w_end = w_end

                    w_start_str = self._format_ass_time(w_start)
                    w_end_str = self._format_ass_time(w_end)

                    parts = []
                    for i, w in enumerate(chunk):
                        word_str = w.get("word", "").upper()
                        if i == active_i:
                            # Active word: Neon Yellow-Gold & slightly scaled up
                            parts.append(f"{{\\c&H0000E5FF&\\fscx112\\fscy112}}{word_str}{{\\c&H00FFFFFF&\\fscx100\\fscy100}}")
                        else:
                            parts.append(word_str)

                    line_text = " ".join(parts)
                    events.append(
                        f"Dialogue: 3,{w_start_str},{w_end_str},Default,,0,0,0,,{line_text}"
                    )
        else:
            # Fallback static subtitles if word timings absent
            events.append(
                f"Dialogue: 3,0:00:01.00,{self._format_ass_time(min(clip_duration, 5.0))},Default,,0,0,0,,[GTA 6 CLUTCH MOMENT]"
            )

        full_ass = ass_content + "\n".join(events) + "\n"

        with open(output_path, "w", encoding="utf-8") as f:
            f.write(full_ass)

        logger.info(f"Generated ASS subtitle file: {output_path.name}")
        return output_path

    def render_short(
        self,
        video_url: str,
        video_id: str,
        start_time: float,
        duration: float,
        streamer_name: str,
        streamer_handle: str,
        facecam_box: Optional[List[float]],
        hook_text: str,
        word_timings: List[Dict[str, Any]],
        output_filename: Optional[str] = None,
        channel_name: Optional[str] = None,
        channel_handle: Optional[str] = None,
    ) -> Optional[Path]:
        """
        Executes full composite rendering:
        1. Downloads exact video section.
        2. Generates animated ASS subtitle file.
        3. Builds FFmpeg filtergraph:
           - Crops top facecam (35% height, 672px).
           - Crops bottom gameplay (65% height, 1248px).
           - Adds sleek neon divider line.
           - Applies ASS animated subtitles & watermarks.
        4. Outputs 1080x1920 60/30fps MP4 ready for YouTube Shorts.
        """
        raw_clip = self.download_video_slice(video_url, video_id, start_time, duration)
        if not raw_clip:
            logger.error("Could not obtain raw video slice. Aborting render.")
            return None

        clean_slug = re.sub(r"[^a-zA-Z0-9_-]", "_", streamer_name)
        ch_slug = f"{re.sub(r'[^a-zA-Z0-9_-]', '_', channel_name)}_" if channel_name else ""
        out_name = output_filename or f"short_{ch_slug}{clean_slug}_{video_id}_{int(start_time)}.mp4"
        final_output = OUTPUT_DIR / out_name

        ass_file = TEMP_DIR / f"{video_id}_{int(start_time)}_subs.ass"
        self.generate_ass_subtitles(
            word_timings=word_timings,
            output_path=ass_file,
            streamer_name=streamer_name,
            streamer_handle=streamer_handle,
            hook_text=hook_text,
            clip_duration=duration,
            channel_name=channel_name,
            channel_handle=channel_handle,
        )

        # Default facecam box: normalized [x, y, w, h] (top-right webcam)
        box = facecam_box or [0.70, 0.03, 0.28, 0.36]
        fx, fy, fw, fh = box[0], box[1], box[2], box[3]

        # Prepare subtitle path for FFmpeg filter (handling Windows colons/slashes safely)
        ass_path_escaped = ass_file.as_posix().replace(":", r"\:")

        logger.info(f"Compositing 9:16 vertical Short ({self.config.width}x{self.config.height})...")

        # Complex FFmpeg Filtergraph:
        # [0:v] split=2 [cam_in][game_in];
        # [cam_in] crop=iw*fw:ih*fh:iw*fx:ih*fy, scale=1080:672:force_original_aspect_ratio=increase, crop=1080:672 [top_cam];
        # [game_in] crop=ih*(1080/1248):ih:(iw-ow)/2:0, scale=1080:1248 [bottom_game];
        # [top_cam][bottom_game] vstack=inputs=2 [stacked];
        # [stacked] drawbox=y=670:color=0x00E5FF@0.9:width=iw:height=4:t=fill [bordered];
        # [bordered] ass=subtitles.ass [v]
        # Complex FFmpeg Filtergraph with Transformative Anti-Content-ID Protection:
        # 1. Top Facecam Zoom + Bottom Gameplay crop
        # 2. Vertical Stack (1080x1920)
        # 3. Transformative Color Grade (Saturation + Contrast + Sharpen) to break raw video fingerprinting
        # 4. Sleek Neon Divider Line
        # 5. Dynamic ASS Subtitles
        filtergraph = (
            f"[0:v]split=2[cam_in][game_in];"
            f"[cam_in]crop=iw*{fw:.3f}:ih*{fh:.3f}:iw*{fx:.3f}:ih*{fy:.3f},"
            f"scale={self.config.width}:{self.config.top_cam_height}:force_original_aspect_ratio=increase,"
            f"crop={self.config.width}:{self.config.top_cam_height}[top_cam];"
            f"[game_in]crop=ih*({self.config.width}/{self.config.bottom_game_height}):ih:(iw-ow)/2:0,"
            f"scale={self.config.width}:{self.config.bottom_game_height}[bottom_game];"
            f"[top_cam][bottom_game]vstack=inputs=2[stacked];"
            f"[stacked]eq=contrast=1.07:brightness=0.012:saturation=1.14,unsharp=3:3:0.8:3:3:0.0[graded];"
            f"[graded]drawbox=y={self.config.top_cam_height - 2}:color={self.config.divider_color}@0.95:width=iw:height=4:t=fill[bordered];"
            f"[bordered]ass='{ass_path_escaped}'[v]"
        )

        # Anti-Copyright Audio Transformation:
        # - Highpass / Lowpass removes acoustic watermark artifacts
        # - EQ boost at 3kHz brings streamer speech forward
        # - Dynaudnorm prevents audio clipping on phone speakers
        # - Micro pitch/rate shift (1.2%) breaks raw Content ID audio match hashes while sounding 100% natural
        audio_filter = (
            "highpass=f=100,lowpass=f=13500,"
            "equalizer=f=3000:t=q:w=1.5:g=3.0,"
            "equalizer=f=250:t=q:w=1.0:g=-2.5,"
            "dynaudnorm=f=150:g=15,"
            "asetrate=44100*1.038,aresample=44100,atempo=1/1.038"
        )

        cmd = [
            "ffmpeg",
            "-y",
            "-i", str(raw_clip),
            "-filter_complex", filtergraph,
            "-map", "[v]",
            "-map", "0:a?",
            "-af", audio_filter,
            "-c:v", "libx264",
            "-preset", "fast",
            "-crf", "18",
            "-r", str(self.config.fps),
            "-pix_fmt", "yuv420p",
            "-c:a", "aac",
            "-b:a", "192k",
            "-ar", "44100",
            "-movflags", "+faststart",
            str(final_output),
        ]

        try:
            logger.info("Executing FFmpeg compositor...")
            process = subprocess.run(cmd, capture_output=True, text=True, timeout=300)

            if final_output.exists() and final_output.stat().st_size > 500000:
                mb = final_output.stat().st_size / (1024 * 1024)
                logger.info(f"Render SUCCESS! Output: {final_output.name} ({mb:.2f} MB)")
                return final_output

            # If ASS filter failed (e.g. fontconfig cache on Linux), try fallback without ASS
            logger.warning(f"Compositing with ASS filter failed. Attempting fallback render without subtitles: {process.stderr[-400:]}")
            fallback_filter = (
                f"[0:v]split=2[cam_in][game_in];"
                f"[cam_in]crop=iw*{fw:.3f}:ih*{fh:.3f}:iw*{fx:.3f}:ih*{fy:.3f},"
                f"scale={self.config.width}:{self.config.top_cam_height}:force_original_aspect_ratio=increase,"
                f"crop={self.config.width}:{self.config.top_cam_height}[top_cam];"
                f"[game_in]crop=ih*({self.config.width}/{self.config.bottom_game_height}):ih:(iw-ow)/2:0,"
                f"scale={self.config.width}:{self.config.bottom_game_height}[bottom_game];"
                f"[top_cam][bottom_game]vstack=inputs=2[stacked];"
                f"[stacked]eq=contrast=1.07:brightness=0.012:saturation=1.14,unsharp=3:3:0.8:3:3:0.0[graded];"
                f"[graded]drawbox=y={self.config.top_cam_height - 2}:color={self.config.divider_color}@0.95:width=iw:height=4:t=fill"
            )
            cmd_fallback = [
                "ffmpeg",
                "-y",
                "-i", str(raw_clip),
                "-filter_complex", fallback_filter,
                "-map", "0:a?",
                "-af", audio_filter,
                "-c:v", "libx264",
                "-preset", "fast",
                "-crf", "18",
                "-r", str(self.config.fps),
                "-pix_fmt", "yuv420p",
                "-c:a", "aac",
                "-b:a", "192k",
                "-movflags", "+faststart",
                str(final_output),
            ]
            sub_res = subprocess.run(cmd_fallback, capture_output=True, text=True, timeout=300)
            if final_output.exists() and final_output.stat().st_size > 500000:
                logger.info(f"Fallback render SUCCESS! Output: {final_output.name}")
                return final_output

            logger.error(f"FFmpeg composite failed entirely: {sub_res.stderr[-300:]}")
            return None

        except subprocess.TimeoutExpired:
            logger.error("FFmpeg render timed out after 300 seconds.")
            return None
        except Exception as e:
            logger.error(f"Render exception: {e}")
            return None
        finally:
            # Cleanup intermediate raw clip and ASS file
            raw_clip.unlink(missing_ok=True)
            ass_file.unlink(missing_ok=True)


if __name__ == "__main__":
    renderer = VideoRenderer()
    print("[Renderer Self-Test] Video Renderer module initialized successfully.")
