#!/bin/bash
set -e
cd /opt/eris
if [ -d .git ]; then
  git fetch --all
  git reset --hard origin/main
fi
source venv/bin/activate
pip install --upgrade eris fastapi "uvicorn[standard]"
systemctl restart eris
echo "✅ Eris updated and restarted."
