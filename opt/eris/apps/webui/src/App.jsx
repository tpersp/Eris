import { useCallback, useMemo, useState } from 'react';
import Header from './components/Header.jsx';
import UrlForm from './components/UrlForm.jsx';
import ControlButtons from './components/ControlButtons.jsx';
import StatusCard from './components/StatusCard.jsx';
import { useWebSocket } from './hooks/useWebSocket.js';

const DEFAULT_STATUS = Object.freeze({
  uptime: '--',
  cpu: null,
  mem: null,
  temp: null,
  active_url: '--'
});

async function postJSON(path, payload) {
  const response = await fetch(path, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json'
    },
    body: JSON.stringify(payload)
  });

  if (!response.ok) {
    const text = await response.text();
    throw new Error(text || `Request failed with status ${response.status}`);
  }

  return response.json().catch(() => ({}));
}

function mergeStatus(prev, incoming) {
  if (!incoming) {
    return prev;
  }

  const data = incoming.payload || incoming.data || incoming;
  return {
    uptime: data.uptime ?? prev.uptime,
    cpu: data.cpu ?? prev.cpu,
    mem: data.mem ?? prev.mem,
    temp: data.temp ?? prev.temp,
    active_url: data.active_url ?? data.url ?? prev.active_url
  };
}

export default function App() {
  const [connected, setConnected] = useState(false);
  const [status, setStatus] = useState(DEFAULT_STATUS);
  const [urlInput, setUrlInput] = useState('');
  const [isBlanked, setIsBlanked] = useState(false);
  const [loading, setLoading] = useState(true);
  const [toast, setToast] = useState(null);

  const showToast = useCallback((message, tone = 'info') => {
    setToast({ message, tone, timestamp: Date.now() });
    const timeout = setTimeout(() => setToast(null), 4000);
    return () => clearTimeout(timeout);
  }, []);

  const sendWebAction = useCallback(async (cmd) => {
    try {
      await postJSON('/api/web/action', { cmd });
      showToast(`Command "${cmd}" sent`);
    } catch (error) {
      showToast(error.message || 'Failed to send command', 'error');
    }
  }, [showToast]);

  const handleNavigate = useCallback(async (url) => {
    if (!url) {
      showToast('Please enter a URL', 'error');
      return;
    }

    try {
      await postJSON('/api/web/navigate', { url });
      showToast('Navigation request sent');
    } catch (error) {
      showToast(error.message || 'Failed to navigate', 'error');
    }
  }, [showToast]);

  const toggleBlank = useCallback(async () => {
    const next = !isBlanked;
    setIsBlanked(next);
    try {
      await postJSON('/api/display/blank', { on: next });
      showToast(next ? 'Display blanked' : 'Display restored');
    } catch (error) {
      setIsBlanked(!next);
      showToast(error.message || 'Failed to toggle display', 'error');
    }
  }, [isBlanked, showToast]);

  const handleMessage = useCallback((message) => {
    setStatus((prev) => mergeStatus(prev, message));
    setLoading(false);

    const data = message.payload || message.data || message;

    if (typeof data?.blanked === 'boolean') {
      setIsBlanked(data.blanked);
    } else if (typeof data?.display_blank === 'boolean') {
      setIsBlanked(data.display_blank);
    } else if (typeof data?.display?.blanked === 'boolean') {
      setIsBlanked(data.display.blanked);
    }

    if (typeof (data?.active_url ?? data?.url) === 'string') {
      setUrlInput(data.active_url ?? data.url);
    }
  }, []);

  const handleOpen = useCallback(() => {
    setConnected(true);
    setLoading(false);
    showToast('Connected to device', 'success');
  }, [showToast]);

  const handleClose = useCallback(() => {
    setConnected(false);
    showToast('Connection lost – retrying…', 'error');
  }, [showToast]);

  useWebSocket(
    useMemo(() => ({
      onMessage: handleMessage,
      onOpen: handleOpen,
      onClose: handleClose
    }), [handleMessage, handleOpen, handleClose])
  );

  return (
    <div className="w-full max-w-4xl space-y-6">
      <Header connected={connected} />
      {toast ? (
        <div
          className={`rounded-lg border px-4 py-3 text-sm shadow-sm transition ${
            toast.tone === 'error'
              ? 'border-red-500/60 bg-red-900/40 text-red-100'
              : toast.tone === 'success'
              ? 'border-emerald-500/60 bg-emerald-900/30 text-emerald-100'
              : 'border-slate-500/60 bg-slate-800/60 text-slate-200'
          }`}
        >
          {toast.message}
        </div>
      ) : null}
      <UrlForm
        value={urlInput}
        onChange={setUrlInput}
        onSubmit={handleNavigate}
        disabled={!connected}
      />
      <ControlButtons
        disabled={!connected}
        onBack={() => sendWebAction('back')}
        onForward={() => sendWebAction('forward')}
        onReload={() => sendWebAction('reload')}
        onHome={() => sendWebAction('home')}
        onToggleBlank={toggleBlank}
        isBlanked={isBlanked}
      />
      <StatusCard status={status} connected={connected} loading={loading} />
    </div>
  );
}
