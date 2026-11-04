# Using the GPU box fully

Context: you noticed that the GPU box was not being used to its full capacity. This document covers what the runs
show, what is now implemented, and what comes next. Implemented items are marked **done**.

## 1. What we observed (2026-11-03 run, g6e.xlarge: 1× L40S 48 GB, 4 vCPU, 32 GB RAM)

| Symptom | Evidence | Cause |
|---|---|---|
| About 12 min of paid idle GPU at every boot | Launched 21:46, ready 21:58 | Every boot restored the env and copied **all ~122 GB** of weights before any job could start. Scenes 3/4 needed about 84 GB of that; the talking-head family (about 22 GB more) was never used. |
| The same job is fast alone and slow in parallel | 480×832 video shots: **30 s each** back to back (1.4-C/D/E); **60–222 s** while alternating with image-edit jobs (1.3-D/E/F, 1.4-A). Image jobs: 12–18 s alone, 135–309 s while queued. | Streams posted straight into ComfyUI's first-come queue. Image-edit (Qwen, ~29 GB in VRAM) and video (Wan 2.2, ~35 GB) alternated on a 48 GB GPU, so each alternation evicted one model family and reloaded the other. (These times include queue wait, which is why telemetry is now logged; see §2.) |
| GPU idle while CPU-side work ran | Voice env restore (10.5 GB), ffmpeg assembly and scoring ran on 4 vCPUs on the GPU box | Small instance for the CPU part; no overlap planning |
| Long waits for a box | 85 min of "no capacity" before a box started | One region and one instance type; quota is 8 vCPU (one box) |

## 2. Implemented now

| What | How | Where |
|---|---|---|
| **done:** Load only the models a session needs | `models.json` lists the weight files per family: `image`, `edit`, `video`, `talk`, `upscale`. `MODELS=fam:image,edit,video ./launch_gpu.sh` copies only those families. A file shared by two families (text encoder, VAE) is copied once. | `infra/quicktest/models.json`, `model_plan.py`, `launch_gpu.sh`, `gpu_bootstrap.sh` |
| **done:** Start working before all weights land | Families are copied in the given order by a background service. Each is marked in `/mnt/nvme/models.ready/<family>` when it lands, so the first family's jobs start right away. For scenes 3/4 the first family (image, about 29 GB) is ready after about a third of the old copy. | `gpu_bootstrap.sh` (vrea-models service) |
| **done:** Stop the model thrash | `gpu_dispatch.py` owns the GPU queue. It always runs the next job of the **family already loaded**, and switches family only when nothing of that family is waiting, or when a job has waited more than 15 min (no starvation). It skips families whose weights haven't landed. Streams keep calling `comfy.run()` unchanged. Replaying the interleaved shape of the last run: **13 model switches with the old queue, 1 with the dispatcher.** | `video/gpu_dispatch.py`, `video/comfy.py`, `video/test_gpu_dispatch.py` |
| **done:** Measure, don't guess | The box logs GPU utilization, VRAM and power every 5 s (`gpu.csv`) and every job's family, wait, run time and whether it switched model (`gpu_jobs.jsonl`). Both are synced to `s3://BUCKET/logs/<instance>/`. `util_report.py` gives busy %, time to first job, idle gaps, switches and per-family times. | `gpu_bootstrap.sh` (vrea-gpustat), `video/util_report.py` |
| **done:** Session template | Starts the dispatcher, runs all streams in parallel, then writes the utilization report | `video/run_template.sh` |
| **done:** CPU work off the GPU box | Re-assembly, the episode stitch and the consistency test now run on a CPU machine (this time, the dev machine at no AWS cost) | `rebuild34.py`, `episode.py`, `ep_consistency.py` |

## 3. Next steps, in order of payoff

1. **Work in phases that match the model families.** Render all keyframes (edit/image) for every scene, review them,
   then render all videos, then talking heads. This batches by family naturally and lines up with the platform's
   review gates. The dispatcher still handles any overlap.
2. **Render variants in one pass.** Generate 2–4 variants of a sheet or keyframe as one batched latent in a single
   graph, instead of N separate jobs. That's one model pass and better GPU occupancy.
3. **Draft, then final.** Review video at 480p with the 4-step LoRA; render only approved shots at the final setting,
   then run Real-ESRGAN and RIFE (frame interpolation) on approved shots only.
4. **More RAM per GPU.** Prefer g6e.2xlarge (64 GB RAM, 8 vCPU) over g6e.xlarge (32 GB, 4 vCPU). It fits the same
   8-vCPU quota and leaves room to keep a swapped-out model family in system RAM instead of re-reading it from disk.
   Exactly how ComfyUI's model cache behaves with more RAM is to be confirmed with the new telemetry.
5. **True parallelism needs more GPUs.** One L40S runs one diffusion job at a time efficiently; two big model
   families can't share 48 GB. Running one box per family or per scene in parallel costs roughly the same in
   total (plus each box's boot) and finishes about N× sooner.
   - Needs the G-instance vCPU quota raised from 8 to 32–48. The requests for us-east-2 and us-west-2 are open.
   - A g6e.12xlarge (4× L40S) is the single-box form.
   - The platform's autoscaler (see the platform plan) assigns families to boxes.
6. **Fewer capacity waits.** Launch across regions and AZs (once quotas allow), with a fallback type list
   (g6e.2xlarge → g6e.xlarge), and keep the box warm between phases while a review is pending (idle timeout set to
   the expected review time) instead of terminating and waiting for capacity again.
7. **Faster boot.** Bake the ComfyUI env (4.3 GB) into a custom AMI: about 2–3 min saved per boot for a few cents a
   month of snapshot storage. Weights stay on S3→NVMe, which the earlier analysis showed beats keeping an EBS volume.

## 4. How to use it on the next run

```bash
MODELS=fam:edit,image,video TYPE=g6e.2xlarge MARKET=ondemand IDLE_MIN=30 MAX_HOURS=2 \
  BUCKET=vrea-686112930191-us-east-1 REGION=us-east-1 infra/quicktest/launch_gpu.sh
```

Then run the session from `video/run_template.sh`. Afterwards:

```bash
aws s3 sync s3://vrea-686112930191-us-east-1/logs/<instance-id>/ ./logs/ && python3 infra/quicktest/video/util_report.py ./logs
```

That gives the measured busy %, time to first job, idle gaps and model switches. Those numbers are the baseline for
judging every further optimization.
