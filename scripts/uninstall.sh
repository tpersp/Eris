#!/bin/bash
set -e
systemctl disable --now eris || true
rm -f /etc/systemd/system/eris.service
rm -rf /opt/eris /etc/eris /var/lib/eris
echo "✅ Eris removed."
