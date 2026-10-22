# Security policy

## Reporting a vulnerability

Please report security problems privately through GitHub's private vulnerability reporting: open the repository's **Security** tab and choose **Report a vulnerability** (or go to <https://github.com/Jeevash23/frankenfly/security/advisories/new>). Do not open a public issue, pull request or discussion for an unfixed vulnerability.

Include the version (`backend/pyproject.toml`, or the `application_version` of an export), your operating system, the steps or a proof of concept, and what an attacker gains. The maintainer aims to acknowledge reports within a week. Fixes go into the next release, credited in the changelog unless you prefer otherwise.

Only the latest release is supported with fixes.

## Threat model

DigitalFly is a **local, single-user application**. The server, the simulation and the browser interface all run on your own computer, for you alone. It has no accounts, no authentication, no telemetry and no cloud services; at run time the app contacts nothing outside your computer.

What the app defends against is a web page or another program on your computer trying to drive the local server through your browser. The defenses:

- **Local bind.** The launcher binds to `127.0.0.1` only, with one worker process. Any other address needs the explicit acknowledgement `DIGITALFLY_ALLOW_NETWORK_BIND=1`; the container image sets it because a published port reaches the server through the container's own interface, and it is meant to be published to `127.0.0.1` only (see [docs/INSTALL.md](docs/INSTALL.md#listening-beyond-localhost)).
- **Host check.** Requests must name `127.0.0.1` or `localhost` as their host, which blocks DNS-rebinding attacks. `DIGITALFLY_ALLOWED_ORIGINS` can add exact origins, such as another published port; their host names are then accepted too.
- **Origin allowlist.** Commands that change state (POST, PUT, PATCH, DELETE) and the telemetry WebSocket are refused when they come from a browser origin other than the app itself (`http://127.0.0.1:PORT` or `http://localhost:PORT`, plus the development server on port 5173).
- **JSON only, bounded size.** Commands must be `application/json`, which a cross-site form cannot send without a CORS preflight the server never grants, and bodies are limited (16 KB; 2 MB for connectivity imports).
- **Content Security Policy.** `default-src 'self'`, `script-src 'self'`, `frame-ancestors 'none'` and WebSocket connections only to the local server, plus `X-Content-Type-Options: nosniff` and `Referrer-Policy: no-referrer`.
- **Shutdown** requires the current server instance's random ID, so another page cannot stop your server blind.
- **No paths from the client.** Exports are written only inside `runs/`, under generated names; circuit names are validated against a strict pattern; the circuit builder runs as a subprocess with validated arguments passed as a list, never through a shell.
- **Files are data.** Circuits, run exports, configurations and connectivity imports are parsed and validated, never executed. NumPy archives are loaded without pickle support, and FlyVis checkpoints are loaded weights-only.
- **Verified downloads.** Dependencies install from hashed lockfiles (`--require-hashes`). Data downloads come from pinned URLs over HTTPS and are kept only if their size and SHA-256 match the recorded values; archives with unsafe paths are refused.

## Out of scope

- **Exposing the server to a network.** Binding it to another interface that others can reach, publishing a container port beyond `127.0.0.1`, port forwarding or putting it behind a proxy makes an unauthenticated control API reachable by others; this is not supported.
- **Someone who already controls your user account** or your machine.
- **Scientific validity.** Wrong model results are bugs, not vulnerabilities; please use the issue templates.
- **Vulnerabilities in dependencies** that DigitalFly does not reach in practice. Do tell us if you find one that it does.
