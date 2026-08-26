import json
from pathlib import Path
import sys

sys.path.append(str(Path.cwd() / 'pipeline'))
from publikclip_pipeline.campaigns import store
from publikclip_pipeline.config import home_dir

jobs_dir = home_dir() / 'jobs'
if jobs_dir.exists():
    for d in jobs_dir.iterdir():
        if d.is_dir():
            asr = d / 'asr.json'
            ing = d / 'ingest.json'
            if asr.exists() and ing.exists():
                try:
                    with open(asr, 'rb') as f:
                        a = json.loads(f.read().decode('utf-8', errors='ignore'))
                    with open(ing, 'rb') as f:
                        i = json.loads(f.read().decode('utf-8', errors='ignore'))
                    
                    url = i.get('data', {}).get('audio_path', '').replace('clip_', 'https://youtu.be/').replace('.mp4', '') 
                    if not url.startswith('http'):
                        url = i.get('data', {}).get('source')
                        
                    if url:
                        store.store_transcript(
                            video_url=url,
                            campaign_id=None,
                            title=i.get('data', {}).get('title'),
                            channel=i.get('data', {}).get('channel'),
                            duration_sec=i.get('data', {}).get('duration'),
                            transcript=a.get('data', {}).get('segments', []),
                            word_count=a.get('data', {}).get('word_count', 0)
                        )
                        print(f'Synced {url}')
                except Exception as e:
                    print(f"Error on {d.name}: {e}")
print('Migration complete')
