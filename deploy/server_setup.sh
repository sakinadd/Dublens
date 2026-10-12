#!/usr/bin/env bash
# Serverin özündə işlədilir (Termius və ya istənilən SSH terminalında), fayllar /opt/dublens-ə yükləndikdən sonra:
#
#   bash /opt/dublens/deploy/server_setup.sh
#
# Docker-i quraşdırır, DOMAIN-i serverin IP-sindən düzəldir (pulsuz HTTPS: 1-2-3-4.sslip.io),
# yaddaş üçün swap əlavə edir və DubLens-i işə salır. Təkrar işlətmək təhlükəsizdir.
set -e
cd "$(dirname "$0")/.."

[ -f .env ] || { echo "✗ .env tapılmadı. SFTP-də gizli faylları göstər və .env-i də yüklə."; exit 1; }
grep -q '^OPENAI_API_KEY=.\+' .env || { echo "✗ .env-də OPENAI_API_KEY boşdur."; exit 1; }
grep -q '^INVITE_CODE=.\+' .env || echo "⚠ INVITE_CODE boşdur — linki bilən hər kəs qeydiyyatdan keçə bilər."

echo "→ Docker…"
command -v docker >/dev/null || curl -fsSL https://get.docker.com | sh

IP=$(curl -s -4 --max-time 5 https://ifconfig.me || hostname -I | awk '{print $1}')
DOMAIN="$(echo "$IP" | tr . -).sslip.io"
sed -i '/^DOMAIN=/d' .env && echo "DOMAIN=$DOMAIN" >> .env

if [ ! -f /swapfile ]; then
  echo "→ Swap (2 GB)…"
  fallocate -l 2G /swapfile && chmod 600 /swapfile && mkswap /swapfile >/dev/null && swapon /swapfile
fi

echo "→ DubLens qurulur və işə salınır (ilk dəfə 3–8 dəqiqə)…"
docker compose up -d --build
docker compose ps

echo
echo "✓ Hazırdır (HTTPS sertifikatı ilk dəfə 1 dəqiqəyə qədər çəkə bilər):"
echo "  Panel:  https://$DOMAIN"
echo "  API:    https://api.$DOMAIN/health"
echo "  Uzantı: Bağlantı → Backend ünvanı = https://api.$DOMAIN"
