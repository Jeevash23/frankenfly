import {useCallback, useEffect, useRef, useState} from 'react';
import type {State} from './types';
import {describeError} from './errors';
import {isNewer} from './snapshot';

// Commands still waiting for an answer, by path (e.g. 'run', 'reset'), with how many are in flight.
export type Pending = Readonly<Record<string, number>>;

export function useSimulation(enabled = true) {
  const [state, setState] = useState<State | null>(null);
  const [connected, setConnected] = useState(false);
  const [pending, setPending] = useState<Pending>({});
  const [error, setError] = useState<string | null>(null);
  const socket = useRef<WebSocket | null>(null);
  const sent = useRef<Record<string, unknown>>({});
  useEffect(() => {
    if (!enabled) {
      setConnected(false);
      return;
    }
    let closed = false;
    let timer: ReturnType<typeof setTimeout>;
    let retry = 500;
    // While the tab is hidden only the newest message is kept; it is applied when the tab shows again.
    let held: string | null = null;
    const apply = (text: string) => {
      try {
        const next = JSON.parse(text) as State;
        setState((prev) => (isNewer(prev, next) ? next : prev));
      } catch {
        setError('A telemetry message could not be read. Reconnect to the local server.');
      }
    };
    const shown = () => {
      if (document.hidden || held === null) return;
      const text = held;
      held = null;
      apply(text);
    };
    document.addEventListener('visibilitychange', shown);
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
        if (document.hidden) held = e.data;
        else apply(e.data);
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
      document.removeEventListener('visibilitychange', shown);
      socket.current?.close();
    };
  }, [enabled]);

  const count = (path: string, delta: number) =>
    setPending((previous) => {
      const next = {...previous, [path]: (previous[path] ?? 0) + delta};
      if (next[path] <= 0) delete next[path];
      return next;
    });
  const command = useCallback(async (path: string, body?: unknown) => {
    count(path, 1);
    sent.current[path] = body;
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
      if (data.instance_id) setState((prev) => (isNewer(prev, data) ? data : prev));
      return data;
    } catch (e) {
      setError(e instanceof Error ? e.message : 'The local command failed.');
      return null;
    } finally {
      count(path, -1);
      if (sent.current[path] === body) delete sent.current[path];
    }
  }, []);
  // The newest body sent to a command that has not been answered yet, so quick successive edits
  // (two switches, a second reset) build on it instead of on an older snapshot.
  const inFlight = useCallback((path: string): unknown => sent.current[path], []);
  const clearError = useCallback(() => setError(null), []);
  return {state, connected, pending, error, command, inFlight, clearError};
}

// The application version reported by the server, fetched again after a server restart. Null until
// known, or when the server does not report one.
export function useServerVersion(instanceId: string | undefined): string | null {
  const [version, setVersion] = useState<string | null>(null);
  useEffect(() => {
    if (!instanceId) return;
    let cancelled = false;
    fetch('/api/health')
      .then((r) => (r.ok ? r.json() : null))
      .then((data) => {
        if (!cancelled)
          setVersion(typeof data?.version === 'string' && data.version ? data.version : null);
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [instanceId]);
  return version;
}
