# Eris – Modular Digital Signage Platform  
*Controlled chaos for beautiful screens.*

Eris is a lightweight Linux-based digital signage system that displays web pages, videos, and images on connected monitors.  
It’s built for Raspberry Pi Zero 2 W, Pi 4 B, and Ubuntu Server devices.

## Hardware & software requirements

- Raspberry Pi Zero 2 W (512 MB RAM min) or Pi 4 B (2 GB + recommended)
- Micro-SD (16 GB +)
- HDMI display
- Fresh OS (Lite or Server)
- Network access (Wi-Fi or Ethernet)

## Quick install commands

```bash
# Quick install (one-liner)
curl -fsSL https://raw.githubusercontent.com/tpersp/Eris/main/setup.sh | sudo bash

# Manual install route
# 1. Download the installer
git clone https://github.com/tpersp/Eris.git
cd Eris

# 2. Run interactive setup
chmod +x setup.sh
sudo bash setup.sh
```

The interactive installer will:
- Detect the device type (Pi Zero 2 W, Pi 4 B, or generic Linux)
- Install Chromium, mpv, Python, and other dependencies
- Install Node.js/npm when missing and build the Eris web control UI
- Create the `/opt/eris` virtual environment
- Configure and enable the `eris.service` systemd unit
- Offer to mount an optional Samba media share
- Print the local access URL when setup completes

## Configuration

Configuration lives under `/etc/eris/`:

```
/etc/eris/config.yaml
/etc/eris/chromium_flags
```

Minimal examples:

```yaml
# /etc/eris/config.yaml
api:
  host: 0.0.0.0
  port: 8080
display:
  homepage: https://example.com
  rotation: normal
media:
  local_path: /var/lib/eris/media/local
  cache_path: /var/lib/eris/media/cache
```

```bash
# /etc/eris/chromium_flags
--enable-gpu-rasterization
--no-first-run
--disable-infobars
```

## Service control

```bash
sudo systemctl status eris
sudo systemctl restart eris
sudo journalctl -u eris -f
```

## Testing the installation

```bash
curl http://localhost:8080/api/health
```

The API should return JSON containing uptime information, and the connected display should load the homepage defined in `config.yaml`.

## Updating or uninstalling

Helper scripts live in `scripts/`:

- `scripts/update.sh` pulls the repository, refreshes Python packages inside `/opt/eris/venv`, and restarts the service.
- `scripts/uninstall.sh` stops Eris, removes installed files, and cleans up the systemd unit.

Run them with:

```bash
sudo bash scripts/update.sh
sudo bash scripts/uninstall.sh
```

## Troubleshooting

| Symptom | Fix |
| --- | --- |
| Black screen | Check HDMI connection and Chromium flags in `/etc/eris/chromium_flags` |
| Web UI unreachable | Confirm port 8080 is open (`curl localhost:8080`) |
| Samba share not mounting | Verify the `/etc/fstab` entry and run `sudo mount -a` |
| Daemon crash | Inspect logs with `journalctl -u eris -f` |

## Security note

Set a strong admin password during installation, keep devices on trusted networks, and avoid exposing Eris directly to the public Internet without firewalls or an HTTPS reverse proxy. Pair new controllers through the web UI to ensure only authorized users manage the displays.

**Developer note:** Rebuild the web UI manually with:

```bash
cd /opt/eris/apps/webui
npm install
npm run build
```
