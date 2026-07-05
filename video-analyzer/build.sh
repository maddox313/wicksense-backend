#!/usr/bin/env bash
# video-analyzer/build.sh
# Render build script for wicksense-video-analyzer (native Python, no Docker)
# Installs system binaries (ffmpeg) and Python dependencies

set -e

echo "=== [BUILD] wicksense-video-analyzer ==="
echo "=== [BUILD] Installing system packages ==="

# Install ffmpeg via apt (available on Render's Ubuntu build environment)
apt-get update -qq && apt-get install -y --no-install-recommends ffmpeg

echo "=== [BUILD] ffmpeg installed ==="
ffmpeg -version | head -1

echo "=== [BUILD] Installing Python dependencies ==="
pip install --upgrade pip
pip install -r requirements.txt

echo "=== [BUILD] Verifying yt-dlp ==="
yt-dlp --version

echo "=== [BUILD] Verifying openai-whisper ==="
python -c "import whisper; print('whisper OK')"

echo "=== [BUILD] Build complete ==="
