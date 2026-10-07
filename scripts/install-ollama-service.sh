#!/usr/bin/env bash
set -euo pipefail
# Instancia exclusiva de inferencia: no cambia ni detiene el Ollama de sistema.
MODELS="${OLLAMA_MODELS_DIR:-/usr/share/ollama/.ollama/models}"
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
UNIT="$HOME/.config/systemd/user/boletinDiario-ollama.service"
DROPIN="$HOME/.config/systemd/user/boletinDiario.service.d/ollama.conf"
OLLAMA="$(command -v ollama)"
for value in "$MODELS" "$OLLAMA" "$ROOT"; do
  if [[ "$value" == *'"'* || "$value" == *'%'* || "$value" == *$'\n'* || "$value" == *'\'* ]]; then
    echo 'Las rutas no pueden contener comillas, %, barras inversas ni saltos de línea.' >&2
    exit 1
  fi
done
if [[ ! -r "$MODELS/manifests/registry.ollama.ai/library/qwen3.5/4b" ]]; then
  echo "Falta qwen3.5:4b en $MODELS. Instálalo antes; este script no descarga modelos." >&2
  exit 1
fi
if [[ -e "$UNIT" || -e "$DROPIN" ]]; then
  echo 'Ya existe la unidad o el complemento de Ollama. Revísalos antes de sobrescribirlos.' >&2
  exit 1
fi
if [[ ! -e "$HOME/.config/systemd/user/boletinDiario.service" ]]; then
  echo 'Instala primero boletinDiario.service con scripts/install-service.sh.' >&2
  exit 1
fi
if [[ ! -x "$ROOT/.venv/bin/python" ]]; then
  echo 'Falta el entorno .venv del proyecto.' >&2
  exit 1
fi
python3 - <<'PY'
import socket
with socket.socket() as sock:
    try:
        sock.bind(('127.0.0.1',11435))
    except OSError as exc:
        raise SystemExit(f'El puerto 11435 no está disponible: {exc}')
PY
mkdir -p "$(dirname "$UNIT")" "$(dirname "$DROPIN")"
cat > "$UNIT" <<EOF
[Unit]
Description=Ollama local exclusivo para boletinDiario
Before=boletinDiario.service

[Service]
Type=simple
ExecStart="$OLLAMA" serve
ExecStartPost="$ROOT/.venv/bin/python" "$ROOT/scripts/wait-ollama.py"
Environment=OLLAMA_HOST=127.0.0.1:11435
Environment=RADAR_OLLAMA_HOST=http://127.0.0.1:11435
Environment="OLLAMA_MODELS=$MODELS"
Environment=OLLAMA_NO_CLOUD=1
Environment=OLLAMA_MAX_LOADED_MODELS=1
Environment=OLLAMA_NUM_PARALLEL=1
Environment=LLAMA_ARG_CACHE_RAM=0
Environment=LLAMA_ARG_CTX_CHECKPOINTS=0
Restart=on-failure
RestartSec=5
TimeoutStopSec=40
UMask=0077
NoNewPrivileges=true
PrivateTmp=true
RestrictSUIDSGID=true
MemoryHigh=6G
MemoryMax=10G

[Install]
WantedBy=default.target
EOF
cat > "$DROPIN" <<'EOF'
[Unit]
Requires=boletinDiario-ollama.service
After=boletinDiario-ollama.service

[Service]
Environment=RADAR_OLLAMA_HOST=http://127.0.0.1:11435
EOF
systemctl --user daemon-reload
systemctl --user enable --now boletinDiario-ollama.service
echo 'Ollama dedicado activo en 127.0.0.1:11435. No se modificó el servicio de sistema.'
echo 'Reinicia la aplicación cuando no haya tareas activas para adoptar el endpoint.'
