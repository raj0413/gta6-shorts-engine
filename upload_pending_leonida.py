"""
Helper script to upload the 2 pending pre-rendered shorts for LEONIDA 6 once the YouTube rolling limit resets.
"""
from pathlib import Path
from uploader import YouTubeUploader

PENDING = [
    {
        "video": "output/short_LEONIDA_6_CarryisLive_irNhWMG560k_5183.mp4",
        "title": "CARRYMINATI'S EMOTIONAL GTA 6 MOMENT 😭🔥",
        "streamer": "CarryisLive",
        "publish_at": "2026-11-19T14:00:00Z",  # 07:30 PM IST
        "slot": "07:30 PM IST"
    },
    {
        "video": "output/short_LEONIDA_6_CarryisLive_irNhWMG560k_7487.mp4",
        "title": "CARRYMINATI'S GTA 6 MELTDOWN! 💀😭",
        "streamer": "CarryisLive",
        "publish_at": "2026-11-19T16:00:00Z",  # 09:30 PM IST
        "slot": "09:30 PM IST"
    }
]

def upload_pending():
    uploader = YouTubeUploader(channel_name="LEONIDA 6")
    for item in PENDING:
        p = Path(item["video"])
        if not p.exists():
            print(f"⚠️ Video file not found: {p}")
            continue
        print(f"\n=======================================================")
        print(f"🚀 Uploading for Slot: {item['slot']} ({item['publish_at']})")
        print(f"   Video: {p.name} ({p.stat().st_size / (1024*1024):.2f} MB)")
        print(f"   Title: {item['title']}")
        print(f"=======================================================")
        
        res = uploader.upload_short(
            video_path=p,
            title=item["title"],
            streamer_name=item["streamer"],
            streamer_handle="@CarryisLive",
            stream_url="https://www.youtube.com/watch?v=irNhWMG560k",
            description=f"{item['title']}\n\nCarryMinati plays GTA 6 live gameplay highlights!\nCredit: @CarryisLive\n\n#GTA6 #CarryMinati #Shorts #Gaming #GTA6Gameplay",
            tags=["GTA6", "CarryMinati", "Shorts", "GTA 6 Gameplay", "CarryisLive", "GTA VI"],
            publish_at=item["publish_at"],
        )
        if res.success:
            print(f"✅ SUCCESS! Video ID: {res.video_id} -> {res.short_url}")
        else:
            print(f"❌ Failed: {res.error}")

if __name__ == "__main__":
    upload_pending()
