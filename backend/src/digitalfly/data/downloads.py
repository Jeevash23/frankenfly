"""Resilient HTTP downloads for the data scripts (fetch_recording.py, fetch_flyvis.py, build_circuit.py).

Network errors and transient HTTP statuses are retried with exponential backoff, and every retry asks only for
the bytes still missing (an HTTP Range request), so an interrupted transfer resumes where it stopped; `download`
also resumes a partial file left by an earlier run. A server that ignores Range sends the whole file again,
which then replaces the partial copy. When the retries run out, or the server refuses the file, DownloadError
carries a one-line message. Nothing here checks content: callers verify size and hashes before keeping a file.
Standard library only.
"""
import http.client
from pathlib import Path
import re
import sys
import time
import urllib.error
import urllib.request

RETRIES = 4
BACKOFF_S = 2.0  # waits 2, 4, 8 and 16 s; the count starts again after an attempt that made progress
TIMEOUT_S = 120
CHUNK = 1 << 20
TRANSIENT = {408, 425, 429, 500, 502, 503, 504}


class DownloadError(Exception):
    """A download that failed for good. str() is one line; `status` is the HTTP status when there was one."""

    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


def _reason(exc) -> str:
    if isinstance(exc, urllib.error.HTTPError):
        return f"HTTP {exc.code} {exc.reason}".strip()
    if isinstance(exc, urllib.error.URLError):
        exc = exc.reason  # the socket error, or a text
    return " ".join((str(exc) or type(exc).__name__).split())


def _start(response, offset: int) -> int:
    """Where the response body starts in the file: `offset` for a matching 206 answer, 0 for a whole file."""
    if response.status != 206:
        return 0
    match = re.match(r"bytes (\d+)-", response.headers.get("Content-Range", ""))
    if not match or int(match.group(1)) != offset:
        raise DownloadError(f"{response.url} answered a range request with {response.headers.get('Content-Range')!r}.")
    return offset


def _length(response) -> int | None:
    try:
        return int(response.headers["Content-Length"])
    except (KeyError, TypeError, ValueError):
        return None


def _retrying(url, attempt, progress, retries, backoff_s, sleep, log):
    # Defaults are read here, so RETRIES and BACKOFF_S can be changed on the module.
    retries, backoff_s = RETRIES if retries is None else retries, BACKOFF_S if backoff_s is None else backoff_s
    sleep = sleep or time.sleep
    failures = 0
    while True:
        before = progress()
        try:
            return attempt()
        except urllib.error.HTTPError as exc:
            if exc.code not in TRANSIENT:
                raise DownloadError(f"{url}: {_reason(exc)}", exc.code) from None
            reason = _reason(exc)
        except (OSError, http.client.HTTPException) as exc:  # URLError, timeouts, resets, truncated bodies
            reason = _reason(exc)
        failures = 1 if progress() > before else failures + 1
        if failures > retries:
            raise DownloadError(f"{url}: {reason} (gave up after {retries} retries)") from None
        wait = backoff_s * 2 ** (failures - 1)
        if log is not None:
            log(f"{reason}; retrying in {wait:g} s ({failures} of {retries}) …")
        sleep(wait)


def _log(message):
    print(message, file=sys.stderr, flush=True)


def download(url: str, path, size: int | None = None, agent: str = "digitalfly", retries: int | None = None,
             backoff_s: float | None = None, timeout: float = TIMEOUT_S, sleep=None, log=_log) -> Path:
    """Stream `url` into `path` (normally a .part file), keeping the bytes already there and asking only for the
    rest. `size`, when known, marks a complete file (a longer one starts over). Returns `path`."""
    path = Path(path)

    def have():
        return path.stat().st_size if path.is_file() else 0

    def attempt():
        offset = have()
        if size is not None and offset >= size:
            if offset == size:
                return path
            path.unlink()
            offset = 0
        headers = {"User-Agent": agent, **({"Range": f"bytes={offset}-"} if offset else {})}
        try:
            response = urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=timeout)
        except urllib.error.HTTPError as exc:
            if exc.code != 416 or not offset:
                raise
            return path  # nothing after `offset`: the server's file ends there (the caller's size check decides)
        with response:
            offset = _start(response, offset)
            expected = _length(response)
            with path.open("ab" if offset else "wb") as output:
                while chunk := response.read(CHUNK):
                    output.write(chunk)
        received = have()
        if (expected is not None and received < offset + expected) or (size is not None and received < size):
            raise ConnectionError(f"the connection closed after {received:,} of {size or offset + expected:,} bytes")
        return path
    return _retrying(url, attempt, have, retries, backoff_s, sleep, log)


def fetch_bytes(url: str, start: int | None = None, end: int | None = None, agent: str = "digitalfly",
                retries: int | None = None, backoff_s: float | None = None, timeout: float = TIMEOUT_S, sleep=None,
                log=_log) -> bytes:
    """The body of `url`, or its bytes [start, end), in memory; retries resume after the bytes received."""
    received = bytearray()

    def attempt():
        first = (start or 0) + len(received)
        ranged = start is not None or bool(received)
        headers = {"User-Agent": agent}
        if ranged:
            headers["Range"] = f"bytes={first}-{'' if end is None else end - 1}"
        with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=timeout) as response:
            if ranged and _start(response, first) != first:
                if start is not None:
                    raise DownloadError(f"{url} does not serve byte ranges (asked for bytes "
                                        f"{start}-{'' if end is None else end - 1}).")
                received.clear()  # the server sent the whole file again
            expected = _length(response)
            before = len(received)
            while chunk := response.read(CHUNK):
                received.extend(chunk)
        if expected is not None and len(received) - before < expected:
            raise ConnectionError(f"the connection closed after {len(received) - before:,} of {expected:,} bytes")
        if start is not None and end is not None and len(received) != end - start:
            raise DownloadError(f"Expected {end - start} bytes from {url}, received {len(received)}.")
        return bytes(received)
    return _retrying(url, attempt, lambda: len(received), retries, backoff_s, sleep, log)
