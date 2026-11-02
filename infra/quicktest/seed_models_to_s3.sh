#!/usr/bin/env bash
# Copy every model in models.manifest straight from Hugging Face / GitHub into S3.
# Files are streamed (curl | aws s3 cp -), so no local disk is needed. Safe to re-run:
# files already in S3 with the right size are skipped, and truncated uploads are deleted.
#
# usage: HF_TOKEN=... ./seed_models_to_s3.sh <bucket> [manifest] [parallel]
set -euo pipefail

BUCKET=${1:?usage: seed_models_to_s3.sh <bucket> [manifest] [parallel]}
MANIFEST=${2:-models.manifest}
PARALLEL=${3:-3}
export BUCKET

seed_one() {
  set -o pipefail
  local dir=$1 url=$2 name key expected actual
  local auth=()
  name=$(basename "${url%%\?*}")
  key="models/$dir/$name"
  if [[ -n "${HF_TOKEN:-}" && $url == https://huggingface.co/* ]]; then
    auth=(-H "Authorization: Bearer $HF_TOKEN")
  fi

  # Expected size: HF sends x-linked-size for LFS files; otherwise use the final content-length.
  expected=$(curl -sIL ${auth[@]+"${auth[@]}"} "$url" | tr -d '\r' |
    awk 'tolower($1)=="x-linked-size:"{x=$2} tolower($1)=="content-length:"{c=$2} END{print (x!="" ? x : c)}')
  if [[ -z "$expected" || "$expected" == 0 ]]; then
    echo "ERROR cannot read size of $url (gated model? set HF_TOKEN)" >&2; return 1
  fi

  actual=$(aws s3api head-object --bucket "$BUCKET" --key "$key" --query ContentLength --output text 2>/dev/null || echo 0)
  if [[ "$actual" == "$expected" ]]; then echo "skip  $key"; return 0; fi

  echo "fetch $key ($((expected / 1024 / 1024)) MiB)"
  curl -fsSL --retry 5 ${auth[@]+"${auth[@]}"} "$url" | aws s3 cp - "s3://$BUCKET/$key" --only-show-errors || true

  actual=$(aws s3api head-object --bucket "$BUCKET" --key "$key" --query ContentLength --output text 2>/dev/null || echo 0)
  if [[ "$actual" != "$expected" ]]; then
    echo "ERROR size mismatch for $key: got $actual, want $expected — removing" >&2
    aws s3 rm "s3://$BUCKET/$key" --only-show-errors || true
    return 1
  fi
  echo "done  $key"
}
export -f seed_one

grep -vE '^[[:space:]]*(#|$)' "$MANIFEST" | xargs -P "$PARALLEL" -L 1 bash -c 'seed_one "$0" "$1"'
echo "All models are in s3://$BUCKET/models/"
