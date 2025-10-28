#!/usr/bin/env bash
set -e

echo "🔄 Updating Eris from origin/main..."
cd "$(dirname "$0")/.."

git fetch origin main
git reset --hard origin/main

if [ ! -d "venv" ]; then
  echo "Creating Python virtual environment..."
  python3 -m venv venv
fi

source venv/bin/activate

pip install --upgrade pip wheel setuptools

if [ -f requirements.txt ]; then
  echo "Installing Python dependencies..."
  pip install -r requirements.txt
fi

if [ -x setup.sh ]; then
  echo "Syncing system environment..."
  bash setup.sh --deps-only || true
fi

echo "Restarting eris service..."
sudo systemctl restart eris

echo "✅ Eris updated and restarted successfully."
