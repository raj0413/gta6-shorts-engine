import sys
from pathlib import Path
from curator import ViralCurator
from renderer import VideoRenderer
from uploader import YouTubeUploader
from config import logger, record_clip_in_history

def process_moment(video_url, video_id, start_time, duration, streamer_name, streamer_handle, channel_name, publish_at):
    print(f"=== Processing Moment {start_time}s - {start_time+duration}s for {channel_name} ===")
    
    curator = ViralCurator()
    curation = curator.curate_candidate(
        video_url=video_url,
        video_id=video_id,
        streamer_name=streamer_name,
        stream_title="CARRYMINATI PLAYS GTA VI | NO PROMOTIONS",
        start_time=start_time,
        duration=duration,
        keywords=["[Loud Scream/Reaction]"],
        spike_type="audio_rms",
        language="hi",
    )
    
    if not curation or not curation.approved:
        print(f"Moment rejected by AI or curation failed: {curation.reason if curation else 'None'}")
        return False
        
    print(f"Approved by Gemini! Score: {curation.viral_score}/10, Title: {curation.short_title}")
    
    # Render Short
    renderer = VideoRenderer()
    uploader = YouTubeUploader(channel_name=channel_name)
    ch_handle = uploader.channel.get("handle")
    
    rendered_path = renderer.render_short(
        video_url=video_url,
        video_id=video_id,
        start_time=start_time,
        duration=duration,
        streamer_name=streamer_name,
        streamer_handle=streamer_handle,
        facecam_box=[0.005, 0.335, 0.20, 0.245],
        hook_text=curation.hook_text,
        word_timings=curation.word_timestamps,
        channel_name=channel_name,
        channel_handle=ch_handle,
    )
    
    if not rendered_path or not rendered_path.exists():
        print("Render failed!")
        return False
        
    print(f"Rendered successfully: {rendered_path.name} ({rendered_path.stat().st_size / (1024*1024):.2f} MB)")
    
    # Upload and schedule
    print(f"Uploading to {channel_name} scheduled for {publish_at}...")
    res = uploader.upload_short(
        video_path=rendered_path,
        title=curation.short_title,
        streamer_name=streamer_name,
        streamer_handle=streamer_handle,
        stream_url=video_url,
        description=curation.description,
        tags=curation.tags,
        publish_at=publish_at,
    )
    
    if res.success:
        print(f"✅ Upload SUCCESS! Video ID: {res.video_id}, URL: {res.short_url}")
        record_clip_in_history(
            video_id=video_id,
            streamer_name=streamer_name,
            stream_title="CARRYMINATI PLAYS GTA VI | NO PROMOTIONS",
            clip_start=start_time,
            clip_end=start_time + duration,
            short_title=curation.short_title,
            short_id=f"{channel_name}:{res.video_id}",
            viral_score=curation.viral_score,
        )
        return True
    else:
        print(f"❌ Upload failed: {res.error}")
        return False

if __name__ == "__main__":
    v_url = sys.argv[1]
    v_id = sys.argv[2]
    start = float(sys.argv[3])
    dur = float(sys.argv[4])
    s_name = sys.argv[5]
    s_handle = sys.argv[6]
    c_name = sys.argv[7]
    pub = sys.argv[8]
    
    process_moment(v_url, v_id, start, dur, s_name, s_handle, c_name, pub)
