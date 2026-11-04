"""Turn a model-family list into the bootstrap's copy plan: "fam=file|file;fam=file|...".
usage: python model_plan.py edit,video models.json   (prints the plan and, on stderr, the GB per family)"""
import json, sys

fams, m = sys.argv[1].split(","), json.load(open(sys.argv[2]))["families"]
bad = [f for f in fams if f not in m]
if bad:
    sys.exit(f"unknown model families: {bad} (have {sorted(m)})")
seen, parts = set(), []
for f in fams:                                    # a file shared by two families (text encoder, VAE) is copied once
    files = [x for x in m[f]["files"] if x not in seen]; seen.update(files)
    parts.append(f + "=" + "|".join(files))
print(";".join(parts))
