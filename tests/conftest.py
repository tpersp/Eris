import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP_PATH = ROOT / "opt/eris/apps"
if APP_PATH.exists() and str(APP_PATH) not in sys.path:
    sys.path.insert(0, str(APP_PATH))

DAEMON_PATH = APP_PATH / "daemon"
if DAEMON_PATH.exists() and str(DAEMON_PATH) not in sys.path:
    sys.path.insert(0, str(DAEMON_PATH))

# Provide lightweight stubs for optional runtime dependencies so unit tests can
# import modules without requiring the full production environment.
import types

if 'websocket' not in sys.modules:
    websocket_stub = types.SimpleNamespace(
        create_connection=lambda *args, **kwargs: None,
        WebSocketException=Exception
    )
    sys.modules['websocket'] = websocket_stub
