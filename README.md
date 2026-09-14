# publikclip

**Long video in. Scored vertical clips out. Everything runs on your machine.**

publikclip is an open-source (AGPL-3.0) desktop app that takes a YouTube URL or a
horizontal video file and produces vertical 9:16 clips with:

- **Smart camera** — active-speaker-tracked crop paths, smoothed motion, hard cuts
  on speaker change, punch-ins fired by actual laughter and vocal energy
- **Word-accurate captions** — multiple styles, karaoke highlighting, prosodic
  emphasis (loud words get loud styling), `[laughs]` tags from real laughter detection
- **A virality score you can audit** — never a bare number: every clip ships with
  its subscores, which detectors fired, and every adjustment applied. LLM humor
  scores get discounted when no actual laughter corroborates them.
- **Music-type suggestions** — an editable genre/mood/energy brief derived from
  what's being said and how it sounds
- **Optional real-outcomes loop** — connect your own Instagram (via your own Meta
  app, no middleman) and the scorer calibrates against how your clips actually perform

Every model — speech recognition, forced alignment, diarization, laughter
detection, audio tagging, face detection, active-speaker detection — runs
locally. The only network calls are the video download and 2–3 small LLM calls
(bring your own Gemini key, or run fully local via Ollama at reduced scoring
quality).

## Status

Working end to end: hour-long podcast in, rendered/captioned/scored 9:16 clips
out, validated on real footage. The Instagram feedback loop ships in-app
(sync, clip↔Reel matching, snapshot history, automatic score calibration).
Builds are currently unsigned — install from source below, or follow the
guided install at [publikhq.com/publikclip](https://publikhq.com/publikclip).

Runs on macOS (Apple silicon) and Windows 10/11 x64. The Windows path is
validated on every push by the `windows` workflow: env resolve, full test
suite, NSIS build, silent install, and a launch of the installed app on a
clean VM.

## Layout

```
pipeline/   Python package — the entire processing pipeline + CLI
app/        Tauri v2 desktop shell (React UI, Python sidecar)
```

## Install from source (macOS)

You need four tools: git, [Node](https://nodejs.org), [Rust](https://rustup.rs),
and [uv](https://docs.astral.sh/uv/). Then:

```sh
git clone https://github.com/Blueturboguy07/publikclip.git
cd publikclip/app
npm install
npx tauri build --bundles app
ditto src-tauri/target/release/bundle/macos/publikclip.app /Applications/publikclip.app
open /Applications/publikclip.app
```

The app downloads its speech/audio models (~4–5 GB) on first run with a
progress UI, and fetches a caption-capable static ffmpeg automatically if the
machine has none. Scoring uses your own Gemini API key, or a local Ollama
model at reduced scoring quality — onboarding walks through both.

## Install from source (Windows)

You need [Rust](https://rustup.rs), the Visual Studio **Desktop development
with C++** build tools, [Node](https://nodejs.org), git, and
[uv](https://docs.astral.sh/uv/) (`winget install --id astral-sh.uv -e`).
Then, in PowerShell:

```powershell
git clone https://github.com/Blueturboguy07/publikclip.git
cd publikclip\app
npm.cmd install
node_modules\.bin\tauri.cmd build --bundles nsis
# run the installer it produces:
Start-Process (Get-ChildItem src-tauri\target\release\bundle\nsis -Filter *-setup.exe).FullName
```

First run behaves the same as on macOS: models download behind a progress
bar, and a caption-capable static ffmpeg is fetched automatically.

## Development

### Linux / SSH with NVIDIA GPU

From the project directory, install the optional camera inference runtime after
the base dependencies (the tested environment uses PyTorch 2.8 / CUDA 12.8):

```sh
venv/bin/python -m pip install -r requirements-gpu.txt
```

The runtime is pinned for the project's CUDA 12 libraries; newer ONNX GPU
packages require CUDA 13. See the
[ONNX CUDA compatibility table](https://onnxruntime.ai/docs/execution-providers/CUDA-ExecutionProvider.html#requirements).

Start these in separate SSH terminals:

```sh
cd ~/Desktop/Clipizator/backend
../venv/bin/python -m uvicorn server:app --host 127.0.0.1 --port 8000
```

```sh
cd ~/Desktop/Clipizator/app
npm run dev -- --host 127.0.0.1
```

Tunnel port 5173 and open `http://localhost:5173` on Windows. Vite proxies API
requests to the backend. Restart the backend after changing pipeline code.

Rendering probes CUDA scaling and NVENC before using them, including for edited
clips. CUDA scaling avoids the FFmpeg 6.1 software-scaler freeze observed when a
camera punch-in changes the crop dimensions. A watchdog aborts FFmpeg after 120
seconds without advancing frames or output time, even if it keeps emitting
unchanged progress messages. Resume preserves completed analysis checkpoints.

Face detection and active-speaker analysis prefer the ONNX CUDA provider;
speech transcription, alignment, diarization, and audio models already select
CUDA when available. The progress messages show the selected render/camera
acceleration. Caption burning, crop commands, audio filters, and I/O still use
the CPU. NVIDIA's encoder is separate from its general compute cores, so a
fully busy encoder does not imply 100% general GPU utilization. To inspect both:

```sh
nvidia-smi --query-gpu=utilization.gpu,utilization.encoder,memory.used --format=csv -l 1
```

Review defaults to a cached 720×1280 H.264 playback preview at approximately
1.6 Mbps video plus 96 kbps audio. The original 4K clip is still used for exports;
choose **Original · full quality** in the player to inspect it. Preview generation
uses NVIDIA decoding, scaling, and encoding where supported, with CPU decoding
fallback. A new preview is prepared on first use, then reused. Re-rendering a clip
automatically gives it a new preview cache key. Browser playback supports byte
ranges, fast-start MP4s, and private caching without downloading the full export
into a JavaScript blob. Preview files live in each clips directory's `.previews`.

For the Windows tunnel `ssh -N -L 1080:localhost:5173 -L 8001:localhost:8000 Mike@4.231.114.220`,
open `http://localhost:1080`. Alternatively, after running `npm run build` in `app`,
open `http://localhost:8001` to use the built frontend served directly by the
Linux backend. The latter does not require the Vite dev server.

```sh
# pipeline
cd pipeline && uv sync && uv run pytest
# or, with pip requirements installed:
# pip install -r ../requirements.txt && python -m pytest
uv run publikclip run "https://www.youtube.com/watch?v=..."

# optional laptop worker for downloading campaign sources
# same PC as the backend:
PUBLIKCLIP_SERVER_URL=http://127.0.0.1:8000 python laptop_worker.py
# separate laptop: replace the address with the backend PC's LAN IP
# PUBLIKCLIP_SERVER_URL=http://192.168.1.50:8000 python laptop_worker.py
# VM through an SSH tunnel from the laptop:
# ssh -N -L 8001:127.0.0.1:8000 user@4.231.114.220
# in a second terminal:
# python laptop_worker.py --server-url http://127.0.0.1:8001
# or explicitly:
# python laptop_worker.py --server-url http://127.0.0.1:8001 --cookies-from-browser chrome
# or use an exported Netscape cookies file (keep it private):
# python laptop_worker.py --server-url http://127.0.0.1:8001 --cookies C:\path\to\cookies.txt
# test the connection once without waiting:
# python laptop_worker.py --server-url http://127.0.0.1:8001 --once
# yt-dlp uses the laptop's normal internet connection by default.
# Optional SOCKS proxy for yt-dlp (only with an SSH -D tunnel):
# ssh -N -D 1080 user@4.231.114.220
# PUBLIKCLIP_YTDLP_PROXY=socks5://127.0.0.1:1080 python laptop_worker.py --server-url http://127.0.0.1:8001
# Windows YouTube login: close the browser first, then run one of:
# set PUBLIKCLIP_COOKIES_FROM_BROWSER=chrome
# set PUBLIKCLIP_COOKIES_FROM_BROWSER=edge
# python laptop_worker.py --server-url http://127.0.0.1:8001

# app
cd app && npm install && npm run tauri dev
```

## License

AGPL-3.0-or-later. Portions adapted from other open-source projects — see
`VENDORED-LICENSES.md` for the full provenance list.
