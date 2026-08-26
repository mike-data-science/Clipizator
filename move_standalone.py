import shutil
from pathlib import Path

from publikclip_pipeline.jobs import queue
from publikclip_pipeline.campaigns import store
from publikclip_pipeline import config
import re

def main():
    print("Moving standalone jobs to lovable...")
    jobs_dir = config.jobs_dir()
    
    with store._connect() as conn:
        c = conn.execute("SELECT id, name FROM campaigns LIMIT 1").fetchone()
        if not c:
            print("No campaigns found!")
            return
            
        safe_name = re.sub(r'[^a-zA-Z0-9]+', '_', c["name"]).strip('_').lower()
        campaign_dir = f"{safe_name}_{c['id']}"
        print(f"Target campaign dir: {campaign_dir}")
        
    with queue._connect() as conn:
        rows = conn.execute("SELECT id FROM jobs WHERE campaign_dir = 'standalone'").fetchall()
        
    for row in rows:
        job_id = row["id"]
        print(f"Processing job {job_id}...")
        
        old_dir = jobs_dir / "standalone" / job_id
        new_dir = jobs_dir / campaign_dir / job_id
        
        if old_dir.exists() and old_dir.is_dir():
            print(f"  Moving {old_dir} -> {new_dir}")
            new_dir.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(old_dir), str(new_dir))
        else:
            print(f"  Folder {old_dir} not found (already moved or missing).")
            
        with queue._connect() as conn:
            conn.execute("UPDATE jobs SET campaign_dir = ? WHERE id = ?", (campaign_dir, job_id))
            print(f"  Updated database for {job_id} -> {campaign_dir}")

    # Remove the standalone directory if it's empty
    standalone_dir = jobs_dir / "standalone"
    if standalone_dir.exists() and standalone_dir.is_dir():
        if not any(standalone_dir.iterdir()):
            standalone_dir.rmdir()
            print("Removed empty standalone directory.")
        else:
            print("standalone directory is not empty, leaving it.")
            
    print("Migration complete!")

if __name__ == "__main__":
    main()
