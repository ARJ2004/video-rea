#!/bin/bash
# First-boot setup of the platform server (Ubuntu 24.04 arm64, t4g.small). deploy.sh fills the __PLACEHOLDERS__.
# Installs Postgres (local only, peer auth), ffmpeg + fonts, the app (uvicorn on 127.0.0.1:8000) and Caddy as the public
# HTTPS front door on __DOMAIN__ (Let's Encrypt). Only ports 80/443 are open; Postgres is never exposed.
set -euxo pipefail
exec > >(tee -a /var/log/vrea-setup.log) 2>&1
export DEBIAN_FRONTEND=noninteractive
BUCKET=__BUCKET__; REGION=__REGION__; DOMAIN=__DOMAIN__

apt-get -o DPkg::Lock::Timeout=600 update -y
apt-get -o DPkg::Lock::Timeout=600 install -y postgresql python3-venv ffmpeg fonts-noto-core curl gnupg debian-keyring debian-archive-keyring apt-transport-https

# 2 GB swap: ffmpeg on a 2 GB machine
if [ ! -f /swapfile ]; then fallocate -l 2G /swapfile && chmod 600 /swapfile && mkswap /swapfile && swapon /swapfile && echo '/swapfile none swap sw 0 0' >> /etc/fstab; fi

id vrea >/dev/null 2>&1 || useradd -r -m -d /opt/vrea -s /bin/bash vrea
sudo -u postgres psql -tc "SELECT 1 FROM pg_roles WHERE rolname='vrea'" | grep -q 1 || sudo -u postgres psql -c "CREATE ROLE vrea LOGIN"
sudo -u postgres psql -tc "SELECT 1 FROM pg_database WHERE datname='vrea'" | grep -q 1 || sudo -u postgres createdb -O vrea vrea

python3 -m venv /opt/vrea/venv
/opt/vrea/venv/bin/pip install -q --upgrade pip boto3
cat >/usr/local/bin/vrea-update <<'EOF'
#!/bin/bash
# fetch the latest app bundle from S3 and restart (used at first boot and by deploy.sh for updates)
set -euo pipefail
. /etc/vrea-platform.env
/opt/vrea/venv/bin/python - <<PY
import boto3, tarfile, io, shutil, os
b = boto3.client("s3", region_name="$VREA_REGION").get_object(Bucket="$VREA_BUCKET", Key="platform/server_bundle.tar.gz")["Body"].read()
shutil.rmtree("/opt/vrea/app.new", ignore_errors=True); os.makedirs("/opt/vrea/app.new")
tarfile.open(fileobj=io.BytesIO(b)).extractall("/opt/vrea/app.new")
shutil.rmtree("/opt/vrea/app.old", ignore_errors=True)
if os.path.exists("/opt/vrea/app"): os.rename("/opt/vrea/app", "/opt/vrea/app.old")
os.rename("/opt/vrea/app.new", "/opt/vrea/app")
PY
/opt/vrea/venv/bin/pip install -q -r /opt/vrea/app/platform/requirements.txt
chown -R vrea:vrea /opt/vrea
systemctl restart vrea-web || true
EOF
chmod +x /usr/local/bin/vrea-update

# quoted heredoc: the password hash contains '$' and must not be expanded by the shell
cat >/etc/vrea-platform.env <<'EOF'
VREA_DSN=postgresql://vrea@/vrea
VREA_BUCKET=__BUCKET__
VREA_REGION=__REGION__
AWS_DEFAULT_REGION=__REGION__
VREA_PUBLIC_URL=https://__DOMAIN__
VREA_PW_HASH='__PW_HASH__'
VREA_QUICKTEST=/opt/vrea/app/infra/quicktest
EOF
chmod 640 /etc/vrea-platform.env && chgrp vrea /etc/vrea-platform.env

cat >/etc/systemd/system/vrea-web.service <<'EOF'
[Unit]
Description=vrea platform web app + engine + autoscaler
After=network-online.target postgresql.service
[Service]
User=vrea
EnvironmentFile=/etc/vrea-platform.env
WorkingDirectory=/opt/vrea/app/platform/server
ExecStart=/opt/vrea/venv/bin/uvicorn app:app --host 127.0.0.1 --port 8000 --proxy-headers
Restart=always
RestartSec=3
[Install]
WantedBy=multi-user.target
EOF
systemctl daemon-reload && systemctl enable vrea-web
/usr/local/bin/vrea-update

# Caddy: HTTPS front door
if ! command -v caddy >/dev/null; then
  curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
  curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' > /etc/apt/sources.list.d/caddy-stable.list
  apt-get -o DPkg::Lock::Timeout=600 update -y && apt-get -o DPkg::Lock::Timeout=600 install -y caddy
fi
cat >/etc/caddy/Caddyfile <<EOF
$DOMAIN {
	encode gzip
	reverse_proxy 127.0.0.1:8000
}
EOF
systemctl restart caddy

# wait for the app, then import Episode 2 (approved by the owner) once
for i in $(seq 60); do curl -fs http://127.0.0.1:8000/healthz && break; sleep 2; done
cd /opt/vrea/app/platform/server && sudo -u vrea bash -c 'set -a; . /etc/vrea-platform.env; set +a; /opt/vrea/venv/bin/python import_ep2.py'
echo "PLATFORM READY"
