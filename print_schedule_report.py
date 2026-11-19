import datetime
from uploader import YouTubeUploader

target_times = [
    ("10:00 AM IST", "2026-11-19T04:30:00Z"),
    ("12:00 PM IST", "2026-11-19T06:30:00Z"),
    ("01:30 PM IST", "2026-11-19T08:00:00Z"),
    ("04:00 PM IST", "2026-11-19T10:30:00Z"),
    ("05:00 PM IST", "2026-11-19T11:30:00Z"),
    ("06:30 PM IST", "2026-11-19T13:00:00Z"),
    ("07:30 PM IST", "2026-11-19T14:00:00Z"),
    ("08:45 PM IST", "2026-11-19T15:15:00Z"),
    ("09:30 PM IST", "2026-11-19T16:00:00Z"),
]

def generate_report():
    print("=" * 90)
    print("🎬 YOUTUBE SHORTS AUTOMATION - AUDIT & SCHEDULE STATUS REPORT")
    print("=" * 90)

    for ch in ["LEONIDA 6", "VicePulse"]:
        print(f"\n📺 CHANNEL: {ch}")
        print("-" * 90)
        u = YouTubeUploader(channel_name=ch)
        svc = u._get_authenticated_service()
        ch_res = svc.channels().list(part="contentDetails", mine=True).execute()
        uploads_id = ch_res["items"][0]["contentDetails"]["relatedPlaylists"]["uploads"]
        pl_res = svc.playlistItems().list(part="contentDetails", playlistId=uploads_id, maxResults=50).execute()
        vids = [item["contentDetails"]["videoId"] for item in pl_res.get("items", [])]
        if not vids:
            print("No videos found.")
            continue
            
        items = svc.videos().list(part="snippet,status,contentDetails", id=",".join(vids)).execute().get("items", [])
        
        # Map by scheduled time
        scheduled_map = {}
        live_videos = []
        for item in items:
            status = item["status"]
            content = item.get("contentDetails", {})
            pub_at = status.get("publishAt")
            is_restricted = "regionRestriction" in content or status.get("rejectionReason") is not None
            info = {
                "id": item["id"],
                "title": item["snippet"]["title"],
                "status": status.get("uploadStatus"),
                "privacy": status.get("privacyStatus"),
                "restricted": is_restricted,
                "restriction_details": content.get("regionRestriction") or status.get("rejectionReason"),
                "publishAt": pub_at
            }
            if pub_at:
                scheduled_map[pub_at] = info
            else:
                live_videos.append(info)
                
        print(f"{'SLOT (IST)':<15} | {'SCHEDULED TIME (UTC)':<20} | {'STATUS':<10} | {'VIDEO ID':<12} | {'RESTRICTION':<11} | {'TITLE'}")
        print("-" * 90)
        
        for ist_label, utc_time in target_times:
            if utc_time in scheduled_map:
                v = scheduled_map[utc_time]
                res_str = "CLEAN ✅" if not v["restricted"] else f"BLOCKED ❌ ({v['restriction_details']})"
                print(f"{ist_label:<15} | {utc_time:<20} | {v['status']:<10} | {v['id']:<12} | {res_str:<11} | {v['title'][:40]}")
            else:
                print(f"{ist_label:<15} | {utc_time:<20} | {'PENDING':<10} | {'-':<12} | {'-':<11} | [Ready in output folder / Limit reached]")
                
        if live_videos:
            print("\n  📢 Currently Live / Public Videos:")
            for lv in live_videos:
                res_str = "CLEAN ✅" if not lv["restricted"] else f"BLOCKED ❌ ({lv['restriction_details']})"
                print(f"     - [{lv['id']}] {lv['title']} ({lv['privacy']}, {lv['status']}, {res_str})")

if __name__ == "__main__":
    generate_report()
