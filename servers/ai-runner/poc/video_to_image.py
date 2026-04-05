#!/usr/bin/env python3
"""
Video-to-Image POC
------------------
Takes a video file, samples frames, sends them to the AI model,
and saves the model-selected best frames for use on a recipe/blog page.

Usage:
    python3 video_to_image.py <video_path> [--output <dir>] [--interval <seconds>]

Requirements:
    - ffmpeg installed locally
    - AI backend running at API_BASE (LiteLLM on airunner01)
"""

import argparse
import base64
import json
import os
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import urllib.error

API_BASE = "http://192.168.4.56:8000/v1"
MODEL = "qwen3-vl:30b"
DEFAULT_INTERVAL = 30   # seconds between sampled frames
DEFAULT_SCALE = "1280:720"  # resize to 720p to keep token count manageable


def extract_frames(video_path, interval, scale, output_dir):
    """Extract frames from video at given interval, scaled to target resolution."""
    cmd = [
        "ffmpeg", "-i", video_path,
        "-vf", f"fps=1/{interval},scale={scale}",
        os.path.join(output_dir, "frame_%03d.jpg"),
        "-y", "-loglevel", "error"
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"ffmpeg error: {result.stderr}", file=sys.stderr)
        sys.exit(1)

    frames = sorted(f for f in os.listdir(output_dir) if f.endswith(".jpg"))
    return frames


def build_message(frames_dir, frames, interval):
    """Build the multimodal message content: numbered frames + prompt."""
    content = []
    for i, fname in enumerate(frames):
        timestamp = i * interval
        minutes, seconds = divmod(timestamp, 60)
        timestamp_str = f"{minutes}m{seconds:02d}s" if minutes else f"{seconds}s"

        with open(os.path.join(frames_dir, fname), "rb") as f:
            b64 = base64.b64encode(f.read()).decode()

        content.append({"type": "text", "text": f"[Frame {i+1} — {timestamp_str}]"})
        content.append({"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}})

    content.append({
        "type": "text",
        "text": (
            f"These are {len(frames)} frames sampled every {interval} seconds from a food or recipe video. "
            "Identify the 3-4 frames that would make the best images for a recipe blog post. "
            "Reply with the frame numbers (e.g. Frame 3, Frame 7) and a one-sentence explanation "
            "for each. Be specific about what is visually shown in each chosen frame."
        )
    })
    return content


def call_model(content):
    """Send frames to the model and return the response text and token usage."""
    payload = {
        "model": MODEL,
        "messages": [{"role": "user", "content": content}],
        "max_tokens": 600
    }
    req = urllib.request.Request(
        f"{API_BASE}/chat/completions",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(req, timeout=300) as r:
            result = json.loads(r.read())
        return result["choices"][0]["message"]["content"], result["usage"]
    except urllib.error.HTTPError as e:
        print(f"API error {e.code}: {e.read().decode()}", file=sys.stderr)
        sys.exit(1)


def parse_frame_numbers(response):
    """Extract frame numbers mentioned in the model response, deduplicated."""
    import re
    numbers = [int(n) for n in re.findall(r"[Ff]rame\s+(\d+)", response)]
    return list(dict.fromkeys(numbers))  # preserve order, remove duplicates


def save_selected_frames(frames_dir, frames, selected_numbers, output_dir):
    """Copy the model-selected frames to the output directory."""
    os.makedirs(output_dir, exist_ok=True)
    saved = []
    for n in selected_numbers:
        if 1 <= n <= len(frames):
            src = os.path.join(frames_dir, frames[n - 1])
            dst = os.path.join(output_dir, f"selected_frame_{n:02d}.jpg")
            shutil.copy2(src, dst)
            saved.append(dst)
    return saved


def main():
    parser = argparse.ArgumentParser(description="Extract best recipe images from a video using AI")
    parser.add_argument("video", help="Path to input video file")
    parser.add_argument("--output", default="./output_frames", help="Directory to save selected frames")
    parser.add_argument("--interval", type=int, default=DEFAULT_INTERVAL,
                        help=f"Seconds between sampled frames (default: {DEFAULT_INTERVAL})")
    args = parser.parse_args()

    if not os.path.exists(args.video):
        print(f"Video not found: {args.video}", file=sys.stderr)
        sys.exit(1)

    print(f"Video: {args.video}")
    print(f"Sampling: 1 frame every {args.interval}s at 720p")

    with tempfile.TemporaryDirectory() as tmpdir:
        print("Extracting frames...")
        frames = extract_frames(args.video, args.interval, DEFAULT_SCALE, tmpdir)
        print(f"  {len(frames)} frames extracted")

        print("Sending frames to model...")
        content = build_message(tmpdir, frames, args.interval)
        response, usage = call_model(content)

        print(f"\nModel response:\n{response}")
        print(f"\nTokens used: prompt={usage['prompt_tokens']}, completion={usage['completion_tokens']}, total={usage['total_tokens']}")

        selected = parse_frame_numbers(response)
        print(f"\nSelected frames: {selected}")

        saved = save_selected_frames(tmpdir, frames, selected, args.output)
        print(f"\nSaved {len(saved)} frames to {args.output}/:")
        for path in saved:
            print(f"  {path}")


if __name__ == "__main__":
    main()
