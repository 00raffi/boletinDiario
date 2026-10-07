#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
if [[ "$ROOT" == *'"'* || "$ROOT" == *'%'* || "$ROOT" == *$'\n'* ]]; then
  echo 'La ruta no puede contener comillas, %, ni saltos de línea.' >&2
  exit 1
fi
UNIT="$HOME/.config/systemd/user/paper-radar.service"
if [[ -e "$UNIT" ]]; then
  echo "Ya existe $UNIT. Revísalo antes de sobrescribirlo." >&2
  exit 1
fi
if [[ ! -x "$ROOT/.venv/bin/python" ]]; then
  echo 'Primero crea .venv e instala el proyecto.' >&2
  exit 1
fi
mkdir -p "$HOME/.config/systemd/user"
cat > "$UNIT" <<EOF
[Unit]
Description=Paper Radar - observatorio local de investigación
After=network-online.target

[Service]
Type=simple
WorkingDirectory=$ROOT
ExecStart="$ROOT/.venv/bin/python" -m radar
Environment=PYTHONUNBUFFERED=1
Restart=on-failure
RestartSec=15
UMask=0077
NoNewPrivileges=true
PrivateTmp=true
RestrictSUIDSGID=true

[Install]
WantedBy=default.target
EOF
systemctl --user daemon-reload
systemctl --user enable --now paper-radar.service
echo 'Servicio activado. Abre http://127.0.0.1:8765'
echo 'Arranca al iniciar sesión; recupera las búsquedas pendientes. No requiere privilegios root.'
