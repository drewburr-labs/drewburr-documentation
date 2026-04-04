# Model Strategy

Guidance on model selection and usage for the ai-runner machine.

## Hardware

- **2x NVIDIA RTX 3090** — 24GB VRAM each, 48GB total
- Connected via **NVLink** (4 links × 14 GB/s = ~56 GB/s bidirectional) — the two GPUs are treated as a unified 48GB memory pool by CUDA
- Models are served via **Ollama** and accessible to other servers on the network

NVLink requires no server-side configuration — the driver detects it automatically. To verify it's active:

```sh
nvidia-smi nvlink --status -i 0
nvidia-smi nvlink --status -i 1
```

Both GPUs should show 4 links at 14.062 GB/s each.

## Use Cases

### General LLM Tasks

Text generation, summarization, Q&A, code assistance, etc. from other servers on the network.

### Image-to-Text

Converting images containing text to machine-readable content. Primary targets:

- Handwritten notes
- Recipe cards
- Other document scans

Requires a **vision-capable model**.

## Model Selection

### Vision (Image-to-Text)

| Model                 | VRAM  | Notes                                                                      |
| --------------------- | ----- | -------------------------------------------------------------------------- |
| `llama3.2-vision:11b` | ~8GB  | Fast, fits on one GPU, good for clean handwriting and structured documents |
| `llama3.2-vision:90b` | ~45GB | Spans both GPUs, best quality for messy or complex handwriting             |

Start with `llama3.2-vision:11b`. Pull `90b` if quality is insufficient for the use case.

### General Text

| Model          | VRAM  | Notes                                 |
| -------------- | ----- | ------------------------------------- |
| `llama3.1:8b`  | ~5GB  | Fast responses, good for simple tasks |
| `llama3.3:70b` | ~40GB | High quality, fits across both GPUs   |

## VRAM Budget

With 48GB total, the general approach is:

- Keep a vision model loaded for image tasks
- Keep a text model loaded for general tasks
- The 11b vision + 70b text combo fits comfortably (~45GB combined)

If running the 90b vision model, unload other models first.
