#!/bin/bash
# EC2 user-data for the GPU box. launch_gpu.sh fills in the __PLACEHOLDERS__.
#
# Every boot:
#  1. formats the free local NVMe instance-store disk (fast, wiped at terminate)
#  2. restores the ComfyUI + Python environment from S3 (built once, then cached in S3)
#  3. copies the model weights S3 -> NVMe with s5cmd (same-region transfer is free)
#  4. restores your previous work (inputs/outputs/workflows) from S3
#  5. starts ComfyUI on 127.0.0.1:8188 (reach it through SSM port forwarding)
#  6. runs a watchdog that syncs work to S3 every 3 min and terminates the instance
#     when the GPU has been idle IDLE_MIN minutes, after MAX_HOURS, or on a Spot interruption.
set -euxo pipefail
exec > >(tee -a /var/log/vrea-bootstrap.log) 2>&1

cat >/etc/vrea.env <<'EOF'
BUCKET=__BUCKET__
AWS_REGION=__REGION__
AWS_DEFAULT_REGION=__REGION__
IDLE_MIN=__IDLE_MIN__
MAX_HOURS=__MAX_HOURS__
ROOT=/mnt/nvme
UV_PYTHON_INSTALL_DIR=/mnt/nvme/python
EOF
set -a; . /etc/vrea.env; set +a
export HOME=/root

# 1) Local NVMe instance store
DEV=$(lsblk -dpno NAME,MODEL | awk '/Instance Storage/ {print $1; exit}')
mkfs.ext4 -F -q "$DEV"
mkdir -p "$ROOT" && mount -o noatime "$DEV" "$ROOT"

# 2) Tools
apt-get -o DPkg::Lock::Timeout=600 update -y
apt-get -o DPkg::Lock::Timeout=600 install -y zstd git ffmpeg fonts-noto-core
curl -fsSL https://github.com/peak/s5cmd/releases/download/v2.3.0/s5cmd_2.3.0_Linux-64bit.tar.gz | tar -xz -C /usr/local/bin s5cmd
curl -LsSf https://astral.sh/uv/install.sh | env UV_INSTALL_DIR=/usr/local/bin UV_NO_MODIFY_PATH=1 sh

# 3) ComfyUI environment: restore from S3 cache, or build once and cache it
cd "$ROOT"
if s5cmd ls "s3://$BUCKET/env/comfyui-env.tar.zst" >/dev/null 2>&1; then
  s5cmd cat "s3://$BUCKET/env/comfyui-env.tar.zst" | zstd -d -T0 | tar -x -C "$ROOT"
else
  git clone --depth 1 https://github.com/comfyanonymous/ComfyUI.git
  cd ComfyUI
  uv venv --python 3.12 .venv
  uv pip install --python .venv/bin/python torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu128
  uv pip install --python .venv/bin/python -r requirements.txt
  for repo in Kosinkadink/ComfyUI-VideoHelperSuite Fannovel16/ComfyUI-Frame-Interpolation; do
    d="custom_nodes/${repo#*/}"
    git clone --depth 1 "https://github.com/$repo" "$d"
    if   [ -f "$d/requirements-no-cupy.txt" ]; then uv pip install --python .venv/bin/python -r "$d/requirements-no-cupy.txt"
    elif [ -f "$d/requirements.txt" ];         then uv pip install --python .venv/bin/python -r "$d/requirements.txt"; fi
  done
  cd "$ROOT"
  tar --exclude='ComfyUI/models' -cf - ComfyUI python | zstd -T0 -3 | s5cmd pipe "s3://$BUCKET/env/comfyui-env.tar.zst"
fi

# 4) Model weights S3 -> NVMe, then previous work
time s5cmd --numworkers 32 cp --concurrency 16 "s3://$BUCKET/models/*" "$ROOT/ComfyUI/models/"
for d in input output user; do
  mkdir -p "$ROOT/ComfyUI/$d"
  s5cmd cp "s3://$BUCKET/work/$d/*" "$ROOT/ComfyUI/$d/" || true   # empty on first run
done

# 5) ComfyUI service (localhost only)
cat >/etc/systemd/system/comfyui.service <<EOF
[Unit]
Description=ComfyUI
After=network-online.target
[Service]
WorkingDirectory=$ROOT/ComfyUI
ExecStart=$ROOT/ComfyUI/.venv/bin/python main.py --listen 127.0.0.1 --port 8188
Restart=always
[Install]
WantedBy=multi-user.target
EOF

# 6) Watchdog: sync work to S3, terminate when idle, past MAX_HOURS, or on Spot interruption
cat >/usr/local/bin/vrea-watchdog <<'EOF'
#!/bin/bash
set -a; . /etc/vrea.env; set +a
sync_up() { for d in input output user; do s5cmd sync "$ROOT/ComfyUI/$d/" "s3://$BUCKET/work/$d/" >/dev/null 2>&1; done; }
start=$(date +%s); idle=0; tick=0
while true; do
  sleep 60; tick=$((tick + 1))
  util=$(nvidia-smi --query-gpu=utilization.gpu --format=csv,noheader,nounits | head -1)
  if [ "${util:-0}" -lt 5 ]; then idle=$((idle + 1)); else idle=0; fi
  [ $((tick % 3)) -eq 0 ] && sync_up
  tok=$(curl -s -X PUT http://169.254.169.254/latest/api/token -H "X-aws-ec2-metadata-token-ttl-seconds: 60")
  spot=$(curl -s -o /dev/null -w '%{http_code}' -H "X-aws-ec2-metadata-token: $tok" http://169.254.169.254/latest/meta-data/spot/instance-action)
  if [ "$spot" = 200 ] || [ "$idle" -ge "$IDLE_MIN" ] || [ $(( $(date +%s) - start )) -ge $((MAX_HOURS * 3600)) ]; then
    logger "vrea-watchdog: stopping (spot=$spot idle=${idle}m)"; sync_up; shutdown -h now; exit 0
  fi
done
EOF
chmod +x /usr/local/bin/vrea-watchdog
cat >/etc/systemd/system/vrea-watchdog.service <<'EOF'
[Unit]
Description=vrea idle/budget watchdog
[Service]
ExecStart=/usr/local/bin/vrea-watchdog
Restart=always
[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable --now comfyui vrea-watchdog
echo "VREA READY"
