import { useEffect, useRef, useState } from 'react';

const WS_URL = 'ws://127.0.0.1:8000/ws/stream';

export function useStream() {
  const [streamData, setStreamData] = useState({
    frame: null,
    frameSize: [800, 450],
    faces: [],
    message: 'Connecting to attendance stream...',
    counts: { enrolled: 0, eligible: 0, present: 0, remaining: 0 },
    cameraActive: false,
    sessionActive: false,
    sessionId: null,
    error: null,
  });

  const [connected, setConnected] = useState(false);
  const [reconnectAttempt, setReconnectAttempt] = useState(0);
  const wsRef = useRef(null);
  const reconnectTimeoutRef = useRef(null);
  const isMountedRef = useRef(true);

  useEffect(() => {
    isMountedRef.current = true;

    function connect() {
      if (!isMountedRef.current) return;

      try {
        const ws = new WebSocket(WS_URL);
        wsRef.current = ws;

        ws.onopen = () => {
          if (!isMountedRef.current) return;
          setConnected(true);
          setReconnectAttempt(0);
        };

        ws.onmessage = (event) => {
          if (!isMountedRef.current) return;
          try {
            const data = JSON.parse(event.data);
            setStreamData((prev) => ({
              ...prev,
              frame: data.frame,
              frameSize: data.frame_size || prev.frameSize,
              faces: data.faces || [],
              message: data.message || prev.message,
              counts: data.counts || prev.counts,
              cameraActive: data.camera_active,
              sessionActive: data.session_active,
              sessionId: data.session_id,
              error: data.error,
            }));
          } catch (err) {
            console.error('Failed to parse stream packet:', err);
          }
        };

        ws.onerror = (err) => {
          console.warn('WebSocket error:', err);
        };

        ws.onclose = () => {
          if (!isMountedRef.current) return;
          setConnected(false);

          // Exponential backoff reconnect: 1s, 2s, 3s, max 5s
          setReconnectAttempt((prev) => {
            const nextAttempt = prev + 1;
            const delay = Math.min(5000, 1000 * Math.pow(1.3, nextAttempt));
            reconnectTimeoutRef.current = setTimeout(connect, delay);
            return nextAttempt;
          });
        };
      } catch (err) {
        console.error('WebSocket initialization failure:', err);
        reconnectTimeoutRef.current = setTimeout(connect, 2000);
      }
    }

    connect();

    return () => {
      isMountedRef.current = false;
      if (reconnectTimeoutRef.current) {
        clearTimeout(reconnectTimeoutRef.current);
      }
      if (wsRef.current) {
        wsRef.current.close();
      }
    };
  }, []);

  return {
    ...streamData,
    connected,
    reconnecting: !connected && reconnectAttempt > 0,
  };
}
