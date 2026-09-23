# Publikclip — Azure GPU VM Runbook

Last updated: September 2026

This document is the canonical procedure for creating, cloning, recovering,
and validating Azure GPU VMs used by Publikclip.

---

# 1. Goal

Publikclip GPU infrastructure should be reproducible.

A VM should be considered disposable.

If a VM disappears:

- CODE → Git
- IMPORTANT DATA → persistent Azure disk
- MODELS → downloadable again
- CACHE → regenerable
- CONFIGURATION → reproducible from this runbook

Never depend on undocumented manual configuration.

---

# 2. Standard Publikclip VM Architecture

Recommended storage layout:

    /                       OS disk
    ├── Ubuntu
    ├── system packages
    ├── ~/Desktop/Clipizator
    └── Python .venv

    /data                   PERSISTENT Azure Data Disk
    └── publikclip
        ├── videos
        ├── analysis
        ├── renders
        ├── databases
        └── important artifacts

    /mnt                    TEMPORARY Azure local disk
    ├── ollama
    ├── model caches
    ├── temporary frames
    └── temporary processing

Rules:

    /       = OS + code
    /data   = IMPORTANT / PERSISTENT
    /mnt    = DISPOSABLE / REGENERABLE

Never store irreplaceable data only under /mnt.

---

# 3. Current Primary VM

Reference development GPU:

    Standard_NC4as_T4_v3

Typical resources:

    NVIDIA Tesla T4
    16 GB VRAM
    4 vCPU
    ~28 GB RAM

Use for:

- Publikclip development
- Analyzer
- ASR
- audio/visual analysis
- Qwen 8B
- FFmpeg rendering
- normal experiments

Preferred deployment:

    Azure Spot

Recommended Spot settings:

    Eviction type: Capacity only
    Eviction policy: Stop / Deallocate

---

# 4. Experimental A100 VM

Target experimental SKU:

    Standard_NC24ads_A100_v4

Use only when needed for:

- VLM experiments
- larger models
- multimodal benchmarks
- T4 vs A100 benchmarks
- workloads exceeding T4 capabilities

A100 should normally be:

    create/start
        ↓
    benchmark
        ↓
    persist results
        ↓
    deallocate

Do not leave A100 running unnecessarily.

IMPORTANT:

Do NOT blindly install the T4 GRID driver on an A100.

Always check the current Azure/NVIDIA recommendation
for the A100 VM family before installing the GPU driver.

---

# 5. Preferred VM Creation Strategy

There are TWO supported paths.

## PATH A — Azure Image

PREFERRED once the current T4 environment is stable.

    Publikclip Base Image
            ↓
    Create new GPU VM
            ↓
    attach persistent storage
            ↓
    verify GPU
            ↓
    git pull
            ↓
    start Publikclip

This avoids repeating most installation work.


## PATH B — Fresh VM

Use when:

- no compatible image exists
- testing a significantly different GPU
- image is outdated
- debugging infrastructure
- Azure image deployment fails

Follow the full installation procedure below.

---

# 6. Before Creating Any VM

Check Azure:

- target region
- VM SKU availability
- Spot availability
- Total Regional Spot vCPU quota
- GPU-family quota
- availability-zone support
- current Spot price

Do not assume quota from one region applies to another.

Do not assume a SKU shown in quota settings is currently deployable.

---

# 7. Azure VM Settings

Recommended OS:

    Ubuntu Server 24.04 LTS x64 Gen2

Architecture:

    x64

Authentication:

    SSH public key

For our current T4 driver configuration:

    Secure Boot: OFF
    vTPM: OFF

Spot:

    ON

Eviction:

    Capacity only

Eviction policy:

    Stop / Deallocate

---

# 8. OS Disk

30 GB technically works but is too tight.

Recommended for future VMs:

    64 GB minimum

Better:

    128 GB

OS disk should contain:

- Ubuntu
- repository
- .venv
- system dependencies
- Node
- Codex
- FFmpeg

Do NOT use the OS disk as primary video storage.

---

# 9. Persistent Data Disk

Recommended:

    256 GiB+

Current reference:

    Standard SSD LRS
    256 GiB

Use for:

    .publikclip
    source media
    analysis artifacts
    renders
    databases
    important outputs

Mount point:

    /data

---

# 10. Temporary Azure Disk

GPU VMs may provide local temporary storage.

Example:

    /mnt

Current T4 example:

    ~176 GB

Use for:

    Ollama models
    caches
    temporary processing
    temporary downloads

WARNING:

Data on this disk can disappear.

Anything stored here must be reproducible.

---

# 11. SSH From Windows

Example key:

    C:\Users\Mike\Desktop\clipozaurVm_key.pem

Connect:

    ssh -i C:\Users\Mike\Desktop\clipozaurVm_key.pem azureuser@PUBLIC_IP

---

# 12. Fix Windows SSH Key Permissions

If SSH says:

    WARNING: UNPROTECTED PRIVATE KEY FILE!

Run:

    icacls C:\Users\Mike\Desktop\clipozaurVm_key.pem /inheritance:r

    icacls C:\Users\Mike\Desktop\clipozaurVm_key.pem /remove "DESKTOP-RN05L6U\CodexSandboxUsers"

    icacls C:\Users\Mike\Desktop\clipozaurVm_key.pem /grant:r "%USERNAME%:R"

Then reconnect.

---

# 13. FIRST COMMANDS ON EVERY NEW VM

Before installing anything:

    lsblk
    df -h
    free -h
    lscpu

Try:

    nvidia-smi

Record:

- OS disk
- temporary disk
- persistent disks
- free space
- GPU status

Never format a disk before identifying it with lsblk.

---

# 14. Base Ubuntu Setup

    sudo apt update
    sudo apt upgrade -y

Install:

    sudo apt install -y \
      build-essential \
      git \
      git-lfs \
      curl \
      wget \
      unzip \
      zip \
      jq \
      htop \
      tmux \
      ffmpeg \
      sqlite3 \
      python3 \
      python3-pip \
      python3-venv \
      python3-dev \
      pkg-config \
      libgl1 \
      libglib2.0-0 \
      libsm6 \
      libxext6 \
      libxrender1 \
      libsndfile1 \
      libgomp1 \
      libssl-dev \
      ca-certificates \
      rsync

---

# 15. T4 NVIDIA Driver

ONLY for the compatible T4 configuration.

Current working installer:

    NVIDIA-Linux-x86_64-595.58.03-grid-azure.run

Download:

    cd ~

    wget -O NVIDIA-Linux-x86_64-595.58.03-grid-azure.run \
    https://download.microsoft.com/download/51239696-ec04-4c02-a6b3-1d9c608fb57c/NVIDIA-Linux-x86_64-595.58.03-grid-azure.run

Make executable:

    chmod +x NVIDIA-Linux-x86_64-595.58.03-grid-azure.run

Install:

    sudo ./NVIDIA-Linux-x86_64-595.58.03-grid-azure.run

If asked for module type:

    NVIDIA Proprietary

With Secure Boot disabled, module signing should not
normally be required.

After installation:

    sudo reboot

Reconnect.

Verify:

    nvidia-smi

Expected:

    NVIDIA Tesla T4
    ~16 GB VRAM

---

# 16. A100 NVIDIA Driver

DO NOT COPY THE T4 DRIVER PROCEDURE BLINDLY.

For a new A100:

1. Check current Azure documentation.
2. Check current NVIDIA recommendation.
3. Identify exact A100 Azure SKU.
4. Install supported compute driver.
5. Reboot.
6. Run:

       nvidia-smi

7. Confirm A100 is visible.
8. Only then install Python GPU dependencies.

Never assume a driver version in this document remains
the correct A100 driver in the future.

---

# 17. Attach Persistent Data Disk

After attaching the disk in Azure:

    lsblk

Example:

    sda    OS
    sdb    temporary
    sdc    new persistent disk

WARNING:

The device name may be different.

Never blindly run mkfs on `/dev/sdc`.

Confirm first.

---

# 18. Format NEW Data Disk

ONLY if the disk is new and empty:

    sudo mkfs.ext4 /dev/sdc

Create mount:

    sudo mkdir -p /data

Mount:

    sudo mount /dev/sdc /data

Ownership:

    sudo chown azureuser:azureuser /data

Verify:

    df -h /data

---

# 19. Persistent Mount

Get UUID:

    sudo blkid /dev/sdc

Example:

    UUID="xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"

Edit:

    sudo nano /etc/fstab

Add:

    UUID=YOUR_UUID /data ext4 defaults,nofail 0 2

Test:

    sudo mount -a

Verify:

    df -h /data

Do NOT reboot until `mount -a` succeeds.

---

# 20. Move .publikclip to Persistent Disk

Create:

    mkdir -p /data/publikclip

Copy:

    rsync -a --info=progress2 ~/.publikclip/ /data/publikclip/

Backup:

    mv ~/.publikclip ~/.publikclip_backup

Symlink:

    ln -s /data/publikclip ~/.publikclip

Verify:

    ls -ld ~/.publikclip

Expected:

    ~/.publikclip -> /data/publikclip

Check:

    du -sh /data/publikclip

Only after verification:

    rm -rf ~/.publikclip_backup

---

# 21. IMPORTANT .publikclip Migration Warning

Do NOT blindly copy `.publikclip` from old VMs/Windows.

It may contain:

- SQLite DBs
- absolute paths
- projects
- campaigns
- media
- analysis artifacts
- machine-specific references

Migration should be deliberate.

---

# 22. Install Node.js

    curl -fsSL https://deb.nodesource.com/setup_22.x | sudo -E bash -

    sudo apt install -y nodejs

Verify:

    node -v
    npm -v

---

# 23. Install Codex CLI

    sudo npm install -g @openai/codex@latest

Verify:

    codex --version

Later:

    cd ~/Desktop/Clipizator
    codex

Authenticate when requested.

---

# 24. Install uv

    curl -LsSf https://astral.sh/uv/install.sh | sh

    source ~/.bashrc

Verify:

    uv --version

---

# 25. Clone Publikclip

    mkdir -p ~/Desktop

    cd ~/Desktop

    git clone <REPOSITORY_URL> Clipizator

    cd Clipizator

Then:

    git lfs install
    git lfs pull

Check:

    git status
    git branch --show-current

---

# 26. Python Virtual Environment

    cd ~/Desktop/Clipizator

    python3 -m venv .venv

Activate:

    source .venv/bin/activate

Upgrade:

    python -m pip install --upgrade pip setuptools wheel

Verify:

    which python
    which pip

Both should point inside `.venv`.

---

# 27. Publikclip Python Dependencies

Current dependency files:

    requirements.txt
    requirements-gpu.txt
    backend/requirements.txt
    pipeline/pyproject.toml

Install:

    pip install -r requirements.txt

    pip install -r backend/requirements.txt

    pip install -r requirements-gpu.txt

    pip install -e ./pipeline

Do NOT install Python libraries one-by-one with apt.

Do NOT rely on system Uvicorn.

---

# 28. Verify Backend Environment

    python -c "import fastapi, uvicorn; print('FastAPI/Uvicorn OK')"

GPU/PyTorch:

    python -c "import torch; print('PyTorch:', torch.__version__); print('CUDA runtime:', torch.version.cuda); print('CUDA:', torch.cuda.is_available()); print('GPU:', torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'NONE')"

Expected T4:

    CUDA: True
    GPU: Tesla T4

Expected A100:

    CUDA: True
    GPU: NVIDIA A100...

---

# 29. Install Ollama

    curl -fsSL https://ollama.com/install.sh | sh

Do NOT download large models yet.

---

# 30. Put Ollama Models on Temporary Disk

Create:

    sudo mkdir -p /mnt/ollama

Ownership:

    sudo chown -R ollama:ollama /mnt/ollama

Configure systemd:

    sudo mkdir -p /etc/systemd/system/ollama.service.d

    sudo tee /etc/systemd/system/ollama.service.d/override.conf > /dev/null <<'EOF'
    [Service]
    Environment="OLLAMA_MODELS=/mnt/ollama"
    EOF

Reload:

    sudo systemctl daemon-reload
    sudo systemctl restart ollama

Verify:

    sudo systemctl show ollama --property=Environment --no-pager | tr ' ' '\n' | grep OLLAMA

Expected:

    OLLAMA_MODELS=/mnt/ollama

---

# 31. Install Qwen

Current local LLM:

    qwen3:8b

Download:

    ollama pull qwen3:8b

Verify:

    ollama list

Test:

    ollama run qwen3:8b "Reply only with: Qwen works"

GPU monitor:

    watch -n 1 nvidia-smi

---

# 32. If Root Disk Becomes Full

Check:

    df -h /

Find large directories:

    sudo du -xhd1 / | sort -h

Check user:

    du -sh ~/* ~/.??* 2>/dev/null | sort -h

Failed Ollama downloads may leave partial blobs.

Example cleanup:

    sudo rm -f /usr/share/ollama/.ollama/models/blobs/*-partial

APT cache:

    sudo apt clean

Then:

    df -h /

Do NOT randomly delete `.publikclip`.

---

# 33. Frontend Setup

Locate:

    find . -maxdepth 3 -name package.json -print

Enter actual frontend directory.

Install:

    npm install

Start:

    npm run dev -- --host 0.0.0.0

Expected:

    port 5173

---

# 34. Backend Startup

Every shell:

    cd ~/Desktop/Clipizator

    source .venv/bin/activate

Start:

    python -m uvicorn backend.server:app --host 0.0.0.0 --port 8000

Check:

    curl http://127.0.0.1:8000

---

# 35. Windows SSH Tunnel

    ssh -i C:\Users\Mike\Desktop\clipozaurVm_key.pem -N -L 1080:localhost:5173 -L 8001:localhost:8000 azureuser@PUBLIC_IP

Windows access:

    Frontend:
    http://localhost:1080

    Backend:
    http://localhost:8001

---

# 36. Windows YouTube Worker

YouTube may block Azure IPs.

Publikclip should use the Windows/local worker:

    Azure
       ↓
    waiting_for_worker
       ↓
    Windows laptop
       ↓
    yt-dlp
       ↓
    upload source
       ↓
    resume pipeline

Example:

    python laptop_worker.py --server-url http://127.0.0.1:8001

---

# 37. 2-Minute VM Validation

After creating/cloning/restarting a VM:

## Storage

    df -h
    lsblk

Confirm:

    /data mounted
    /mnt available

## GPU

    nvidia-smi

## Publikclip data

    ls -ld ~/.publikclip

Expected:

    ~/.publikclip -> /data/publikclip

## Python

    cd ~/Desktop/Clipizator
    source .venv/bin/activate

    python -c "import torch; print(torch.cuda.is_available()); print(torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'NO GPU')"

## Ollama

    ollama list

## Git

    git status

If all pass, VM is ready.

---

# 38. Daily Startup

Do NOT repeat installation.

Terminal 1:

    cd ~/Desktop/Clipizator
    source .venv/bin/activate
    python -m uvicorn backend.server:app --host 0.0.0.0 --port 8000

Terminal 2:

    cd ~/Desktop/Clipizator/<FRONTEND>
    npm run dev -- --host 0.0.0.0

Windows tunnel:

    ssh -i <KEY> -N -L 1080:localhost:5173 -L 8001:localhost:8000 azureuser@PUBLIC_IP

Windows worker:

    python laptop_worker.py --server-url http://127.0.0.1:8001

---

# 39. Before Stopping / Deallocating

Check Git:

    git status

Push important code.

Check persistent disk:

    df -h /data

Anything important currently under `/mnt` should be considered disposable.

Then deallocate VM.

---

# 40. Azure Image Strategy

Once the current VM has been stable for several days,
create a reusable:

    Publikclip GPU Base Image v1

The image should contain:

- Ubuntu configuration
- system dependencies
- FFmpeg
- Git / Git LFS
- Node.js
- Codex CLI
- Python tooling
- stable GPU setup where appropriate
- common Publikclip dependencies

Do NOT bake into the image:

- API secrets
- SSH private keys
- user videos
- project databases
- `.publikclip`
- temporary caches
- Ollama model blobs unless intentionally desired

---

# 41. IMPORTANT — T4 Image vs A100

A complete T4 VM image is not automatically the ideal A100 image.

Preferred long-term approach:

    Publikclip Base
         │
         ├── T4 GPU configuration
         │
         └── A100 GPU configuration

Avoid making the NVIDIA driver the fragile part of a universal image.

The application environment should be shared.

GPU-specific driver configuration can remain GPU-family-specific.

---

# 42. Future Fast Deployment

Ideal future workflow:

    Create VM
        ↓
    choose Publikclip image
        ↓
    attach /data
        ↓
    boot
        ↓
    verify nvidia-smi
        ↓
    git pull
        ↓
    verify .venv
        ↓
    start backend/frontend
        ↓
    work

Target:

    5–10 minutes instead of rebuilding the VM manually.

---

# 43. A100 Quick Procedure

When A100 quota becomes available:

    1. Check Spot price.
    2. Check SKU availability.
    3. Create NC24ads_A100_v4.
    4. Prefer compatible Publikclip base image if available.
    5. Inspect lsblk.
    6. Configure/attach persistent disk if required.
    7. Install/verify CURRENT A100 driver.
    8. Run nvidia-smi.
    9. Verify PyTorch CUDA.
    10. Clone/pull Publikclip.
    11. Run benchmark.
    12. Persist benchmark results.
    13. Deallocate A100.

Do not spend A100 time doing basic package installation if an image can avoid it.

---

# 44. Recovery After Spot Eviction

After Spot VM returns:

    lsblk
    df -h

Verify:

    /data

Then:

    nvidia-smi

Then:

    ls -ld ~/.publikclip

Then:

    cd ~/Desktop/Clipizator
    git status

Temporary `/mnt` may have been cleared.

If Ollama models disappeared:

    sudo mkdir -p /mnt/ollama
    sudo chown -R ollama:ollama /mnt/ollama

    sudo systemctl restart ollama

    ollama pull qwen3:8b

This is expected.

Project data must remain on `/data`.

---

# 45. Golden Rule

Treat every compute VM as disposable.

A correctly designed Publikclip environment should survive losing
the VM itself.

CODE:
    Git

PROJECT DATA:
    persistent disk / future object storage

MODELS:
    downloadable

CACHE:
    regenerable

SETUP:
    this runbook

SECRETS:
    external configuration / secure storage

The VM is compute, not the source of truth.