import {describeError} from './errors';

// A JSON request to the local server that answers {ok, status, data} or {ok: false, error}, for
// panels that show their own errors (commands that change the simulation use useSimulation).
export async function request<T = any>(
  method: 'GET' | 'POST' | 'DELETE',
  path: string,
  body?: unknown,
): Promise<{ok: true; status: number; data: T} | {ok: false; status: number; error: string}> {
  try {
    const response = await fetch(path, {
      method,
      headers: method === 'GET' ? undefined : {'Content-Type': 'application/json'},
      body: method === 'GET' ? undefined : JSON.stringify(body ?? {}),
      signal: AbortSignal.timeout(30000),
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok)
      return {
        ok: false,
        status: response.status,
        error: describeError(data.detail, response.status),
      };
    return {ok: true, status: response.status, data};
  } catch {
    return {
      ok: false,
      status: 0,
      error: 'The local server did not answer. Check that it is still running.',
    };
  }
}
