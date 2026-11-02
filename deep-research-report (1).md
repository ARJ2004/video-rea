# Executive Summary  
Generating short-form videos (Reels/Stories) via AI requires integrating multiple specialized models (text-to-video, audio, editing, upscaling, etc.) under a high-throughput, low-latency orchestration. In practice, products like Google Flow (formerly VideoFX) and HiggsField combine state-of-the-art generative models (e.g. DeepMind’s *Veo* video model in Google Flow) with an agentic pipeline to iterate and post-process clips. We propose a microservices/workflow architecture that ingests user prompts, routes to appropriate models (text→video, audio, interpolation, style transfer, upscaling, etc.), applies safety filtering (e.g. AWS Rekognition moderation), and stitches together final videos. Feasible model/service candidates include Google Flow/Veo, Vertex AI (Imagen), AWS Bedrock/SageMaker (Stable Diffusion, Titan models), RunwayML Gen-3/4, OpenAI Sora, Meta’s Make-A-Video, Nvidia’s VideoLDM, and open-source LDM-based video diffusion. Table 1 (below) compares these on quality, latency, cost, licensing and maturity. For MVP we recommend cloud APIs (e.g. Runway or SageMaker-hosted Stable Diffusion) orchestrated via serverless workflows (GCP Workflows/AWS Step Functions) to generate 5–15 s reels at ~720p. For production, a hybrid GPU cluster (GCP or AWS) with autoscaling, caching and fine-tuned models (with watermarks like SynthID) can achieve 15–30 s clips. 

**Key findings:** Google Flow’s VideoFX uses DeepMind’s *Veo* model for cinematic text-to-video conversion, while HiggsField appears to wrap multiple best-in-class video engines (Runway’s Kling, Seedance, etc.) into a single UI. Modern text-to-video models (Imagen Video, Make-A-Video, Runway Gen-4.5, Sora) either cascade diffusion or use transformers to balance spatial and temporal fidelity. Orchestration must thus handle multi-step pipelines (cascaded upscaling, frame interpolation for temporal consistency, audio generation and lip-sync, etc.), with trade-offs between latency and cost. Cloud deployments can leverage managed services (Vertex AI, Bedrock, Cloud Run/Lambda, SageMaker, EKS) but careful cost/throughput analysis is needed. Safety (filtering objectionable content) and IP (watermarking) are critical – Google already watermarks AI-generated content via SynthID. Evaluation will rely on video-specific metrics (FVD, temporal coherence tests) and user engagement signals. A continuous integration pipeline for models (using SageMaker Pipelines or Vertex Pipelines) will ensure quality and reproducibility.  

**Figure 1** below shows a proposed end-to-end orchestration flow. **Table 1** compares candidate models/services. We also include (2) recommended MVP vs production stack, (3) a reverse-engineering checklist (with experiments and public datasets like MSR-VTT, HowTo100M, WebVid), and (4) estimated prototype vs production costs (GPUs, storage, bandwidth). All claims are supported by recent sources.

## System Architecture (HiggsField & Google Flow)  
HiggsField and Google Flow embody *agentic orchestration* over multiple AI models. Google Flow (formerly VideoFX) uses DeepMind’s “Veo” text-to-video model as its core, and supports scene-by-scene storyboarding and music addition. Google’s blog notes: *“VideoFX is powered by Veo, Google DeepMind’s new and most capable video generation model… captures emotional nuance and produces cinematic effects.”*. Google also embeds SynthID watermarking into all Flow-generated content, highlighting IP/safety focus. HiggsField (AI Short Video Generator) offers multiple “skills” (e.g. “Shorts Maker”, “AI Clipper”) that likely wrap different specialized models (named “Kling”, “Seedance”, “Wan”, etc.) for video+audio generation. Runway’s docs confirm similar components: e.g. *“Runway Dev lets you bring video, image and audio models … including Kling, Seedance…”*. HiggsField also includes upscaling and editing tools. Thus, both platforms are multi-service pipelines: user input is dispatched via a workflow engine to model endpoints, then combined into final clips. 

**Architectural pattern:** A microservices-based or serverless workflow is apt. Each model (text2video, upscaler, audio gen, style transfer, face tracking, etc.) is a service; an orchestrator (AWS Step Functions or GCP Workflows) sequences them, with caching/routing logic. This aligns with cloud-native design: “Microservices … independent services that make up a larger application”, enabling independent scaling. Models can be deployed as containerized endpoints (Vertex AI endpoints, SageMaker endpoints) or serverless functions calling APIs. Autoscaling GPUs (e.g. via Amazon EC2/GPU Spot or GCP GPU instances) handles bursty loads. Batching requests can improve GPU utilization for throughput (at cost of some latency). Caching prompt-to-output mappings or partial results (e.g. reusing an audio track) further balances cost/latency. 

**Model pipeline components:** Based on state-of-art research, a short-video pipeline typically includes:  
- **Text encoder:** Tokenize prompt via a large encoder (T5/GPT) for conditioning, as in Imagen Video.  
- **Base Video Generator:** A diffusion model or transformer (e.g. Veo, Gen-4/5, Make-A-Video, Sora) that outputs a low-res video (e.g. 16 frames at 160×96).  
- **Frame Interpolation/Temporal Up-scaling:** Models like RIFE (CVPR 2020) to increase fps and smooth motion between diffusion steps.  
- **Spatial Super-Resolution:** Cascaded diffusion or CNN upscalers (as in Imagen Video’s multi-stage SSR).  
- **Audio Generation/Synchronization:** A text-to-audio or speech model (e.g. AudioGen, MusicGen) triggered by subtitles or related prompt; or Wav2Lip to sync generated speech to mouth movements in video. HiggsField’s “Wan/Seedance/Kling” suggest integrated audio; Runway’s “veo3.1_fast (audio)” model hints at video+audio together.  
- **Editing/Styling:** Optional tools like style-transfer, text overlays, or character insertion (face/body tracking to impose a user face or style transfer filter).  
- **Post-processing:** Color correction, watermarking (SynthID), formatting (vertical vs square), and packaging (concatenate clips into a final reel).  

To manage this, the orchestrator workflow might route a prompt through a “video generation” branch or an “image → video” branch, then through quality-ensuring tasks. For example: 
```mermaid
flowchart LR
  A[User Prompt & Assets] -->|filter content| B[Moderation Filter]
  B --> C{Type?}
  C -->|Text-to-Video| D[Base Video Model]
  C -->|Image-to-Video| E[Image-conditioned Video Model]
  D & E --> F[Temporal Upscaling (Interpolation)]
  F --> G[Spatial Upscaling / SuperRes]
  G --> H{Audio?}
  H -->|Generate| I[Audio Model]
  H -->|None| J[Skip Audio]
  I & J --> K[Merge Audio + Video]
  K --> L[Post-Edit (Style, Captions)]
  L --> M[Output Storage & Delivery]
```  
*Figure 1: Proposed orchestration pipeline (text-to-video path shown).*  

## Candidate Models & Services  

| Model/Service            | Quality (Accuracy)                | Latency | Cost (per clip)          | Licensing          | Maturity/Deployment                                                                                |
|--------------------------|----------------------------------|---------|--------------------------|--------------------|---------------------------------------------------------------------------------------------------|
| **Google Flow (Veo)**    | High (cinematic, multi-style) | ~10–30s per 5s (GPU) | TBD (proprietary)  | Proprietary (Google Labs) | Experimental (preview); no public API; uses SynthID watermark.                  |
| **Vertex AI (Imagen?)**  | Very high (HD, 3D-aware) | ~seconds (GPU cluster) | Very high (custom TPU) | Restricted (not released) | Research (Imagen Video paper); no public API. Google Cloud has Imagen 2 for images but no public video model yet. |
| **AWS Bedrock (SD)**     | Good (up to 768p); depends on model | ~10–30s per 5s | Low (~$0.50 for 5s of SD) | SD: CC BY-NC; Bedrock: pay-per-use | Beta (Stable Diffusion, Titan Models); SageMaker offers SD via JumpStart. Bedrock currently image-focused. |
| **Runway Gen-4.5**       | High (creative, stable)         | ~10–20s per 5s | $0.25–0.75 per 5s | Proprietary (SDK/API) | Production-ready; API supports text/image→video (Runway SDK). Good for prototyping.    |
| **Runway Gen-4.5 Turbo** | Lower quality (faster, image→video only) | <10s | $0.25 per 5s | Proprietary         | Fast variant; needs image prompt.                                                                     |
| **OpenAI Sora**         | Very high (long scenes, complex logic) | Unknown (likely fast) | TBD (closed)         | Proprietary         | Closed Alpha; transformer-based (video tokens); strongest on complex prompts; likely highest cost. |
| **Meta Make-A-Video**   | Good (vivid, coherent)  | ~tens of seconds | N/A (no service)     | Research-only       | Research (CVPR 2022); not publicly released (demo only). Trained on unpaired image/video. |
| **Imagen Video**        | Very high (HD 1280×768, 24fps) | ~minutes (cascade) | Research use only  | Proprietary (no release) | Research (Google Brain, 2022); not released due to safety/bias concerns.             |
| **Nvidia VideoLDM**     | High (driving, generic scenes) | ~30–60s (fine-tuning + denoise) | Free (open code)  | MIT (Source code)   | Research (CVPR 2023); code published; uses Stable Diffusion base (open weights).       |
| **Stable Diffusion + RIFE** | Medium (720p clips)         | ~10–30s       | ~\$0.10–0.50 (GPU) | CC BY-NC; MIT (RIFE) | Community implementations (e.g. StableVideoDiffusion). Less polished; needs chaining (diffusion + interpolation). |
| **VQGAN+CLIP**          | Low (blurry, slow, artistic)  | Minutes       | Low (CPU/GPU)       | Depends on variants | Legacy method (2020); not competitive for production; any open implementation.                       |

*Table 1: Comparison of candidate text-to-video models/services.* Citations indicate model claims. Costs are rough; e.g. Runway’s pricing lists 12 credits/sec for Gen-4.5 (~$0.60 per 5s clip) and 40 credits/sec for Veo3. “Latency” assumes modern GPUs (A100/V100). 

## Orchestration & Data Pipeline  
**Orchestration patterns:** The pipeline should use a **workflow engine** (e.g. AWS Step Functions or GCP Workflows) to coordinate steps, and services or containers for each model. A microservices design fits: each step (tokenization, base generation, upscaling, audio, moderation, etc.) is a stateless service. This allows independent scaling: e.g. spin up extra pods for video diffusion when demand spikes. Batch-processing (multiple prompts in one GPU job) and caching (memoize repeated prompts or identical sub-prompts) can reduce costs. Serverless functions (Cloud Functions/Lambda) can handle lightweight tasks (prompt filtering, metadata storage). Latency vs cost trade-off is key: ultra-low latency (<5s for a 5s clip) would require large GPU fleets (very high cost), whereas batched/async generation (10–30s latency) can reduce compute idle time. 

**Data pipeline:**  
- **Ingestion:** Accept user inputs via API (text prompt, reference images, video, style instructions). Store raw inputs and metadata (userID, prompt, timestamp) in a database.  
- **Preprocessing:** Sanitize and tokenize text (BPE or CLIP tokenizer). Perform any requested image/video analysis (e.g. frame sampling). If re-using a user’s face/body, run a face recognition/pose model to extract landmarks.  
- **Safety filters (content moderation):** Early filter of prompts with banned content (hate, adult, illegal). After generation, run automatic **video/image moderation** (e.g. AWS Rekognition “Content moderation” or Google Cloud Video AI) on outputs to detect nudity, violence, hate symbols. (Google’s Imagen Video team also notes filtering inputs/outputs to avoid hate/explicit content.) Low-confidence outputs may be rejected or flagged for review.  
- **Tokenization & Prompt Expansion:** Use an LLM (e.g. PaLM or Gemini via Vertex AI) to refine or expand the prompt, if needed (e.g. automatically add context or keywords). HiggsField’s “AI Clipper” suggests an agent analyzes input videos and writes scene descriptions.  
- **Logging & Monitoring:** Log all model calls, latencies, and outcomes. Collect user feedback as a quality signal. Implement health checks for each service.  
- **Storage:** Store generated videos (and intermediate results if auditing) in scalable object storage (GCP Cloud Storage or AWS S3) with appropriate access control. Metadata (tags, prompt, model used) in a database (BigQuery/DynamoDB).  

Integration of Google Flow model (Veo) in a third-party pipeline isn’t public; if Google exposes a “Flow API” or Notebook (the Labs site mentions a Gemini Notebook), it could be invoked as a service. More likely, a clone would use existing diffusion models.

## Deployment (GCP/AWS Integration)  
**MVP Stack:** For a minimal viable product, one could avoid complex infra by using managed services:  
- **Model hosting:** Use RunwayML API or SageMaker JumpStart images (Stable Diffusion) for video generation. These provide HTTP endpoints, so orchestration is simpler (just REST calls). Runway’s Dev API supports text→video (gen4.5, Veo 3.1) out-of-the-box. Alternatively, use Vertex AI **Matching Engine** or **Endpoint** for custom models (e.g. deploy VideoLDM checkpoint).  
- **Compute:** Cloud Run or AWS Fargate containers running the orchestration logic; invoke GPU-based endpoints. Lightweight functions (Cloud Functions/Lambda) handle filtering.  
- **Orchestration:** AWS Step Functions or GCP Workflows to coordinate steps. Example: an AWS Step Functions state machine can sequentially call Lambdas (for text), SageMaker endpoints (for video), Rekognition (for moderation), and Glue/Athena (for tagging).  
- **Storage:** S3/Cloud Storage for outputs; use built-in CDN (CloudFront, Cloud CDN) for delivery.  

This MVP can be built quickly and costs scale with usage. For short videos (5–15s at 720p), a single GPU instance (V100/A10) can suffice. Throughput targets (e.g. 10 clips/minute) can be met with a few GPUs in parallel.

**Production Stack:** For scale and efficiency, a more robust architecture is needed:  
- **On-demand GPU cluster:** Use Kubernetes with GPU nodes (AWS EKS or GCP GKE Autopilot) so pods can be scheduled where GPUs are idle. Kubernetes Operators (like Kubeflow) can manage model deployments. Use Spot instances to cut cost, with fallback to on-demand for critical bursts.  
- **Model Routing & Caching:** Deploy multiple model variants (fast vs high-quality) and route based on use case. For example, a “fast” path uses smaller diffusion/turbo models, and a “quality” path uses larger ones. Cache recent results (Redis) for deduplication.  
- **Autoscaling:** Enable cluster autoscaling. For AWS, use EC2 Auto Scaling Groups with Spot fleets, and Lambda/Instance warm pools to reduce cold-starts. Use Karpenter (on AWS) or GCP’s node auto-provisioning.  
- **Vertex AI and Bedrock integration:** On GCP, Vertex AI now offers **Generative AI Model** service (PaLM, Imagen) via API (Chat API, Vision API). You could use Vertex AI for text processing (PaLM for prompt writing) and Vision (Imagen API for reference image prompts). On AWS, use **Amazon Bedrock** to access models like StabilityAI’s models (if available) or Amazon’s Titan text for prompt re-writing. However, as of 2026 Bedrock’s video support is minimal, so most work is custom.  
- **Cost optimization:** Batch requests for image-to-video pipelines; use dynamic quantization or Triton Inference Server for faster throughput. Consider NVIDIA TensorRT (as in stable diffusion on AWS) for speed.  
- **CI/CD for models:** Use SageMaker Pipelines or Vertex AI Pipelines to automate training/fine-tuning and validation. Version all models and data. Deploy models via infrastructure-as-code (Terraform) to ensure reproducibility.

## Monitoring & Evaluation  
**Quality metrics:** Traditional image metrics (FID, IS) extend poorly to video. Use **Fréchet Video Distance (FVD)** which Unterthiner et al. proposed to capture spatial and temporal realism in generated videos. Human judgment studies show FVD correlates with perceived quality and coherence. Other metrics include Video Inception Score or mutual information between frames. Also measure *temporal consistency* (e.g., character identity persistence) via embeddings or IoU of tracked objects. Track user engagement (views, likes) as a proxy.  
**Performance monitoring:** Log per-step latencies and GPU utilization. Track SLA (e.g. p95 generation time) vs budget. Auto-notify on model failures or moderation flags. Use A/B testing: compare model versions by FVD or by small human ratings.  
**CI/CD:** Apply MLOps best-practices: containerize each model’s inference code, run unit tests on prompt-responses, and use pipelines (Vertex Pipelines/SageMaker Pipelines) to automate training and deployment when data or weights update. Maintain a staging environment for new model tests.

## Legal, IP and Safety Considerations  
- **Model licenses:** Many top models are not open-source. Imagen Video and Veo are Google-internal, Make-A-Video was research-only. Stable Diffusion’s weights are CC BY-NC (non-commercial) – unsuitable for a public product without license. Meta’s model uses CC BY-NC as well. OpenAI’s Sora is proprietary. Nvidia’s VideoLDM code is open-source (Apache/MIT). For any selected model, abide by its license (non-commercial vs research).  
- **Copyrighted content:** Models trained on web data can regurgitate copyrighted images. Avoid infringing by limiting resolution/length, or using watermarking. Google’s SynthID watermark is one solution; other proposals exist for “owner watermarks” and provenance. Implement DMCA-compliant workflows if users upload copyrighted content.  
- **Deepfake risks:** Short AI videos can easily become deepfakes. Implement face recognition to prevent unauthorized impersonation, unless the user explicitly consents (e.g. by uploading their own face). Add audible or visual watermarks. Follow emerging regulations (e.g. EU AI Act provisions on “high-risk AI” and requirement to label synthetic media). As [20] notes, Google is actively watermarking AI-generated media to enable traceability.  
- **Content moderation:** In addition to technical filters, enforce terms of use. Rate-limit or human-review prompts that edge filters. Provide users a way to report misuse.  

## MVP vs Production Recommendations  

- **MVP:** Use off-the-shelf APIs and minimal infra. For example, call Runway’s Gen-4.5 (text→video) and Veo3 endpoints for base clips, then pass to an off-the-shelf face/pose model (MediaPipe) and RIFE interpolation (open-source) via Cloud Run. Use Cloud Functions for quick tasks (prompt transform) and AWS Rekognition to moderate outputs. Store clips in S3/Cloud Storage. This yields a working proof-of-concept quickly, costing roughly ~$0.50–2 per clip (Runway’s pricing) plus minimal server costs.  

- **Production:** Containerize all models and deploy on managed Kubernetes with autoscaling on GPU nodes (AWS EKS with EC2 Spot, or GKE Autopilot). Implement a workflow engine (Step Functions/Workflows) for orchestration. Use model replicas and versioning for A/B tests. Integrate Vertex AI for prompt engineering (PaLM2/Gemini), and SageMaker for custom model hosting. For example, a possible stack: Vertex PaLM for prompt refinement; Vertex Model garden to host a custom Imagen Video (if ever available) or VideoLDM; AWS SageMaker for Stable Diffusion super-resolution; AWS Rekognition/Content Moderation; AWS CloudFront CDN; monitoring via CloudWatch. Watermark with SynthID-like system.  

**Rationale:** The MVP leverages SaaS/API to avoid development cost, at higher per-clip cost. Prod uses open-source models on self-managed infra to lower marginal cost and increase control (at expense of ops complexity).  

## Reverse-Engineering Checklist (HiggsField & Flow)  

To replicate HiggsField/Flow features:  

1. **Identify core models:** Determine which video models are used. HiggsField mentions *“Wan, Seedance, Kling 2.6”* for video+audio; Runway’s SDK lists *“veo3.1, gen4.5, Kling, Seedance”*. Obtain similar models (e.g. open-source Stable Diffusion video pipelines, Meta’s Make-A-Video code, or commercial endpoints).  
2. **Reproduce video generation:** Set up text-to-video generation (e.g. use Imagen Video code from Google Research or an open GitHub like stable-video-diffusion). **Experiment:** Run on standard benchmarks (MSR-VTT, UCF-101 video captions) and measure FVD.  
3. **Frame interpolation:** Integrate RIFE or DAIN for smooth frame rates. **Experiment:** Compare 5s video at 24fps vs downsampled 12fps + RIFE upsample – test user preference.  
4. **Audio integration:** Implement a text-to-speech or music model. HiggsField’s “Wan” likely generates audio. Use Meta’s AudioGen or Google’s AudioLM. For syncing, use Wav2Lip to align speech with lip movements. **Experiment:** Generate videos with and without audio to test user retention.  
5. **Editing features:** Build “hook detection”: analyze longer videos with scene-detection (PySceneDetect) or audio peaks to identify viral-worthy 5s segments. Develop “shorts maker” that stitches a storyboard (series of shots) given multi-sentence prompts.  
6. **Quality improvement:** Add upscaling (e.g. ESRGAN or Real-ESRGAN) for HD output, similar to HiggsField’s “Upscale to 4K.”  
7. **Data:** Use public datasets for fine-tuning/evaluation: MSR-VTT, WebVid-10M (text+video), HowTo100M (unlabelled video), UCF-101 (action clips). For speaker modeling, LRS3 (audio-visual speech).  
8. **Agent and UI:** Replicate an “AI agent” that chains tasks: e.g. a GPT-based agent that takes a long prompt and breaks it into multi-shot instructions (“Scene 1: ...; Scene 2: ...”). HiggsField’s agent persona (“Shorts Creator”) suggests a multi-step prompt interface. Implement as multi-turn chat with a puppet LLM (e.g. OpenAI/Gemini).  
9. **Prompt engineering:** Experiment with prompt templates for different styles (e.g. `“[Scene description], cinematic, 24fps, trending on Instagram”`). Leverage chain-of-thought to refine prompts.  
10. **Evaluation:** Use the FVD metric on a hold-out test set, and run user A/B tests (e.g. best-of-3 comparisons between models). Collect engagement metrics if possible.  
11. **Iterate:** Fine-tune or replace underperforming models. For example, use DreamBooth or Low-Rank Adaptation to personalize characters.  

## Cost & Resource Estimates  

We consider two scenarios: **Prototype** (limited use) vs **Production** (high throughput). Assume a 10-second 720×1280 video generation.  

- **Compute (per clip):** A modern GPU (NVIDIA A100 40GB) costs ~$2–4/hour on cloud. If one generation takes ~20s (including base + upscaling), that’s ~0.005–0.011 GPU-hours = ~$0.01–$0.04 compute time per clip. In practice, cloud providers or APIs charge more: Runway’s Gen4.5 is ~$0.60 per 5s. So budget ~$0.50–1.50 per 10s clip (MVP). Production can amortize this: with 10 A100s ($30/hr total), you can produce ~1800 10s videos per hour if 20s each, or $0.016 per 10s (compute only).  

- **Storage:** Each 720p 10s clip (~24fps) is ~10–20 MB (H.264). At scale, 1M clips = ~15 TB. S3/Cloud Storage costs ~$0.023/GB-month ⇒ ~$345/mo for 15TB. Prototype store maybe 500 clips (~10 GB).  

- **Bandwidth (delivery):** ~0.5 MB/s per 720p video. 1M views of 10s = 10 M downloads = ~15 TB egress (CDN). At $0.08/GB ⇒ ~$1200.  

- **Development/Operations:** MVP uses pay-as-you-go; production might reserve capacity (e.g. AWS Savings Plans for GPU). Factor in database (DynamoDB $100s), orchestration (Lambda calls ~ $0.10 per 1M requests), and monitoring tools.  

**Example breakdown:**  
- *Prototype* (light usage): 1 GPU (Spot A100), Cloud Run/Functions, moderate storage/bandwidth. Monthly: GPUs ~$300, storage ~$50, bandwidth ~$100, misc ~$50 = **~$500–1000**/month.  
- *Production* (1000 clips/day): 10 GPUs (clusters, ~$3000/month), autoscaling cluster (~$1000), storage (~$500 for 50TB including backups), bandwidth (~$500), services (~$500) = **~$5500+/month**.  

Cost scales linearly with output length: e.g. 30s videos cost roughly 3×. If offering different quality tiers, premium “HD” pipeline (4K upscaling) could cost 5–10× more.

**Summary:** Even at scale (thousands of videos/day), a budget of a few thousand USD per month is plausible with careful resource use. Most cost is GPU/egress. Using cloud GPUs in “pod” instances (shared) or user GPUs (mobile device accelerators) could further reduce cost.

## References  
- Google’s VideoFX/Flow announcement: *“VideoFX is powered by Veo… captures emotional nuance…,”* with SynthID watermarking.  
- RunwayML dev docs on video models (gen4, Veo) and pricing.  
- Google Imagen Video (Text-to-video): cascaded diffusion, 5.3s HD output, withheld release for safety.  
- Meta Make-A-Video (text→video): public demo, trains on unpaired data.  
- Sora vs Runway analysis: Gen-3 (diffusion) vs Sora (transformer) strengths.  
- Nvidia VideoLDM (SD-based video diffusion): up to 1280×2048 video.  
- AWS Rekognition: Video/image content moderation feature.  
- M. Unterthiner *et al.* (NIPS 2019) – Fréchet Video Distance (FVD) metric for video quality.  
- vFunction blog – microservices architecture overview.

