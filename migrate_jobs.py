import json
import re
import shutil
from pathlib import Path

from publikclip_pipeline.jobs import queue
from publikclip_pipeline.campaigns import store
from publikclip_pipeline import config

def main():
    print("Starting job migration...")
    jobs_dir = config.jobs_dir()
    
    # 1. Update schema if needed
    with queue._connect() as conn:
        try:
            conn.execute("ALTER TABLE jobs ADD COLUMN campaign_dir TEXT")
            print("Added campaign_dir column to jobs table.")
        except Exception:
            print("Column campaign_dir already exists.")
            
    # 2. Get all jobs that don't have a campaign_dir yet
    with queue._connect() as conn:
        rows = conn.execute("SELECT id, campaign_dir FROM jobs").fetchall()
        
    for row in rows:
        job_id = row["id"]
        current_campaign_dir = row["campaign_dir"]
        
        if current_campaign_dir:
            continue
            
        print(f"Processing job {job_id}...")
        
        # Try to find which campaign this job belongs to
        campaign_dir = "standalone"
        with store._connect() as conn:
            cv = conn.execute("SELECT campaign_id FROM campaign_videos WHERE job_id = ?", (job_id,)).fetchone()
            if cv:
                campaign_id = cv["campaign_id"]
                campaign = store.get_campaign(campaign_id)
                if campaign:
                    safe_name = re.sub(r'[^a-zA-Z0-9]+', '_', campaign["name"]).strip('_').lower()
                    campaign_dir = f"{safe_name}_{campaign_id}"
        
        # Move the folder if it exists in the flat directory
        old_dir = jobs_dir / job_id
        new_dir = jobs_dir / campaign_dir / job_id
        
        if old_dir.exists() and old_dir.is_dir():
            print(f"  Moving {old_dir} -> {new_dir}")
            new_dir.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(old_dir), str(new_dir))
        else:
            print(f"  Folder {old_dir} not found (already moved or missing).")
            
        # Update the database
        with queue._connect() as conn:
            conn.execute("UPDATE jobs SET campaign_dir = ? WHERE id = ?", (campaign_dir, job_id))
            print(f"  Updated database for {job_id} -> {campaign_dir}")

    print("Migration complete!")

if __name__ == "__main__":
    main()
