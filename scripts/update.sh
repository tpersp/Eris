#!/usr/bin/env bash
set -euo pipefail

echo "🔄 Pulling latest Eris changes from origin/main..."
cd "$(dirname "$0")/.."

git fetch origin main
git checkout main
git pull --ff-only origin main

if [ ! -d "venv" ]; then
  echo "Creating Python virtual environment..."
  python3 -m venv venv
fi

source venv/bin/activate

pip install --upgrade pip wheel setuptools

if [ -f requirements.txt ]; then
  echo "Installing Python dependencies..."
  pip install --upgrade -r requirements.txt
fi

if [ -x setup.sh ]; then
  echo "Syncing system environment..."
  bash setup.sh --deps-only || true
fi

echo "Restarting eris service..."
sudo systemctl restart eris

echo "✅ Eris updated and restarted"
