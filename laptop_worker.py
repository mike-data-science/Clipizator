import os
import sys
import time
import json
import requests
from pathlib import Path

# Add pipeline to sys.path so we can use its ytdlp tools
sys.path.insert(0, str(Path(__file__).resolve().parent / "pipeline"))

from publikclip_pipeline.ingest import ytdlp

VM_URL = "http://4.231.114.220:8000"

def get_jobs():
    try:
        resp = requests.get(f"{VM_URL}/api/worker/jobs", timeout=5)
        if resp.status_code == 200:
            return resp.json().get("jobs", [])
    except Exception as e:
        pass
    return []

def download_and_upload(job):
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
            
            resp = requests.post(f"{VM_URL}/api/worker/upload/{campaign_id}/{clip_id}", files=files, data=data)
            
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
    print(f"Starting Laptop Worker. Polling {VM_URL} for new downloads...")
    while True:
        jobs = get_jobs()
        if jobs:
            for job in jobs:
                download_and_upload(job)
        time.sleep(5)

if __name__ == "__main__":
    main()
