#!/usr/bin/env bash
# Clip 1.1-E / 1.2-A: still, almost-black void with a barely visible, loopable heat-haze shimmer.
# Runs on CPU (laptop or GPU box). Wave periods (6 s, 3 s, 2 s) divide the 6 s length, so it loops seamlessly.
# usage: ./void.sh out.mp4 [seconds=6]
set -euo pipefail
OUT=${1:-void.mp4}
DUR=${2:-6}
ffmpeg -loglevel error -y -f lavfi -i "nullsrc=s=540x960:d=${DUR}:r=30" \
  -vf "geq=lum='24+7*sin(0.02*Y+2*PI*T/6+3*sin(0.01*X+2*PI*T/3))+4*sin(0.015*X-2*PI*T/2)':cb=134:cr=129,gblur=sigma=8,scale=1080:1920:flags=bicubic,noise=alls=2:allf=t" \
  -c:v libx264 -crf 16 -pix_fmt yuv420p "$OUT"
echo "wrote $OUT"
