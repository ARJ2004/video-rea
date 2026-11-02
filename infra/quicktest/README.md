# Quick test under $20: one finished reel (Clip 1.1)

Goal: answer the risky questions (consistent faces, Hindi voices, lip-sync, vertical quality) by producing **Clip 1.1 "Before Creation" (25 s, 9:16)** end to end, for **about $7–10 on Spot** (about $13–16 on-demand).

## How the "no cold download" setup works

```
 one time (~$0.10)                         every GPU session
┌────────────────────┐   stream    ┌──────────────┐  s5cmd, free same-region  ┌─────────────────────────────┐
│ Hugging Face / GH  │ ──────────▶ │  S3 bucket   │ ────────────────────────▶ │ g6e.2xlarge local NVMe disk │
└────────────────────┘ (seeder VM) │ models/ 114GB│   ~3–8 min for 114 GB     │ (free, fast, wiped at end)  │
                                   │ env/  (venv) │ ◀──── work synced every ── │ ComfyUI + your outputs      │
                                   │ work/ (yours)│        3 min + at exit     └─────────────────────────────┘
                                   └──────────────┘
```

- **Weights are downloaded from Hugging Face once**, by a cheap CPU instance, and kept in S3 (114 GB ≈ **$2.60/month**). GPU time is never spent downloading.
- Each GPU session copies them from S3 to the instance's **free local NVMe disk**. Transfer between S3 and EC2 in the same region costs nothing and takes a few minutes.
- This is cheaper than keeping a 300 GB EBS disk (~$24/month), which was the biggest line in the earlier estimate.
- The ComfyUI Python environment is built **once** and cached in S3 too (`env/comfyui-env.tar.zst`), so later boots skip all `pip install` steps.
- **What S3 can't remove:** each model still has to be loaded from disk into GPU memory when first used (~20–60 s per model). So work **in batches by model**: all keyframes, then all Wan shots, then all talking heads.
- **Nothing bills while you're away.** The instance terminates itself after 20 idle minutes or 3 hours (configurable), and your work is synced to `s3://BUCKET/work/` first.

## One-time setup (~15 min, ~$0.10)

Pick the region with the best g6e Spot price first (see `docs/mvp-plan.md` §5.3). The examples below use `us-east-2`.

1. Create the bucket and variables:

```bash
export REGION=us-east-2 BUCKET=vrea-$(aws sts get-caller-identity --query Account --output text)-$REGION
```

```bash
aws s3 mb s3://$BUCKET --region $REGION
```

2. Create the instance role (S3 access to this bucket + SSM login):

```bash
aws iam create-role --role-name vrea-ec2 --assume-role-policy-document '{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Principal":{"Service":"ec2.amazonaws.com"},"Action":"sts:AssumeRole"}]}'
```

```bash
aws iam attach-role-policy --role-name vrea-ec2 --policy-arn arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore
```

```bash
aws iam put-role-policy --role-name vrea-ec2 --policy-name vrea-s3 --policy-document "{\"Version\":\"2012-10-17\",\"Statement\":[{\"Effect\":\"Allow\",\"Action\":[\"s3:GetObject\",\"s3:PutObject\",\"s3:DeleteObject\",\"s3:ListBucket\"],\"Resource\":[\"arn:aws:s3:::$BUCKET\",\"arn:aws:s3:::$BUCKET/*\"]}]}"
```

```bash
aws iam create-instance-profile --instance-profile-name vrea-ec2 && aws iam add-role-to-instance-profile --instance-profile-name vrea-ec2 --role-name vrea-ec2
```

3. Set a budget alarm at $20 (replace the email address):

```bash
aws budgets create-budget --account-id $(aws sts get-caller-identity --query Account --output text) --budget '{"BudgetName":"vrea-quicktest","BudgetLimit":{"Amount":"20","Unit":"USD"},"TimeUnit":"MONTHLY","BudgetType":"COST"}' --notifications-with-subscribers '[{"Notification":{"NotificationType":"ACTUAL","ComparisonOperator":"GREATER_THAN","Threshold":50,"ThresholdType":"PERCENTAGE"},"Subscribers":[{"SubscriptionType":"EMAIL","Address":"you@example.com"}]}]'
```

4. Copy the models into S3 (the seeder instance terminates itself, ~30–60 min):

```bash
cd infra/quicktest && ./launch_seeder.sh
```

5. Check it finished (prints `ok`):

```bash
aws s3 cp s3://$BUCKET/_SEEDED -
```

You need a fresh GPU vCPU quota for the G family on Spot ("All G and VT Spot Instance Requests" ≥ 8 vCPUs). New accounts often start at 0, so request the increase in Service Quotas **now**; approval can take a day.

## Session 1: look, faces, voices (~2 h of GPU)

```bash
./launch_gpu.sh
```

Then follow the printed commands to open ComfyUI at `http://localhost:8188`. The first boot takes ~25 min (it builds and caches the environment); later boots take ~10 min.

1. **Character and set sheets** (Qwen-Image + Lightning 8-step, built-in ComfyUI template "Qwen-Image"). Generate 4 variants each of Tara, Dadi and the living-room plate, using the descriptions in `stories/srishti-ep1/storyboard.json`, and pick one of each.
2. **Keyframes for 1.1-A, B, C, D** (template "Qwen-Image-Edit 2509", feed the sheets as reference images 1–3). Generate 3 variants each at 720×1280 and pick one.
3. **Voices.** IndicF5 needs a 10–15 s reference recording per character plus its transcript. For this test, record yourself or a colleague on a phone, one clip for Tara and one for Dadi. It is a gated model, so accept its terms on Hugging Face, then on the box:

```bash
cd /mnt/nvme && /usr/local/bin/uv venv tts && /usr/local/bin/uv pip install --python tts/bin/python git+https://github.com/ai4bharat/IndicF5.git
```

   Generate the two lines (`tts` text in `storyboard.json`), following the usage example on the IndicF5 model card. Save them as `ComfyUI/input/1.1-L1.wav` and `1.1-L2.wav` so they sync to S3.

4. Terminate the instance (or just walk away; it stops itself after 20 idle minutes). Review the picks on your laptop from `s3://$BUCKET/work/output/`.

## Session 2: motion, lip-sync, finish (~2–2.5 h of GPU)

1. **1.1-A and 1.1-D** (template "Wan 2.2 14B Image to Video" with the 4-step LightX2V LoRAs): 480×832, 81 frames, 2 takes each.
2. **1.1-B and 1.1-C talking heads** (template "Wan InfiniteTalk"): keyframe + voice WAV, 480×832, 2 takes each.
3. **Upscale** the chosen takes to 1080×1920 (Real-ESRGAN), and **interpolate** 16 → 32 fps (RIFE in Frame-Interpolation, ~10 MB download on first use).
4. **1.1-E void**, which runs on CPU anywhere:

```bash
../../pipeline/comp/void.sh void.mp4 6
```

5. **Assemble** with FFmpeg: concatenate A → B → C → D → E, put the voice lines on their timings, add captions and an optional music bed.

## Expected cost

| Item | Spot | On-demand |
|---|---|---|
| Seeder (c7i-flex.large, ~1 h) | $0.10 | $0.10 |
| S3: 114 GB models + env + work, one month (delete after the test to stop it) | $2.70 | $2.70 |
| GPU g6e.2xlarge, ~4.5 h over 2 sessions (Spot price varies, about $0.9–1.2/h) | $4–5.50 | $10 |
| Root disk, data transfer, requests | <$0.30 | <$0.30 |
| **Total** | **≈ $7–9** | **≈ $13–14** |

Where the money can leak, and what guards it:
- Sitting in ComfyUI thinking: the idle watchdog terminates after 20 minutes. To work more slowly, set `IDLE_MIN=40`.
- A session running all night: hard cap with `MAX_HOURS=3`.
- Forgotten resources: everything is tagged `project=vrea`. When finished:

```bash
aws s3 rm s3://$BUCKET --recursive
```

## If Spot capacity is unavailable

Try another region or Availability Zone, or run with `MARKET=ondemand ./launch_gpu.sh`. On-demand roughly doubles the GPU line, and the total still stays under $15.
