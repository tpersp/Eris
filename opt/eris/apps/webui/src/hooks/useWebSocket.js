import { useEffect, useRef } from 'react';

function resolveWsUrl() {
  const protocol = window.location.protocol === 'https:' ? 'wss' : 'ws';
  return `${protocol}://${window.location.host}/ws`;
}

export function useWebSocket(callbacks) {
  const callbacksRef = useRef(callbacks);

  useEffect(() => {
    callbacksRef.current = callbacks;
  }, [callbacks]);

  useEffect(() => {
    let isMounted = true;
    let ws;

    const connect = () => {
      ws = new WebSocket(resolveWsUrl());

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
  }, []);
}
