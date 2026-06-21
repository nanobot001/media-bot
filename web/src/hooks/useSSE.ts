import { useState, useEffect } from 'react';

export interface SSEStatus {
  state: 'idle' | 'running' | 'error';
  uptime: number;
}

export function useSSE(url: string = 'http://localhost:8000/api/stream') {
  const [connected, setConnected] = useState(false);
  const [status, setStatus] = useState<SSEStatus>({ state: 'idle', uptime: 0 });

  useEffect(() => {
    let eventSource: EventSource | null = null;
    let reconnectTimeout: number;

    const connect = () => {
      eventSource = new EventSource(url);

      eventSource.onopen = () => {
        setConnected(true);
      };

      eventSource.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data);
          if (data.type === 'status') {
            setStatus(data.payload);
          }
        } catch (e) {
          console.error('Failed to parse SSE message', e);
        }
      };

      eventSource.onerror = () => {
        setConnected(false);
        eventSource?.close();
        reconnectTimeout = window.setTimeout(connect, 3000);
      };
    };

    connect();

    return () => {
      eventSource?.close();
      clearTimeout(reconnectTimeout);
    };
  }, [url]);

  return { connected, status };
}
