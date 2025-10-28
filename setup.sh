#!/usr/bin/env bash
set -euo pipefail
IFS=$'\n\t'

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

prompt_input() {
  local prompt_text="$1"
  local default_value="$2"
  local input=""

  if [[ -t 0 ]]; then
    read -r -p "${prompt_text}" input
  elif [[ -e /dev/tty ]]; then
    read -r -p "${prompt_text}" input < /dev/tty
  else
    input=""
  fi

  if [[ -z "${input}" ]]; then
    input="${default_value}"
  fi

  printf '%s' "${input}"
}

prompt_secret() {
  local prompt_text="$1"
  local input=""

  if [[ -t 0 ]]; then
    read -r -s -p "${prompt_text}" input
    echo
  elif [[ -e /dev/tty ]]; then
    read -r -s -p "${prompt_text}" input < /dev/tty
    echo >/dev/tty
  else
    echo "Error: unable to read secret input (no TTY available)." >&2
    exit 1
  fi

  printf '%s' "${input}"
}

if [[ $EUID -ne 0 ]]; then
  echo "This installer must be run as root."
  exit 1
fi

echo "Welcome to the Eris installer!"

DEVICE_MODEL="Unknown"
DEVICE_TYPE="generic_linux"
if [[ -f /proc/device-tree/model ]]; then
  DEVICE_MODEL=$(tr -d '\0' < /proc/device-tree/model)
  case "${DEVICE_MODEL}" in
    *"Raspberry Pi 4"*)
      DEVICE_TYPE="pi_4b"
      ;;
    *"Raspberry Pi Zero 2 W"*)
      DEVICE_TYPE="pi_zero_2w"
      ;;
  esac
elif [[ -f /etc/os-release ]]; then
  # shellcheck disable=SC1091
  source /etc/os-release
  DEVICE_MODEL=${PRETTY_NAME:-Unknown}
fi

case "${DEVICE_TYPE}" in
  pi_zero_2w)
    CHROMIUM_FLAGS="--use-gl=egl"
    FRIENDLY_NAME="Raspberry Pi Zero 2 W"
    ;;
  pi_4b)
    CHROMIUM_FLAGS="--enable-gpu-rasterization"
    FRIENDLY_NAME="Raspberry Pi 4B"
    ;;
  *)
    CHROMIUM_FLAGS="--use-gl=desktop"
    FRIENDLY_NAME="Generic Linux"
    ;;
esac

echo "Detected: ${FRIENDLY_NAME}"
echo "Setting up GPU-accelerated Chromium (${CHROMIUM_FLAGS})…"

export DEBIAN_FRONTEND=noninteractive
echo "Updating package lists…"
apt update
echo "Upgrading existing packages…"
apt upgrade -y

APT_PACKAGES=(
  python3
  python3-venv
  python3-pip
  git
  xorg
  xinit
  chromium
  mpv
  imv
  cifs-utils
  curl
  jq
)
echo "Installing dependencies…"
apt install -y "${APT_PACKAGES[@]}"

if ! command -v node >/dev/null 2>&1 || ! command -v npm >/dev/null 2>&1; then
  echo "Installing Node.js and npm…"
  apt install -y nodejs npm
else
  echo "Node.js and npm already installed."
fi

echo "Creating Eris service user and directories…"
useradd -r -s /usr/sbin/nologin eris >/dev/null 2>&1 || true
mkdir -p /opt/eris
mkdir -p /opt/eris/apps/daemon
mkdir -p /var/lib/eris/media/local
mkdir -p /var/lib/eris/media/cache
chown -R eris:eris /opt/eris /var/lib/eris

DAEMON_MAIN="/opt/eris/apps/daemon/main.py"
if [[ ! -f "${DAEMON_MAIN}" ]]; then
  echo "Writing placeholder daemon to ${DAEMON_MAIN}…"
  cat > "${DAEMON_MAIN}" <<'PY'
#!/usr/bin/env python3
import os
import time
from typing import Any, Dict

import uvicorn
import yaml
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from starlette.staticfiles import StaticFiles

START_TIME = time.time()
CONFIG_PATH = "/etc/eris/config.yaml"


def load_config() -> Dict[str, Any]:
  if os.path.exists(CONFIG_PATH):
    with open(CONFIG_PATH, "r", encoding="utf-8") as handle:
      data = yaml.safe_load(handle) or {}
      if isinstance(data, dict):
        return data
  return {}


def resolve_port(config: Dict[str, Any]) -> int:
  try:
    port = int(config.get("ui", {}).get("port", 8080))
  except Exception:
    port = 8080
  return port


app = FastAPI(title="Eris Placeholder Daemon")

WEBUI_PATH = "/opt/eris/apps/webui/dist"
WEBUI_INDEX = os.path.join(WEBUI_PATH, "index.html")
WEBUI_ASSETS = os.path.join(WEBUI_PATH, "assets")
class SafeStaticFiles(StaticFiles):
  async def __call__(self, scope, receive, send):
    if scope["type"] != "http":
      return
    await super().__call__(scope, receive, send)


if os.path.isdir(WEBUI_PATH) and os.path.isfile(WEBUI_INDEX):
  if os.path.isdir(WEBUI_ASSETS):
    app.mount("/assets", SafeStaticFiles(directory=WEBUI_ASSETS), name="assets")
  print("✅ Web UI static routing isolated — SafeStaticFiles prevents WS assertion errors")

  @app.get("/{full_path:path}", include_in_schema=False)
  def webui_spa(full_path: str, request: Request):
    blocked = ("api/", "ws", "assets/")
    if full_path and full_path.startswith(blocked):
      return {"detail": "Not Found"}
    path = request.url.path.lstrip("/")
    if path and path.startswith(blocked):
      return {"detail": "Not Found"}
    return FileResponse(WEBUI_INDEX)
else:
  print(f"⚠️  Web UI directory not found or missing index: {WEBUI_PATH}")


@app.get("/api/health")
def health() -> Dict[str, Any]:
  uptime = int(time.time() - START_TIME)
  return {
      "status": "ok",
      "uptime": uptime,
      "version": "placeholder",
  }


@app.get("/api/state")
def state() -> Dict[str, Any]:
  return {
      "mode": "web",
      "url": load_config().get("device", {}).get("homepage", "https://example.com"),
  }


def main() -> None:
  config = load_config()
  port = resolve_port(config)
  uvicorn.run(app, host="0.0.0.0", port=port)


if __name__ == "__main__":
  main()
PY
  chmod 755 "${DAEMON_MAIN}"
  chown eris:eris "${DAEMON_MAIN}"
fi

VENV_PATH="/opt/eris/venv"
echo "Configuring Python virtual environment at ${VENV_PATH}…"
if [[ ! -d "${VENV_PATH}" ]]; then
  python3 -m venv "${VENV_PATH}"
fi
"${VENV_PATH}/bin/pip" install --upgrade pip
"${VENV_PATH}/bin/pip" install fastapi "uvicorn[standard]" pyyaml psutil python-multipart bcrypt

WEBUI_DIR="/opt/eris/apps/webui"
WEBUI_DIST="${WEBUI_DIR}/dist"
SOURCE_WEBUI_DIR="${SCRIPT_DIR}/opt/eris/apps/webui"

if [[ ! -d "${WEBUI_DIR}" ]]; then
  if [[ -d "${SOURCE_WEBUI_DIR}" ]]; then
    echo "Copying Web UI source from repository into ${WEBUI_DIR}…"
    mkdir -p "${WEBUI_DIR}"
    cp -a "${SOURCE_WEBUI_DIR}/." "${WEBUI_DIR}/"
  else
    echo "Web UI source not bundled with installer; cloning repository…"
    TEMP_CLONE="$(mktemp -d)"
    trap 'rm -rf "${TEMP_CLONE}"' EXIT
    if git clone --depth 1 https://github.com/tpersp/Eris.git "${TEMP_CLONE}" >/dev/null 2>&1; then
      if [[ -d "${TEMP_CLONE}/opt/eris/apps/webui" ]]; then
        echo "Copying Web UI source from remote repository…"
        mkdir -p "${WEBUI_DIR}"
        cp -a "${TEMP_CLONE}/opt/eris/apps/webui/." "${WEBUI_DIR}/"
      else
        echo "Error: Cloned repository missing web UI source." >&2
        exit 1
      fi
    else
      echo "Error: Unable to clone Eris repository for web UI." >&2
      exit 1
    fi
    rm -rf "${TEMP_CLONE}"
    trap - EXIT
  fi
fi

if [[ -d "${WEBUI_DIR}" ]]; then
  if [[ -d "${WEBUI_DIST}" ]]; then
    echo "Web UI build artifacts detected at ${WEBUI_DIST}; skipping build."
  else
    echo "Building Eris Web UI..."
    pushd "${WEBUI_DIR}" >/dev/null
    npm install --omit=dev
    npm run build
    popd >/dev/null
    chown -R eris:eris "${WEBUI_DIR}"
    echo "Eris Web UI build complete."
  fi
else
  echo "Warning: Web UI directory ${WEBUI_DIR} not found; skipping build."
fi

CONFIGURE_SHARE="$(prompt_input "Would you like to configure a network media share? [Y/n] " "Y")"
USE_NETWORK=false
NETWORK_PATH=""
MOUNT_POINT=""

if [[ "${CONFIGURE_SHARE^^}" == "Y" || "${CONFIGURE_SHARE}" == "" ]]; then
  USE_NETWORK=true
  NETWORK_PATH="$(prompt_input "Enter Samba share (e.g. //192.168.1.10/Media): " "//nas/media")"
  SAMBA_USER="$(prompt_input "Enter Samba username [leave blank for guest access]: " "")"
  SAMBA_PASS="$(prompt_secret "Enter Samba password (leave blank for guest access): ")"
  MOUNT_POINT="/mnt/eris_media"
  mkdir -p "${MOUNT_POINT}"
  chown eris:eris "${MOUNT_POINT}"
  CIFS_OPTIONS="uid=eris,gid=eris,iocharset=utf8,file_mode=0660,dir_mode=0770"
  if [[ -z "${SAMBA_USER}" && -z "${SAMBA_PASS}" ]]; then
    CIFS_OPTIONS="guest,${CIFS_OPTIONS}"
  else
    CIFS_OPTIONS="username=${SAMBA_USER},password=${SAMBA_PASS},${CIFS_OPTIONS}"
  fi
  FSTAB_ENTRY="${NETWORK_PATH} ${MOUNT_POINT} cifs ${CIFS_OPTIONS} 0 0"
  if ! grep -qsF "${NETWORK_PATH} ${MOUNT_POINT} cifs" /etc/fstab; then
    echo "Adding network share to /etc/fstab…"
    echo "${FSTAB_ENTRY}" >> /etc/fstab
  else
    echo "Network share already present in /etc/fstab; skipping append."
  fi
  echo "Mounting ${MOUNT_POINT}…"
  if ! mount "${MOUNT_POINT}" >/dev/null 2>&1; then
    echo "Mount failed; retrying with explicit options…"
    mount -t cifs "${NETWORK_PATH}" "${MOUNT_POINT}" -o "${CIFS_OPTIONS}"
  fi
else
  echo "Skipping network media share configuration."
  USE_NETWORK=false
fi

LOCAL_MEDIA_PATH="$(prompt_input "Enter local media folder path [/var/lib/eris/media/local]: " "/var/lib/eris/media/local")"
mkdir -p "${LOCAL_MEDIA_PATH}"
chown -R eris:eris "${LOCAL_MEDIA_PATH}"
if [[ "${USE_NETWORK}" == false ]]; then
  MOUNT_POINT="${LOCAL_MEDIA_PATH}"
fi

UI_PORT="$(prompt_input "Enter Web UI port [8080]: " "8080")"
while [[ -z "${UI_PORT}" || "${UI_PORT}" =~ [^0-9] ]]; do
  echo "Port must be a numeric value."
  UI_PORT="$(prompt_input "Enter Web UI port [8080]: " "8080")"
done

ADMIN_PASSWORD=""
while [[ -z "${ADMIN_PASSWORD}" ]]; do
  ADMIN_PASSWORD="$(prompt_secret "Set admin password: ")"
  if [[ -z "${ADMIN_PASSWORD}" ]]; then
    echo "Password cannot be empty."
  fi
done

PASSWORD_HASH="$(
  ERIS_ADMIN_PASSWORD="${ADMIN_PASSWORD}" "${VENV_PATH}/bin/python" - <<'PY'
import bcrypt
import os

password = os.environ["ERIS_ADMIN_PASSWORD"].encode("utf-8")
hashed = bcrypt.hashpw(password, bcrypt.gensalt())
print(hashed.decode("utf-8"))
PY
)"
unset ADMIN_PASSWORD
unset SAMBA_PASS

mkdir -p /etc/eris
CONFIG_PATH="/etc/eris/config.yaml"
echo "Writing configuration to ${CONFIG_PATH}…"
cat > "${CONFIG_PATH}" <<EOF
device:
  name: eris-$(hostname)
  homepage: "https://example.com"
ui:
  port: ${UI_PORT}
media:
  use_network: ${USE_NETWORK}
  network_path: "${NETWORK_PATH}"
  mount_point: "${MOUNT_POINT}"
security:
  password_hash: "${PASSWORD_HASH}"
EOF
chown eris:eris "${CONFIG_PATH}"
chmod 640 "${CONFIG_PATH}"

echo "Recording Chromium flags…"
echo "${CHROMIUM_FLAGS}" > /etc/eris/chromium-flags.conf
chown eris:eris /etc/eris/chromium-flags.conf
chmod 644 /etc/eris/chromium-flags.conf

SERVICE_SOURCE="scripts/eris.service"
SERVICE_TARGET="/etc/systemd/system/eris.service"
if [[ -f "${SERVICE_SOURCE}" ]]; then
  echo "Configuring systemd service…"
  cp "${SERVICE_SOURCE}" "${SERVICE_TARGET}"
  systemctl daemon-reload
  systemctl enable --now eris
else
  echo "Warning: ${SERVICE_SOURCE} not found. Skipping systemd service configuration."
fi

sleep 5
if command -v curl >/dev/null 2>&1; then
  if curl -fsS "http://localhost:${UI_PORT}/health" >/dev/null 2>&1; then
    echo "API health check succeeded."
  else
    echo "Warning: API health check failed. Ensure the Eris service is running."
  fi
else
  echo "curl not available; skipping API health check."
fi

IP_ADDRESS="$(hostname -I 2>/dev/null | awk '{print $1}')"
echo "✅ Eris installed successfully!"
if [[ -n "${IP_ADDRESS}" ]]; then
  echo "Access it via http://${IP_ADDRESS}:${UI_PORT} or http://eris.local:${UI_PORT}"
else
  echo "Access it via http://<your-ip>:${UI_PORT} or http://eris.local:${UI_PORT}"
fi
