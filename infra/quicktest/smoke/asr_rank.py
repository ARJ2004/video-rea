import json, sys
from collections import defaultdict
from dataclasses import asdict
from pathlib import Path
from vrea.pronounce.qa import indic_conformer_asr, score_take, rank
d = Path(sys.argv[1]); takes = json.load(open(d / "takes.json"))
asr = indic_conformer_asr(); by = defaultdict(list)
for t in takes:
    s = score_take(str(d / t["take"]), t["script"], *asr(str(d / t["take"])))
    by[t["line"]].append(s)
res = {k: [dict(asdict(s), variant=next(t["variant"] for t in takes if t["take"] == Path(s.path).name)) for s in rank(v)] for k, v in by.items()}
json.dump(res, open(d / "ranking.json", "w"), ensure_ascii=False, indent=2)
for k, v in res.items():
    b = v[0]; print(f"{k}: best={Path(b['path']).name} cer={b['cer']} issues={len(b['word_issues'])} pace={b['chars_per_s']}cps  {b['word_issues'][:3]}")
