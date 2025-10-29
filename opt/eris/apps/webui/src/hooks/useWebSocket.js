import { useEffect, useRef } from 'react';

function resolveWsUrl(token) {
  const protocol = window.location.protocol === 'https:' ? 'wss' : 'ws';
  const tokenParam = token ? `?token=${encodeURIComponent(token)}` : '';
  return `${protocol}://${window.location.host}/ws${tokenParam}`;
}

export function useWebSocket(token, callbacks) {
  const callbacksRef = useRef(callbacks);

  useEffect(() => {
    callbacksRef.current = callbacks;
  }, [callbacks]);

  useEffect(() => {
    if (!token) {
      return undefined;
    }

    let isMounted = true;
    let ws;

    const connect = () => {
      ws = new WebSocket(resolveWsUrl(token));

      ws.onopen = () => {
        if (!isMounted) {
          return;
        }
        callbacksRef.current?.onOpen?.();
      };

      ws.onmessage = (event) => {
        if (!isMounted) {
          return;
        }
        try {
          const parsed = JSON.parse(event.data);
          callbacksRef.current?.onMessage?.(parsed);
        } catch (error) {
          console.warn('WS message parse error', error);
        }
      };

      ws.onclose = () => {
        if (!isMounted) {
          return;
        }
        callbacksRef.current?.onClose?.();
        setTimeout(connect, 2500);
      };

      ws.onerror = () => {
        if (!isMounted) {
          return;
        }
        ws.close();
      };
    };

    connect();

    return () => {
      isMounted = false;
      if (ws && ws.readyState === WebSocket.OPEN) {
        ws.close();
      }
    };
  }, [token]);
}
