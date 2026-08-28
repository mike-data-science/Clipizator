import os
import sys
import time
import json
import argparse
import requests
from pathlib import Path

# Add pipeline to sys.path so we can use its ytdlp tools
sys.path.insert(0, str(Path(__file__).resolve().parent / "pipeline"))

from publikclip_pipeline.ingest import ytdlp

DEFAULT_VM_URL = os.environ.get("PUBLIKCLIP_SERVER_URL", "http://4.231.114.220:8000").rstrip("/")

def get_jobs(server_url):
    try:
        resp = requests.get(f"{server_url}/api/worker/jobs", timeout=5)
        if resp.status_code == 200:
            return resp.json().get("jobs", [])
        print(f"Worker queue returned HTTP {resp.status_code}: {resp.text[:200]}")
    except Exception as e:
        print(f"Worker cannot reach {server_url}: {e}")
    return []

def download_and_upload(job, server_url):
    campaign_id = job["campaign_id"]
    clip_id = job["clip_id"]
    url = job["url"]
    role = job.get("role", "competitor")
    
    print(f"\n--- Processing Job: {clip_id} for campaign {campaign_id} ---")
    print(f"URL: {url}")
    
    video_path = Path(f"temp_{clip_id}.mp4")
    meta_path = Path(f"temp_{clip_id}.json")
    
    try:
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
        with open(video_path, "rb") as vf, open(meta_path, "rb") as mf:
            files = {
                "video": ("video.mp4", vf, "video/mp4"),
                "metadata": ("meta.json", mf, "application/json")
            }
            data = {"role": role}
            
            resp = requests.post(f"{server_url}/api/worker/upload/{campaign_id}/{clip_id}", files=files, data=data)
            
            if resp.status_code == 200:
                print("Successfully uploaded to VM! VM has resumed analysis.")
            else:
                print(f"Upload failed: {resp.text}")
                
    except Exception as e:
        print(f"Error processing job: {e}")
        
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
    parser.add_argument("--once", action="store_true", help="Poll once and exit")
    args = parser.parse_args()
    print(f"Starting Laptop Worker. Polling {args.server_url} for new downloads...")
    while True:
        jobs = get_jobs(args.server_url)
        if jobs:
            for job in jobs:
                download_and_upload(job, args.server_url)
        elif args.once:
            print("No queued worker jobs.")
            return
        if args.once:
            return
        time.sleep(5)

if __name__ == "__main__":
    main()
