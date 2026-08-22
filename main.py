#!/usr/bin/env python3
"""
Download a YouTube video at the best available quality using yt-dlp.

Setup:
    pip install yt-dlp

    ffmpeg is also required, since the best quality is usually a separate
    video stream + audio stream that need to be merged:
        macOS:   brew install ffmpeg
        Ubuntu:  sudo apt install ffmpeg
        Windows: https://ffmpeg.org/download.html  (add it to your PATH)

Usage:
    python download_youtube_video.py
    python download_youtube_video.py "https://www.youtube.com/watch?v=..."
"""

import sys
import yt_dlp

DEFAULT_URL = "https://www.youtube.com/watch?v=jr9ESVOtyMo"


def download_video(url: str, output_dir: str = ".") -> str:
    """Download a video at the highest available quality and return the saved path."""
    ydl_opts = {
        # Best video + best audio streams, merged into one file.
        # Falls back to the best pre-combined stream if separate ones aren't available.
        # Prioritize 60fps (or higher) streams, fallback to standard best video
        "format": "bestvideo[fps>=60]+bestaudio/bestvideo+bestaudio/best",
        "merge_output_format": "mp4",
        "outtmpl": f"{output_dir}/%(title)s.%(ext)s",
        "noplaylist": True,
        "cookiefile": "cookies.txt",
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)
        return ydl.prepare_filename(info)


if __name__ == "__main__":
    url = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_URL
    saved_path = download_video(url)
    print(f"Downloaded: {saved_path}")