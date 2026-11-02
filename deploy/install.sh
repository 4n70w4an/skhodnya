#!/usr/bin/env bash
# Установка Сходни как systemd-сервиса.
#   sudo ./deploy/install.sh                 # в /opt/skhodnya, localhost:8080
#   sudo HOST=0.0.0.0 PORT=9000 ./deploy/install.sh
#   sudo DEST=/srv/skhodnya USER_NAME=skhodnya ./deploy/install.sh
set -euo pipefail

SRC="$(cd "$(dirname "$0")/.." && pwd)"
DEST="${DEST:-/opt/skhodnya}"
USER_NAME="${USER_NAME:-skhodnya}"
HOST="${HOST:-127.0.0.1}"
PORT="${PORT:-8080}"
UNIT=/etc/systemd/system/skhodnya.service

if [ "$(id -u)" -ne 0 ]; then
  echo "Запустите через sudo." >&2
  exit 1
fi

if ! id -u "$USER_NAME" >/dev/null 2>&1; then
  useradd --system --home "$DEST" --shell /usr/sbin/nologin "$USER_NAME"
  echo "Создан пользователь $USER_NAME"
fi

mkdir -p "$DEST/data"
# код и ресурсы обновляем, данные не трогаем
rsync -a --exclude '.git' --exclude '__pycache__' --exclude 'data/' \
      --exclude '*.personal.js' --exclude '*.bak' "$SRC/" "$DEST/"
# данные копируем только при первой установке
if [ ! -f "$DEST/data/manifest.js" ]; then
  cp -a "$SRC/data/." "$DEST/data/"
  rm -f "$DEST/data"/*.personal.js "$DEST/data"/*.bak
fi

chown -R "$USER_NAME:$USER_NAME" "$DEST"
chmod -R u+rwX,go+rX "$DEST"

install -m 0644 "$SRC/deploy/skhodnya.service" "$UNIT"
sed -i "s|--host 127.0.0.1 --port 8080|--host $HOST --port $PORT|" "$UNIT"
sed -i "s|/opt/skhodnya|$DEST|g" "$UNIT"

systemctl daemon-reload
systemctl enable skhodnya.service
systemctl restart skhodnya.service
sleep 1
systemctl --no-pager --lines=0 status skhodnya.service || true

echo
echo "Готово. Открывайте: http://${HOST/0.0.0.0/127.0.0.1}:$PORT"
echo "Логи: journalctl -u skhodnya -f"
