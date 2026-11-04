"""Import Srishti Episode 2 (approved by the owner on 2026-11-04) with everything already made for it:
  locked references: Tara and Dadi sheets (Episode 1 picks), Brahma sheet (the Episode 1 Tridev sheet)
  to pick:           Manu x2, Shatarupa x2, night living room x2 (made on 2026-11-03), 4 voice takes per line (scored)
  2.4-L1 is regenerated straight away: its takes say "shat-rupa"; the lexicon now has शत-रूपा.
Files are read from s3://BUCKET/platform/import/ep2/ (uploaded by deploy.sh). usage: python import_ep2.py"""
import json, os
import boto3
import db, engine
from db import J, event, ex, one

BUCKET = os.environ.get("VREA_BUCKET", "vrea-686112930191-us-east-1")
PRE = "platform/import/ep2/"


def main():
    db.init()
    s3 = boto3.client("s3", region_name=os.environ.get("VREA_REGION", "us-east-1"))
    sb = json.loads(s3.get_object(Bucket=BUCKET, Key=PRE + "storyboard.json")["Body"].read())
    if one("SELECT id FROM projects WHERE title=%s", "Srishti Ep2 · Pehla Jeevan"):
        print("already imported"); return
    p = one("INSERT INTO projects (title, storyboard) VALUES (%s,%s) RETURNING id", "Srishti Ep2 · Pehla Jeevan", J(sb))
    pid = p["id"]
    engine.build_slots(pid, sb, locked={"tara": PRE + "refs/tara_sheet.png", "dadi": PRE + "refs/dadi_sheet.png",
                                        "brahma": PRE + "refs/brahma_sheet.png"}, script_approved=True)
    for name, files in {"manu": ["manu_v1.png", "manu_v2.png"], "shatarupa": ["shatarupa_v1.png", "shatarupa_v2.png"],
                        "living_room_night": ["night_master_v1.png", "night_master_v2.png"]}.items():
        for i, f in enumerate(files):
            ex("INSERT INTO assets (project_id, slot_key, kind, s3_key, meta, scores) VALUES (%s,%s,'image',%s,%s,%s)",
               pid, f"ref:{name}", PRE + "sheets/" + f, J({"variant": i + 1, "made": "2026-11-03"}), J({"rank": -i}))
        ex("UPDATE slots SET state='review' WHERE project_id=%s AND key=%s", pid, f"ref:{name}")
    scores = json.loads(s3.get_object(Bucket=BUCKET, Key=PRE + "voices/voice_scores.json")["Body"].read())
    for r in scores:
        rank = -(r.get("n_issues") or 0) * 10 - (r.get("cer") or 0) * 10 + (r.get("spk_sim") or 0)
        keep = {k: r.get(k) for k in ("n_issues", "cer", "spk_sim", "pace_ok", "f0_std_st", "transcript", "issues")}
        ex("INSERT INTO assets (project_id, slot_key, kind, s3_key, meta, scores) VALUES (%s,%s,'audio',%s,%s,%s)",
           pid, f"voice:{r['line']}", PRE + "voices/" + r["take"], J({"take": r["take"], "made": "2026-11-03"}), J({**keep, "rank": round(rank, 3)}))
    ex("UPDATE slots SET state='review' WHERE project_id=%s AND kind='voice'", pid)
    event(pid, "Episode 2 imported: storyboard approved; Tara, Dadi and Brahma locked; sheets and voice takes from 2026-11-03 waiting for your pick")
    engine.regenerate(pid, "voice:2.4-L1", "lexicon fix: शतरूपा is now voiced as शत-रूपा (keep the medial 'a')")
    print("imported project", pid)
    db.pool.close()


if __name__ == "__main__":
    main()
