#!/usr/bin/env bash
set -euo pipefail
IFS=$'\n\t'

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

show_usage() {
  cat <<'EOF'
Usage: setup.sh [--deps-only]

Options:
  --deps-only   Install or update system dependencies without re-running the interactive installer.
EOF
}

DEPS_ONLY=false
for arg in "$@"; do
  case "${arg}" in
    --deps-only)
      DEPS_ONLY=true
      ;;
    -h|--help)
      show_usage
      exit 0
      ;;
    *)
      echo "Unknown option: ${arg}" >&2
      show_usage >&2
      exit 1
      ;;
  esac
done

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

install_system_dependencies() {
  export DEBIAN_FRONTEND=noninteractive
  echo "Updating package lists…"
  apt update
  echo "Upgrading existing packages…"
  apt upgrade -y

  local -a APT_PACKAGES=(
    python3
    python3-venv
    python3-pip
    git
    xorg
    xinit
    x11-xserver-utils
    chromium
    mpv
    imv
    cifs-utils
    curl
    jq
    matchbox-window-manager
    openbox
    ffmpeg
  )
  echo "Installing dependencies…"
  apt install -y "${APT_PACKAGES[@]}"

  if ! command -v node >/dev/null 2>&1 || ! command -v npm >/dev/null 2>&1; then
    echo "Installing Node.js and npm…"
    apt install -y nodejs npm
  else
    echo "Node.js and npm already installed."
  fi
}

if [[ $EUID -ne 0 ]]; then
  echo "This installer must be run as root."
  exit 1
fi

if [[ "${DEPS_ONLY}" == true ]]; then
  echo "Running Eris system dependency sync (--deps-only)."
else
  echo "Welcome to the Eris installer!"
fi

if [[ "${DEPS_ONLY}" == true ]]; then
  install_system_dependencies
  echo "✅ System dependencies refreshed."
  exit 0
fi

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

install_system_dependencies

CHROMIUM_FLAGS_FILE="/etc/eris/chromium-flags.conf"
CHROMIUM_BINARY="$(command -v chromium-browser || true)"
if [[ -z "${CHROMIUM_BINARY}" ]]; then
  CHROMIUM_BINARY="$(command -v chromium || true)"
fi
if [[ -z "${CHROMIUM_BINARY}" ]]; then
  CHROMIUM_BINARY="/usr/bin/chromium-browser"
fi

DISPLAY_LAUNCHER="$(command -v xinit || echo /usr/bin/xinit) /opt/eris/scripts/kiosk-session.sh -- :0 -nolisten tcp"

echo "Creating Eris service user and directories…"
useradd -r -s /usr/sbin/nologin eris >/dev/null 2>&1 || true
mkdir -p /opt/eris
mkdir -p /opt/eris/apps/daemon
mkdir -p /var/lib/eris/media/local
mkdir -p /var/lib/eris/media/cache
chown -R eris:eris /opt/eris /var/lib/eris
touch /var/lib/eris/media/metadata.json
touch /var/lib/eris/playlists.json
chown eris:eris /var/lib/eris/media/metadata.json /var/lib/eris/playlists.json
chmod 640 /var/lib/eris/media/metadata.json /var/lib/eris/playlists.json
SOURCE_DAEMON_DIR="${SCRIPT_DIR}/opt/eris/apps/daemon"
TARGET_DAEMON_DIR="/opt/eris/apps/daemon"
if [[ -d "${SOURCE_DAEMON_DIR}" ]]; then
  echo "Deploying Eris daemon from repository…"
  rm -rf "${TARGET_DAEMON_DIR}"
  mkdir -p "${TARGET_DAEMON_DIR}"
  cp -a "${SOURCE_DAEMON_DIR}/." "${TARGET_DAEMON_DIR}/"
  chown -R eris:eris "${TARGET_DAEMON_DIR}"
  chmod 755 "${TARGET_DAEMON_DIR}/main.py"
else
  echo "Error: Repository daemon source not found at ${SOURCE_DAEMON_DIR}." >&2
  exit 1
fi

SOURCE_SCRIPTS_DIR="${SCRIPT_DIR}/opt/eris/scripts"
TARGET_SCRIPTS_DIR="/opt/eris/scripts"
if [[ -d "${SOURCE_SCRIPTS_DIR}" ]]; then
  echo "Deploying Eris kiosk scripts…"
  rm -rf "${TARGET_SCRIPTS_DIR}"
  mkdir -p "${TARGET_SCRIPTS_DIR}"
  cp -a "${SOURCE_SCRIPTS_DIR}/." "${TARGET_SCRIPTS_DIR}/"
  chown -R eris:eris "${TARGET_SCRIPTS_DIR}"
  chmod 755 "${TARGET_SCRIPTS_DIR}"/*.sh
else
  echo "Warning: kiosk helper scripts not found; display bootstrap may fail."
fi

VENV_PATH="/opt/eris/venv"
echo "Configuring Python virtual environment at ${VENV_PATH}…"
if [[ ! -d "${VENV_PATH}" ]]; then
  python3 -m venv "${VENV_PATH}"
fi
"${VENV_PATH}/bin/pip" install --upgrade pip
if [[ -f "${SCRIPT_DIR}/requirements.txt" ]]; then
  "${VENV_PATH}/bin/pip" install --upgrade -r "${SCRIPT_DIR}/requirements.txt"
else
  "${VENV_PATH}/bin/pip" install --upgrade fastapi "uvicorn[standard]" pyyaml psutil python-multipart bcrypt
fi

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

CACHE_MEDIA_PATH="/var/lib/eris/media/cache"

MPV_BINARY="$(command -v mpv || echo mpv)"
IMV_BINARY="$(command -v imv || echo imv)"

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

TOKEN_SECRET="$("${VENV_PATH}/bin/python" - <<'PY'
import secrets
print(secrets.token_urlsafe(48))
PY
)"

mkdir -p /etc/eris
CONFIG_PATH="/etc/eris/config.yaml"
echo "Writing configuration to ${CONFIG_PATH}…"
cat > "${CONFIG_PATH}" <<EOF
device:
  name: eris-$(hostname)
  homepage: "https://example.com"
display:
  name: ":0"
  launcher: "${DISPLAY_LAUNCHER}"
  startup_timeout: 15
ui:
  port: ${UI_PORT}
media:
  use_network: ${USE_NETWORK}
  network_path: "${NETWORK_PATH}"
  mount_point: "${MOUNT_POINT}"
  local_path: "${LOCAL_MEDIA_PATH}"
  cache_path: "${CACHE_MEDIA_PATH}"
  metadata_path: "/var/lib/eris/media/metadata.json"
  mpv_binary: "${MPV_BINARY}"
  imv_binary: "${IMV_BINARY}"
  image_duration: 30
  max_upload_mb: 200
state:
  path: "/var/lib/eris/state.json"
  playlist_path: "/var/lib/eris/playlists.json"
security:
  password_hash: "${PASSWORD_HASH}"
  token_secret: "${TOKEN_SECRET}"
  token_ttl: 3600
chromium:
  binary: "${CHROMIUM_BINARY}"
  flags_file: "${CHROMIUM_FLAGS_FILE}"
  debug_port: 9222
scheduler:
  tick_interval: 15
EOF
chown eris:eris "${CONFIG_PATH}"
chmod 640 "${CONFIG_PATH}"

echo "Recording Chromium flags…"
echo "${CHROMIUM_FLAGS}" > "${CHROMIUM_FLAGS_FILE}"
chown eris:eris "${CHROMIUM_FLAGS_FILE}"
chmod 644 "${CHROMIUM_FLAGS_FILE}"

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
