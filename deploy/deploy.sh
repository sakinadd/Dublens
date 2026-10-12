#!/usr/bin/env bash
# DubLens → DigitalOcean Droplet, bir əmrlə.
#
#   ./deploy/deploy.sh root@164.92.10.20
#
# Nə edir: layihəni serverə köçürür (.env daxil, .venv/data yox) → Docker yoxdursa quraşdırır →
# DOMAIN-i IP-dən düzəldir (164-92-10-20.sslip.io, pulsuz HTTPS) → docker compose up --build.
# Təkrar işlətmək təhlükəsizdir: sonrakı dəfələrdə yalnız dəyişənləri göndərir və yenidən qurur.
set -euo pipefail

HOST="${1:?İstifadə: ./deploy/deploy.sh root@SERVER_IP}"
IP="${HOST#*@}"
DOMAIN="${DOMAIN:-$(echo "$IP" | tr . -).sslip.io}"
cd "$(dirname "$0")/.."

[ -f .env ] || { echo ".env tapılmadı (açarlar orada olmalıdır)"; exit 1; }

echo "→ Fayllar $HOST:/opt/dublens qovluğuna köçürülür…"
ssh -o StrictHostKeyChecking=accept-new "$HOST" "mkdir -p /opt/dublens"
rsync -az --delete \
  --exclude .venv --exclude data --exclude .idea --exclude __pycache__ --exclude .git --exclude '*.pyc' \
  ./ "$HOST:/opt/dublens/"

echo "→ Serverdə Docker və konteynerlər…"
ssh "$HOST" DOMAIN="$DOMAIN" bash -s <<'REMOTE'
set -e
command -v docker >/dev/null || curl -fsSL https://get.docker.com | sh
cd /opt/dublens
if grep -q '^DOMAIN=' .env; then sed -i "s/^DOMAIN=.*/DOMAIN=$DOMAIN/" .env; else echo "DOMAIN=$DOMAIN" >> .env; fi
# 1 GB RAM-lı serverdə build zamanı yaddaş çatsın deyə swap
if [ ! -f /swapfile ]; then fallocate -l 2G /swapfile && chmod 600 /swapfile && mkswap /swapfile && swapon /swapfile; fi
docker compose up -d --build
docker compose ps
REMOTE

echo
echo "Hazırdır (HTTPS sertifikatı ilk dəfə 1 dəqiqəyə qədər çəkə bilər):"
echo "  Panel:  https://$DOMAIN"
echo "  API:    https://api.$DOMAIN/health"
echo "Uzantıda: Bağlantı → Backend ünvanı = https://api.$DOMAIN"
