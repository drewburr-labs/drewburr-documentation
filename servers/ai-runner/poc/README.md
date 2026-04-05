# AI Backend — Proof of Concept

POC scripts validating the ai-runner stack for use as a website backend.

---

## video_to_image.py

Demonstrates the "video to image" workflow: given a food/recipe video, the AI selects the
best frames for use on a recipe blog page and saves them to disk.

### Why this approach

The AI model (Qwen3-VL) is a vision-language model — it analyzes images and video and
outputs text. It cannot generate or output image files. "Video to image" therefore works
as a two-step pipeline:

1. **ffmpeg** samples the video into numbered frames (programmatic, no AI)
2. **Qwen3-VL** analyzes all frames and identifies which are visually best (AI reasoning)
3. **The script** copies the selected frames to an output directory (programmatic)

This is the correct architecture. Asking the AI model to "return frames" is not possible —
it can only describe, identify, and reason about images.

### Token budget

Frames are scaled to 720p before sending. At this resolution, each frame costs roughly
900 tokens. For the test video (8 minutes, 16 frames at 1/30s):

| | Tokens |
|---|---|
| 16 frames @ ~900 tokens | ~14,400 |
| Prompt text | ~200 |
| Model response | ~200 |
| **Total** | **~14,800** |

Well within the 32,768 token context window. For longer videos, increase `--interval`
to sample fewer frames.

### Live test results

**Input:** `I-Grew-My-Own-Food-Without-a-Garden` (YouTube, 8 min 1080p, 139MB)

**Command:**
```sh
python3 video_to_image.py video.mp4 --output ./output_frames
```

**Model selected frames:**

| Frame | Timestamp | Description |
|---|---|---|
| 5 | 2m00s | Hands cutting open a mushroom grow kit bag — preparation step |
| 7 | 3m00s | Glass jar with grain spawn and visible mycelium — cultivation process |
| 10 | 4m30s | Chia seeds being poured into a blender — ingredient action shot |
| 15 | 7m00s | Finished stir-fried mushroom dish in a bowl — hero/final dish shot |

**Tokens used:** 14,549 prompt + completion (out of 32,768 available)

**Output files:**
```
output_frames/
  selected_frame_05.jpg
  selected_frame_07.jpg
  selected_frame_10.jpg
  selected_frame_15.jpg
```

### Usage

```sh
# Basic usage
python3 video_to_image.py /path/to/video.mp4

# Custom output directory and sampling interval
python3 video_to_image.py /path/to/video.mp4 --output ./my_frames --interval 20
```

**Arguments:**

| Argument | Default | Description |
|---|---|---|
| `video` | required | Path to input video file |
| `--output` | `./output_frames` | Directory to save selected frames |
| `--interval` | `30` | Seconds between sampled frames |

### Production notes

For a website backend, this script represents the core logic. In production:

- Run asynchronously — a full pipeline (frame extraction + model inference) takes 30–60s
- Queue video jobs separately from image jobs (video ties up more of the KV cache)
- The `--interval` flag is the primary knob for quality vs. token cost trade-off:
  - Lower interval = more frames = better coverage = more tokens = slower
  - 30s is reasonable for cooking videos where scenes change slowly
  - 10s may be better for fast-cut content like TikTok

### Requirements

- `ffmpeg` installed on the machine running the script
- AI backend running (LiteLLM on `192.168.4.56:8000`)
- Python 3.6+ (stdlib only, no pip dependencies)
