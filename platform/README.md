# vrea platform

A hosted web app that takes a story through the whole pipeline. You approve the script, then pick variants at each
review point, and the platform renders the episode. It starts and stops the GPU machines on its own and enforces a hard
spending cap per story ($14 by default). Design: [`docs/orchestration-platform.md`](../docs/orchestration-platform.md).

## Using it

1. **New story:** either paste a story and let Claude draft the storyboard (needs an Anthropic API key in Settings), or
   paste a storyboard JSON in the same format as `stories/srishti-ep2/storyboard.json`.
2. **Approve the storyboard.** Nothing is generated before this.
3. **Pick at each review point.** These are the only required ones; the optional video-shot review is skipped.
   - **Designs:** pick a sheet for each character and set.
   - **Voices:** pick a take for each line, ranked by ASR errors and voice match.
   - **Keyframes:** pick one for each shot, before any video is spent.
   - **Final episode:** approve it, with its QA report.
4. Anything not right: **Regenerate** with a note. The note is added to the prompt, and everything built on that step
   is redone.

The board refreshes every 4 s and shows each step's state, the GPU machine, queued work and spend against the cap.

## How it runs

| Piece | Where | What |
|---|---|---|
| Web app + engine + autoscaler | `server/app.py`, `engine.py`, `scaler.py` | One process on a t4g.small. Postgres is on the same machine, local only. Caddy serves HTTPS on 80/443. |
| CPU assembly | `server/assemble.py` | Clips (voice-driven timing, 2-line captions, labels) and the episode (dissolves, end card, −14 LUFS, QA) |
| GPU worker | `worker/worker.py` | On each GPU machine: pulls tasks for the model families already loaded; voice takes run alongside image jobs |
| Storyboard drafting | `server/drafting.py` | Claude Opus 5.5, structured JSON, validated before it reaches you |

**Spending cap, three layers:**
1. No launch unless at least 15 min of budget is left.
2. Every GPU machine gets a power-off timer equal to what the remaining budget buys, so it terminates even if the
   server dies.
3. The server terminates the machine when spend reaches the cap.

**GPU machines:**
- They load only the model families that queued work needs, staged in order.
- One machine at a time (account quota). It stays warm for up to 15 min while your review would unlock more GPU work;
  otherwise it stops after 3 idle minutes.

## Deploy / update

```bash
platform/deploy/deploy.sh          # first time: IAM role, security group (80/443), Elastic IP, server; prints URL + password
platform/deploy/deploy.sh update   # push new code and restart
```

The server's IAM role can only:
- read and write the project bucket;
- launch instances tagged `project=vrea-platform`, and terminate only those;
- pass the `vrea-ec2` GPU role.

## Test locally (no GPU)

```bash
VREA_DSN=postgresql://vrea:vrea@127.0.0.1/vrea VREA_NO_SCALER=1 python3 -m uvicorn app:app --port 8001   # in server/
python3 tests/e2e_local.py http://127.0.0.1:8001 <password> <project_id>
```

The test uses a real Postgres, real S3 and real ffmpeg assembly, with a simulated GPU worker speaking the real worker
API. It picks the top variant at every review point through the web pages, through to the approved episode.
