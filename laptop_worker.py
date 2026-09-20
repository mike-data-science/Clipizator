import os
import sys
import time
import json
import argparse
import uuid
import requests
from pathlib import Path

for _proxy_name in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy", "PUBLIKCLIP_YTDLP_PROXY"):
    os.environ.pop(_proxy_name, None)

# Add pipeline to sys.path so we can use its ytdlp tools
sys.path.insert(0, str(Path(__file__).resolve().parent / "pipeline"))

from publikclip_pipeline.ingest import ytdlp

DEFAULT_VM_URL = os.environ.get("PUBLIKCLIP_SERVER_URL", "http://4.231.114.220:8000").rstrip("/")

WORKER_ID = f"laptop-{uuid.uuid4().hex[:12]}"


def get_jobs(server_url):
    try:
        resp = requests.get(f"{server_url}/api/worker/jobs", params={"worker_id": WORKER_ID}, timeout=5)
        if resp.status_code == 200:
            return resp.json().get("jobs", [])
        print(f"Worker queue returned HTTP {resp.status_code}: {resp.text[:200]}")
    except Exception as e:
        print(f"Worker cannot reach {server_url}: {e}")
    return []


def report_research_status(job, server_url, status, error=None):
    queue_item_id = job.get("queue_item_id")
    claim_token = job.get("claim_token")
    if not queue_item_id or not claim_token:
        return
    try:
        response = requests.post(
            f"{server_url}/api/worker/research/{queue_item_id}/status",
            json={"claim_token": claim_token, "status": status, "error": error},
            timeout=10,
        )
        if response.status_code != 200:
            print(f"Could not report research status {status}: {response.text[:200]}")
    except Exception as status_error:
        print(f"Could not report research status {status}: {status_error}")

def download_and_upload(job, server_url):
    job_type = job.get("type", "clip")
    campaign_id = job.get("campaign_id")
    clip_id = job.get("clip_id")
    job_id = job.get("job_id")
    url = job["url"]
    role = job.get("role", "competitor")
    queue_item_id = job.get("queue_item_id")
    item_id = queue_item_id or clip_id or job_id
    
    print(f"\n--- Processing {job_type}: {item_id} for campaign {campaign_id} ---")
    print(f"URL: {url}")
    
    video_path = Path(f"temp_{item_id}.mkv")
    meta_path = Path(f"temp_{item_id}.json")
    
    try:
        if job_type == "research_queue":
            report_research_status(job, server_url, "downloading")
        # 1. Fetch Meta
        print("Fetching metadata...")
        meta = ytdlp.fetch_meta(url, lambda pct, msg: print(f"  {msg}", end="\r"))
        
        # Save meta to JSON
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(meta.raw, f)
            
        # 2. Download Video
        print("\nDownloading video...")
        ytdlp.download(url, video_path, lambda pct, msg: print(f"  [{pct*100:.1f}%] {msg}", end="\r"))
        print("\nDownload complete.")
        
        # 3. Upload to VM
        print("Uploading to Azure VM...")
        if job_type == "research_queue":
            report_research_status(job, server_url, "uploading")
        with open(video_path, "rb") as vf, open(meta_path, "rb") as mf:
            files = {
                "video": ("video.mkv", vf, "video/x-matroska"),
                "metadata": ("meta.json", mf, "application/json")
            }
            data = {"role": role}
            if job_type == "research_queue":
                data["claim_token"] = job["claim_token"]
            if job_type == "source" and job.get("resume_pipeline"):
                data["resume_pipeline"] = "true"
            
            upload_url = (
                f"{server_url}/api/worker/upload-research/{queue_item_id}"
                if job_type == "research_queue"
                else f"{server_url}/api/worker/upload-source/{job_id}"
                if job_type == "source"
                else f"{server_url}/api/worker/upload/{campaign_id}/{clip_id}"
            )
            resp = requests.post(upload_url, files=files, data=data)
            
            if resp.status_code == 200:
                print("Successfully uploaded to VM! VM has resumed analysis.")
            else:
                print(f"Upload failed: {resp.text}")
                if job_type == "research_queue":
                    report_research_status(job, server_url, "failed", f"Upload failed with HTTP {resp.status_code}: {resp.text[:500]}")
                
    except Exception as e:
        print(f"Error processing job: {e}")
        if job_type == "research_queue":
            report_research_status(job, server_url, "failed", str(e))
        
    finally:
        # 4. Clean up local files to save memory
        if video_path.exists():
            video_path.unlink()
        if meta_path.exists():
            meta_path.unlink()
        print("Cleaned up local files.")

def main():
    parser = argparse.ArgumentParser(description="Download queued campaign clips on this laptop.")
    parser.add_argument("--server-url", default=DEFAULT_VM_URL, help="Backend URL, e.g. http://127.0.0.1:8001")
    parser.add_argument("--cookies-from-browser", choices=("chrome", "edge", "firefox", "brave", "chromium"), help="Read YouTube login cookies from this browser")
    parser.add_argument("--cookies", help="Path to an exported Netscape cookies.txt file")
    parser.add_argument("--once", action="store_true", help="Poll once and exit")
    args = parser.parse_args()
    if args.cookies_from_browser:
        os.environ["PUBLIKCLIP_COOKIES_FROM_BROWSER"] = args.cookies_from_browser
    if args.cookies:
        os.environ["PUBLIKCLIP_COOKIES_FILE"] = args.cookies
    auth_mode = args.cookies_from_browser or args.cookies or "cookies.txt fallback"
    print(f"Starting Laptop Worker. Polling {args.server_url} for new downloads...")
    print(f"yt-dlp authentication: {auth_mode}")
    print("Download quality: 720p+ when available, best audio, merged without transcoding")
    while True:
        jobs = get_jobs(args.server_url)
        if jobs:
            for job in jobs:
                if job.get("type") == "research_queue":
                    required = ("url", "job_id", "queue_item_id", "claim_token")
                elif job.get("type") == "source":
                    required = ("url", "job_id")
                else:
                    required = ("campaign_id", "clip_id", "url")
                missing = [field for field in required if not job.get(field)]
                if missing:
                    print(f"Skipping malformed worker job; missing: {', '.join(missing)}")
                    continue
                download_and_upload(job, args.server_url)
        elif args.once:
            print("No queued worker jobs.")
            return
        if args.once:
            return
        time.sleep(5)

if __name__ == "__main__":
    main()
