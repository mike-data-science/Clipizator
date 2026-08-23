import os
import time
import json
from pathlib import Path
from azure.storage.blob import BlobServiceClient
from azure.core.exceptions import ResourceExistsError

# Configuration
JOBS_DIR = Path.home() / ".publikclip" / "jobs"
CONTAINER_NAME = "publikclip-videos"

def main():
    conn_string = os.environ.get("AZURE_STORAGE_CONNECTION_STRING")
    if not conn_string:
        print("ERROR: Please set the AZURE_STORAGE_CONNECTION_STRING environment variable.")
        return

    print("Connecting to Azure Blob Storage...")
    blob_service_client = BlobServiceClient.from_connection_string(conn_string)

    # Create the container if it doesn't exist
    container_client = blob_service_client.get_container_client(CONTAINER_NAME)
    try:
        container_client.create_container()
        print(f"Created container '{CONTAINER_NAME}'")
    except ResourceExistsError:
        print(f"Container '{CONTAINER_NAME}' already exists.")

    print(f"Monitoring {JOBS_DIR} for new files to upload...")

    while True:
        if JOBS_DIR.exists():
            for job_path in JOBS_DIR.iterdir():
                if not job_path.is_dir():
                    continue
                
                # Check if it has a job.json (meaning it's a valid job folder)
                if not (job_path / "job.json").exists():
                    continue

                # Check if we already uploaded it
                uploaded_marker = job_path / "azure_uploaded.json"
                if uploaded_marker.exists():
                    continue

                print(f"Found new job to upload: {job_path.name}")
                
                # Upload all files in this job directory
                all_success = True
                for file_path in job_path.rglob("*"):
                    if file_path.is_file() and file_path.name != "azure_uploaded.json":
                        blob_name = f"{job_path.name}/{file_path.relative_to(job_path).as_posix()}"
                        blob_client = container_client.get_blob_client(blob_name)
                        
                        try:
                            print(f"  Uploading {file_path.name}...")
                            with open(file_path, "rb") as data:
                                blob_client.upload_blob(data, overwrite=True)
                        except Exception as e:
                            print(f"  Failed to upload {file_path.name}: {e}")
                            all_success = False

                if all_success:
                    print(f"Successfully uploaded job {job_path.name} to Azure!")
                    # Mark as uploaded so we don't upload it again
                    with open(uploaded_marker, "w") as f:
                        json.dump({"uploaded": True, "timestamp": time.time()}, f)
                else:
                    print(f"Some files failed to upload for {job_path.name}. Will try again later.")
        
        # Wait 10 seconds before checking again
        time.sleep(10)

if __name__ == "__main__":
    main()
