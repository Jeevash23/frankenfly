import {useCallback, useEffect, useRef, useState} from 'react';
import type {State} from './types';
import {describeError} from './errors';

export function useSimulation(enabled = true) {
  const [state, setState] = useState<State | null>(null);
  const [connected, setConnected] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const socket = useRef<WebSocket | null>(null);
  useEffect(() => {
    if (!enabled) {
      setConnected(false);
      return;
    }
    let closed = false;
    let timer: ReturnType<typeof setTimeout>;
    let retry = 500;
    const connect = () => {
      if (closed) return;
      const ws = new WebSocket(
        `${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.host}/api/ws`,
      );
      socket.current = ws;
      ws.onopen = () => {
        setConnected(true);
        retry = 500;
      };
      ws.onmessage = (e) => {
        try {
          const next = JSON.parse(e.data) as State;
          setState((prev) =>
            !prev || prev.instance_id !== next.instance_id || next.revision >= prev.revision
              ? next
              : prev,
          );
        } catch {
          setError('A telemetry message could not be read. Reconnect to the local server.');
        }
      };
      ws.onclose = () => {
        setConnected(false);
        if (!closed) {
          timer = setTimeout(connect, retry);
          retry = Math.min(retry * 2, 5000);
        }
      };
      ws.onerror = () => ws.close();
    };
    connect();
    return () => {
      closed = true;
      clearTimeout(timer);
      socket.current?.close();
    };
  }, [enabled]);

  const command = useCallback(async (path: string, body?: unknown) => {
    setBusy(true);
    setError(null);
    try {
      const response = await fetch(`/api/${path}`, {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(body ?? {}),
        signal: AbortSignal.timeout(30000),
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(describeError(data.detail, response.status));
      if (data.instance_id)
        setState((prev) =>
          !prev || prev.instance_id !== data.instance_id || data.revision >= prev.revision
            ? data
            : prev,
        );
      return data;
    } catch (e) {
      setError(e instanceof Error ? e.message : 'The local command failed.');
      return null;
    } finally {
      setBusy(false);
    }
  }, []);
  return {state, connected, busy, error, command, clearError: () => setError(null)};
}
