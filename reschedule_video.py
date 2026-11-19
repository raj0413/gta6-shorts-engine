import sys
from uploader import YouTubeUploader

def reschedule(channel_name, video_id, new_publish_at):
    u = YouTubeUploader(channel_name=channel_name)
    svc = u._get_authenticated_service()
    
    # Get current video snippet and status
    res = svc.videos().list(part="snippet,status", id=video_id).execute()
    if not res.get("items"):
        print(f"Video {video_id} not found on {channel_name}")
        return False
        
    item = res["items"][0]
    status = item["status"]
    status["privacyStatus"] = "private"
    status["publishAt"] = new_publish_at
    
    body = {
        "id": video_id,
        "snippet": item["snippet"],
        "status": status,
    }
    
    updated = svc.videos().update(part="snippet,status", body=body).execute()
    print(f"✅ Video {video_id} rescheduled on {channel_name} to: {updated['status'].get('publishAt')}")
    return True

if __name__ == "__main__":
    if len(sys.argv) >= 4:
        reschedule(sys.argv[1], sys.argv[2], sys.argv[3])
