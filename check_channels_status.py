import json
from uploader import YouTubeUploader

def check_channel(ch_name):
    print(f"\n=======================================================")
    print(f"👉 CHECKING CHANNEL: {ch_name}")
    print(f"=======================================================")
    u = YouTubeUploader(channel_name=ch_name)
    svc = u._get_authenticated_service()

    # Get uploads playlist
    ch_res = svc.channels().list(part="contentDetails", mine=True).execute()
    uploads_id = ch_res["items"][0]["contentDetails"]["relatedPlaylists"]["uploads"]

    # List videos in uploads playlist
    pl_res = svc.playlistItems().list(part="snippet,contentDetails", playlistId=uploads_id, maxResults=50).execute()
    video_ids = [item["contentDetails"]["videoId"] for item in pl_res.get("items", [])]
    print(f"Total uploaded videos found: {len(video_ids)}")

    if not video_ids:
        return

    vid_res = svc.videos().list(part="snippet,status,contentDetails", id=",".join(video_ids)).execute()
    for v in vid_res.get("items", []):
        vid = v["id"]
        snippet = v["snippet"]
        status = v["status"]
        content = v.get("contentDetails", {})
        title = snippet.get("title")
        pub_at = snippet.get("publishedAt")
        upload_status = status.get("uploadStatus")
        rejection = status.get("rejectionReason")
        privacy = status.get("privacyStatus")
        publish_at = status.get("publishAt")
        
        print(f"\n[Video ID: {vid}] {title}")
        print(f"  Status: uploadStatus={upload_status}, privacyStatus={privacy}")
        if publish_at:
            print(f"  Scheduled: {publish_at}")
        if rejection:
            print(f"  ❌ REJECTION REASON: {rejection}")
        if "regionRestriction" in content:
            print(f"  ⚠️ REGION RESTRICTION: {content['regionRestriction']}")

if __name__ == "__main__":
    for name in ["LEONIDA 6", "VicePulse"]:
        check_channel(name)
