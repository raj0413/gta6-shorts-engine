"""
Master Orchestrator (main.py).
Coordinates the complete autonomous cycle:
  1. Scout (Radar & Live Detection)
  2. Analyze (Chat & Audio Peak Detection)
  3. Curate (Whisper + Gemini 2.0 AI Viral Judge)
  4. Render (9:16 Vertical Video + ASS Karaoke Subtitles)
  5. Upload (Headless YouTube OAuth2 Auto-Publish)
  6. State Persistence (Atomic history.json update)
"""

import argparse
import sys
import time
from pathlib import Path
from typing import List, Optional

from analyzer import HighlightAnalyzer, HighlightCandidate
from config import (
    AUTO_UPLOAD,
    DEFAULT_CLIP_DURATION,
    MAX_SHORTS_PER_RUN,
    MIN_VIEWERS,
    MIN_VIRAL_SCORE,
    OUTPUT_DIR,
    TEMP_DIR,
    is_clip_processed,
    load_streamers,
    logger,
    record_clip_in_history,
)
from curator import CurationResult, ViralCurator
from renderer import RenderConfig, VideoRenderer
from scout import LiveStream, StreamScout
from uploader import UploadResult, YouTubeUploader, get_channel_uploaders


class ShortsEngineOrchestrator:
    """Master controller managing the autonomous Shorts generation pipeline."""

    def __init__(
        self,
        dry_run: bool = False,
        min_viewers: int = MIN_VIEWERS,
        max_shorts: int = MAX_SHORTS_PER_RUN,
        force: bool = False,
        target_channel: Optional[str] = None,
    ):
        self.dry_run = dry_run
        self.min_viewers = min_viewers
        self.max_shorts = max_shorts
        self.force = force
        self.target_channel = target_channel

        # Initialize sub-modules
        self.scout = StreamScout(min_viewers=self.min_viewers)
        self.analyzer = HighlightAnalyzer(target_duration=DEFAULT_CLIP_DURATION)
        self.curator = ViralCurator()
        self.renderer = VideoRenderer()
        self.uploaders = get_channel_uploaders(target_channel=self.target_channel)

    def process_stream(self, stream: LiveStream) -> int:
        """
        Executes pipeline for an active live stream:
        Detects highlight peaks -> Curates with Gemini -> Renders -> Publishes -> Logs.
        Returns number of shorts successfully generated and published.
        """
        logger.info("=" * 60)
        logger.info(f"PROCESSING STREAM: {stream.streamer_name} ({stream.concurrent_viewers:,} viewers)")
        logger.info(f"Title: '{stream.title}' | URL: {stream.url}")
        logger.info("=" * 60)

        # 1. Analyze highlights (Chat velocity + Audio RMS spikes)
        candidates = self.analyzer.find_best_highlights(
            video_url=stream.url, video_id=stream.video_id
        )

        if not candidates:
            logger.info(f"No candidate highlights found for '{stream.streamer_name}'. Moving to next stream.")
            return 0

        shorts_produced = 0

        # 2. Iterate candidates until approved by Gemini AI
        for idx, candidate in enumerate(candidates, 1):
            if shorts_produced >= self.max_shorts:
                logger.info(f"Reached max shorts limit per run ({self.max_shorts}). Halting stream processing.")
                break

            logger.info(
                f"\n--- Evaluating Candidate #{idx}/{len(candidates)} "
                f"[{candidate.start_time:.1f}s - {candidate.end_time:.1f}s] ---"
            )

            # Check history to prevent duplicate clips
            if not self.force and is_clip_processed(
                stream.video_id, candidate.start_time, candidate.end_time
            ):
                logger.info(f"Moment {candidate.start_time:.1f}s - {candidate.end_time:.1f}s already clipped in history. Skipping.")
                continue

            # 3. Curate with Gemini 2.0 AI & Whisper
            curation: CurationResult = self.curator.curate_candidate(
                video_url=stream.url,
                video_id=stream.video_id,
                streamer_name=stream.streamer_name,
                stream_title=stream.title,
                start_time=candidate.start_time,
                duration=candidate.duration,
                keywords=candidate.keywords_found,
                spike_type=candidate.spike_type,
                language=stream.language,
            )

            if not curation.approved and not self.force:
                logger.info(f"Candidate #{idx} rejected by AI curator (Score: {curation.viral_score}/10). Trying next...")
                continue

            # 4. Render 9:16 Vertical Short with facecam and animated subtitles
            primary_uploader = self.uploaders[0] if self.uploaders else None
            ch_name = primary_uploader.channel_name if primary_uploader else None
            ch_handle = primary_uploader.channel.get("handle") if primary_uploader else None

            logger.info(f"Rendering 9:16 vertical Short: '{curation.short_title}' (Channel: {ch_name or 'General'})...")
            rendered_video = self.renderer.render_short(
                video_url=stream.url,
                video_id=stream.video_id,
                start_time=candidate.start_time,
                duration=candidate.duration,
                streamer_name=stream.streamer_name,
                streamer_handle=stream.streamer_handle,
                facecam_box=stream.facecam_box,
                hook_text=curation.hook_text,
                word_timings=curation.word_timestamps,
                channel_name=ch_name,
                channel_handle=ch_handle,
            )

            if not rendered_video or not rendered_video.exists():
                logger.error(f"Render failed for candidate #{idx}.")
                continue

            # 5. Upload to YouTube (or Dry Run)
            uploaded_ids: List[str] = []
            if self.dry_run or not AUTO_UPLOAD:
                for up in self.uploaders:
                    logger.info(f"[DRY-RUN] Short rendered at: {rendered_video.absolute()} (Upload bypassed for '{up.channel_name}').")
                uploaded_ids.append("DRY_RUN_SAVED")
            else:
                for up in self.uploaders:
                    upload_res: UploadResult = up.upload_short(
                        video_path=rendered_video,
                        title=curation.short_title,
                        streamer_name=stream.streamer_name,
                        streamer_handle=stream.streamer_handle,
                        stream_url=stream.url,
                        description=curation.description,
                        tags=curation.tags,
                    )
                    if upload_res.success:
                        if upload_res.video_id:
                            uploaded_ids.append(f"{up.channel_name}:{upload_res.video_id}")
                        logger.info(f"[{up.channel_name}] Short published: {upload_res.short_url}")
                    else:
                        logger.error(f"[{up.channel_name}] Failed to publish short: {upload_res.error}")

            # 6. Update history.json
            record_clip_in_history(
                video_id=stream.video_id,
                streamer_name=stream.streamer_name,
                stream_title=stream.title,
                clip_start=candidate.start_time,
                clip_end=candidate.end_time,
                short_title=curation.short_title,
                short_id=",".join(uploaded_ids) if uploaded_ids else None,
                viral_score=curation.viral_score,
            )

            shorts_produced += 1
            logger.info(f"Successfully processed Short #{shorts_produced} for {stream.streamer_name}!")

        return shorts_produced

    def run_scout_only(self, target_streamer: Optional[str] = None) -> None:
        """Runs radar scan only and prints discovered streams."""
        logger.info("Running Scout Radar...")
        streams = self.scout.scout_all(target_streamer=target_streamer)
        print("\n" + "=" * 70)
        print(f"GTA 6 STREAM RADAR REPORT ({len(streams)} active streams discovered)")
        print("=" * 70)
        for s in streams:
            print(f"• [{s.streamer_name}] - {s.concurrent_viewers:,} live viewers")
            print(f"  Title: {s.title}")
            print(f"  URL:   {s.url}")
            print(f"  Cam:   {s.facecam_position} {s.facecam_box}\n")

    def run_pipeline(self, target_streamer: Optional[str] = None) -> None:
        """Executes full autonomous run cycle."""
        logger.info("Starting autonomous GTA 6 Shorts Engine run...")
        start_time = time.time()

        # Step 1: Scout
        active_streams = self.scout.scout_all(target_streamer=target_streamer)
        if not active_streams:
            logger.info("Radar check complete: No live GTA 6 streams found meeting criteria. Sleeping.")
            return

        total_shorts = 0
        for stream in active_streams:
            if total_shorts >= self.max_shorts:
                break
            created = self.process_stream(stream)
            total_shorts += created

        elapsed = time.time() - start_time
        logger.info(f"Engine cycle completed in {elapsed:.1f}s. Total Shorts produced: {total_shorts}")

    def clip_custom_url(
        self,
        video_url: str,
        streamer_name: str = "GTA 6 Streamer",
        streamer_handle: str = "@GTA6Clips",
    ) -> None:
        """Clips a specific stream or VOD URL on demand."""
        logger.info(f"Manually clipping custom stream URL: {video_url}")
        details = self.scout.probe_video_details(video_url)

        final_streamer = details.streamer_name if details and details.streamer_name and details.streamer_name != "Streamer" else streamer_name
        final_handle = details.streamer_handle if details and details.streamer_handle and details.streamer_handle != "@Streamer" else streamer_handle

        # Match facecam configuration from streamers.json
        streamers_list = load_streamers()
        matched = next(
            (s for s in streamers_list if s.get("name", "").lower() in final_streamer.lower() or final_streamer.lower() in s.get("name", "").lower()),
            None
        )
        facecam_pos = matched.get("facecam_position", "top-right") if matched else "top-right"
        facecam_box = matched.get("facecam_box", [0.70, 0.03, 0.28, 0.36]) if matched else [0.70, 0.03, 0.28, 0.36]
        stream_lang = matched.get("language", "en") if matched else "en"

        vid = details.video_id if details else None
        if not vid:
            if "watch?v=" in video_url:
                vid = video_url.split("watch?v=")[-1].split("&")[0]
            elif "youtu.be/" in video_url:
                vid = video_url.split("youtu.be/")[-1].split("?")[0]
            else:
                vid = "custom_clip"

        stream = LiveStream(
            video_id=vid,
            streamer_name=final_streamer,
            channel_id=details.channel_id if details else "",
            streamer_handle=final_handle,
            title=details.title if details else "GTA 6 Live Gameplay Highlight",
            url=video_url,
            concurrent_viewers=details.concurrent_viewers if details else 5000,
            facecam_position=facecam_pos,
            facecam_box=facecam_box,
            language=stream_lang,
            is_active_live=False,
        )

        self.process_stream(stream)


def main():
    parser = argparse.ArgumentParser(
        description="Autonomous GTA 6 Live Stream Scout & Auto-Clipping Shorts Engine"
    )
    subparsers = parser.add_subparsers(dest="command", help="Command to execute")

    # Command: run (default)
    run_parser = subparsers.add_parser("run", help="Run full autonomous scout -> clip -> publish cycle")
    run_parser.add_argument("--dry-run", action="store_true", help="Render without publishing to YouTube")
    run_parser.add_argument("--streamer", type=str, help="Target specific streamer from VIP list")
    run_parser.add_argument("--channel", type=str, help="Target specific YouTube channel from channels.json (e.g. VicePulse)")
    run_parser.add_argument("--max-shorts", type=int, default=MAX_SHORTS_PER_RUN, help="Max shorts to produce")
    run_parser.add_argument("--min-viewers", type=int, default=MIN_VIEWERS, help="Minimum live viewers threshold")
    run_parser.add_argument("--force", action="store_true", help="Bypass history deduplication and AI minimum score")

    # Command: scout
    scout_parser = subparsers.add_parser("scout", help="Radar only: scan for active streams")
    scout_parser.add_argument("--streamer", type=str, help="Target specific streamer")

    # Command: clip
    clip_parser = subparsers.add_parser("clip", help="Clip a specific YouTube live stream or VOD URL")
    clip_parser.add_argument("--url", required=True, type=str, help="YouTube video or stream URL")
    clip_parser.add_argument("--channel", type=str, help="Target specific YouTube channel from channels.json (e.g. VicePulse)")
    clip_parser.add_argument("--streamer", type=str, default="Streamer", help="Streamer name")
    clip_parser.add_argument("--handle", type=str, default="@Streamer", help="Streamer YouTube handle")
    clip_parser.add_argument("--max-shorts", type=int, default=MAX_SHORTS_PER_RUN, help="Max shorts to produce")
    clip_parser.add_argument("--dry-run", action="store_true", help="Render without publishing to YouTube")
    clip_parser.add_argument("--force", action="store_true", help="Bypass history check")

    args = parser.parse_args()

    command = args.command or "run"

    if command == "scout":
        engine = ShortsEngineOrchestrator(min_viewers=getattr(args, "min_viewers", MIN_VIEWERS))
        engine.run_scout_only(target_streamer=getattr(args, "streamer", None))

    elif command == "clip":
        engine = ShortsEngineOrchestrator(
            dry_run=args.dry_run,
            force=args.force,
            target_channel=getattr(args, "channel", None),
            max_shorts=getattr(args, "max_shorts", MAX_SHORTS_PER_RUN),
        )
        engine.clip_custom_url(
            video_url=args.url,
            streamer_name=args.streamer,
            streamer_handle=args.handle,
        )

    elif command == "run":
        engine = ShortsEngineOrchestrator(
            dry_run=args.dry_run,
            min_viewers=args.min_viewers,
            max_shorts=args.max_shorts,
            force=args.force,
            target_channel=getattr(args, "channel", None),
        )
        engine.run_pipeline(target_streamer=args.streamer)

    else:
        parser.print_help()


if __name__ == "__main__":
    main()
