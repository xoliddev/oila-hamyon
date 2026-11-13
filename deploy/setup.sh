#!/usr/bin/env bash
# Ubuntu/Debian serverga o'rnatish. Loyiha papkasi ichidan ishga tushiring:
#   sudo bash deploy/setup.sh
set -euo pipefail

APP_DIR=/opt/oila-hamyon
SRC_DIR="$(cd "$(dirname "$0")/.." && pwd)"

if [[ $EUID -ne 0 ]]; then
  echo "sudo bilan ishga tushiring: sudo bash deploy/setup.sh"; exit 1
fi

echo "==> Paketlar"
apt-get update -qq
apt-get install -y -qq python3 python3-venv python3-pip tzdata >/dev/null

echo "==> Foydalanuvchi va papka"
id hamyon &>/dev/null || useradd --system --home "$APP_DIR" --shell /usr/sbin/nologin hamyon
mkdir -p "$APP_DIR"
if [[ "$SRC_DIR" != "$APP_DIR" ]]; then
  cp -r "$SRC_DIR"/hamyon "$SRC_DIR"/requirements.txt "$SRC_DIR"/deploy "$APP_DIR"/
  [[ -f "$APP_DIR/.env" ]] || cp "$SRC_DIR/.env" "$APP_DIR/.env" 2>/dev/null || cp "$SRC_DIR/.env.example" "$APP_DIR/.env"
fi
mkdir -p "$APP_DIR/data"

echo "==> Python muhiti"
python3 -m venv "$APP_DIR/.venv"
"$APP_DIR/.venv/bin/pip" install -q --upgrade pip
"$APP_DIR/.venv/bin/pip" install -q -r "$APP_DIR/requirements.txt"

chown -R hamyon:hamyon "$APP_DIR"
chmod 600 "$APP_DIR/.env"

echo "==> systemd xizmati"
cp "$APP_DIR/deploy/hamyon.service" /etc/systemd/system/hamyon.service
systemctl daemon-reload
systemctl enable --now hamyon

sleep 3
systemctl --no-pager status hamyon | head -n 12
echo
echo "✅ Tayyor. Jurnal: sudo journalctl -u hamyon -f"
echo "   .env ni o'zgartirsangiz: sudo systemctl restart hamyon"
