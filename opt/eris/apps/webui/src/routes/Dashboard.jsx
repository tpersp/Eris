import { useCallback, useEffect, useMemo, useState } from 'react';
import ControlButtons from '../components/ControlButtons.jsx';
import StatusCard from '../components/StatusCard.jsx';
import UrlForm from '../components/UrlForm.jsx';
import { useAuth } from '../context/AuthContext.jsx';
import { useApi } from '../hooks/useApi.js';
import { useWebSocket } from '../hooks/useWebSocket.js';

const DEFAULT_STATUS = Object.freeze({
  uptime: '--',
  cpu: null,
  mem: null,
  temp: null,
  url: '',
  mode: 'web',
  media: null,
  services: {},
  player: null
});

function mergeStatus(prev, update) {
  if (!update) {
    return prev;
  }
  return {
    uptime: update.uptime ?? prev.uptime,
    cpu: update.cpu ?? prev.cpu,
    mem: update.mem ?? prev.mem,
    temp: update.temp ?? prev.temp,
    url: update.url ?? prev.url,
    mode: update.mode ?? prev.mode,
    media: update.media ?? prev.media,
    services: update.services ?? prev.services,
    player: update.player ?? prev.player
  };
}

export default function Dashboard() {
  const { token } = useAuth();
  const { request } = useApi();
  const [connected, setConnected] = useState(false);
  const [status, setStatus] = useState(DEFAULT_STATUS);
  const [urlInput, setUrlInput] = useState('');
  const [isBlanked, setIsBlanked] = useState(false);
  const [loading, setLoading] = useState(true);
  const [toast, setToast] = useState(null);

  const showToast = useCallback((message, tone = 'info') => {
    setToast({ message, tone, key: Date.now() });
    const timeout = setTimeout(() => setToast(null), 4000);
    return () => clearTimeout(timeout);
  }, []);

  useEffect(() => {
    let active = true;
    request('/api/state')
      .then((data) => {
        if (!active || !data) {
          return;
        }
        setStatus((prev) => mergeStatus(prev, data));
        setUrlInput(data.url || '');
        const blanked = data.display?.blanked ?? data.blanked ?? false;
        setIsBlanked(Boolean(blanked));
      })
      .catch((error) => {
        console.error('Failed to load state', error);
        showToast('Unable to load device state', 'error');
      })
      .finally(() => {
        if (active) {
          setLoading(false);
        }
      });
    return () => {
      active = false;
    };
  }, [request, showToast]);

  const handleMessage = useCallback((message) => {
    const data = message.payload || message.data || message;
    if (!data) {
      return;
    }
    setStatus((prev) => mergeStatus(prev, data));
    if (typeof data.url === 'string') {
      setUrlInput(data.url);
    }
    if (typeof data.blanked === 'boolean') {
      setIsBlanked(data.blanked);
    } else if (typeof data.display?.blanked === 'boolean') {
      setIsBlanked(data.display.blanked);
    }
  }, []);

  const handleOpen = useCallback(() => {
    setConnected(true);
    if (!loading) {
      showToast('WebSocket connected', 'success');
    }
  }, [loading, showToast]);

  const handleClose = useCallback(() => {
    setConnected(false);
    showToast('Connection lost – retrying…', 'error');
  }, [showToast]);

  useWebSocket(
    token,
    useMemo(
      () => ({
        onMessage: handleMessage,
        onOpen: handleOpen,
        onClose: handleClose
      }),
      [handleMessage, handleOpen, handleClose]
    )
  );

  const wrapAction = useCallback(
    async (fn) => {
      try {
        await fn();
      } catch (error) {
        const message = error?.message || 'Request failed';
        showToast(message, 'error');
      }
    },
    [showToast]
  );

  const navigateTo = useCallback(
    (url) =>
      wrapAction(async () => {
        if (!url) {
          throw new Error('URL required');
        }
        await request('/api/web/navigate', {
          method: 'POST',
          body: JSON.stringify({ url })
        });
        showToast('Navigation requested', 'success');
      }),
    [request, showToast, wrapAction]
  );

  const sendWebAction = useCallback(
    (cmd) =>
      wrapAction(async () => {
        await request('/api/web/action', {
          method: 'POST',
          body: JSON.stringify({ cmd })
        });
        showToast(`Command "${cmd}" sent`, 'success');
      }),
    [request, showToast, wrapAction]
  );

  const toggleBlank = useCallback(() => {
    wrapAction(async () => {
      const next = !isBlanked;
      setIsBlanked(next);
      try {
        await request('/api/display/blank', {
          method: 'POST',
          body: JSON.stringify({ on: next })
        });
        showToast(next ? 'Display blanked' : 'Display restored', 'success');
      } catch (error) {
        setIsBlanked(!next);
        throw error;
      }
    });
  }, [isBlanked, request, showToast, wrapAction]);

  return (
    <div className="space-y-6">
      {toast && (
        <div
          key={toast.key}
          className={`rounded-lg border px-4 py-3 text-sm shadow-sm transition ${
            toast.tone === 'error'
              ? 'border-red-500/60 bg-red-900/30 text-red-100'
              : toast.tone === 'success'
              ? 'border-emerald-500/60 bg-emerald-900/20 text-emerald-200'
              : 'border-slate-600/60 bg-slate-900/60 text-slate-200'
          }`}
        >
          {toast.message}
        </div>
      )}
      <div className="flex items-center justify-between rounded-2xl border border-slate-800/70 bg-slate-900/60 px-5 py-4">
        <div>
          <p className="text-xs uppercase tracking-[0.3em] text-slate-500">Device Link</p>
          <p className="mt-1 text-lg font-semibold text-emerald-300">
            {status.url || 'https://example.com'}
          </p>
        </div>
        <span
          className={`inline-flex items-center gap-2 rounded-full border px-3 py-1 text-xs font-semibold ${
            connected
              ? 'border-emerald-500/70 bg-emerald-500/10 text-emerald-200'
              : 'border-amber-500/70 bg-amber-500/10 text-amber-200'
          }`}
        >
          <span className={`h-2 w-2 rounded-full ${connected ? 'bg-emerald-300' : 'bg-amber-300'}`} />
          {connected ? 'Connected' : 'Reconnecting'}
        </span>
      </div>
      <UrlForm value={urlInput} onChange={setUrlInput} onSubmit={navigateTo} disabled={!connected} />
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
