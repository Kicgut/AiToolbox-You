# Proxy Traffic Monitor

Local dashboard for Clash/Mihomo traffic split between proxy and direct connections.

Auxiliary feature mounted into the primary app (AI Coding Workbench, repo root) via `proxy_traffic_monitor.mount()`/`lifespan()` — see `docs/adr/0002-workbench-root-and-feature-module-layout.md`. It has no standalone entry point of its own; see `docs/architecture.md` in this directory for the full design.

## Prerequisites

1. Enable `external-controller` in Clash Verge / Mihomo (default `127.0.0.1:9090`).
2. If the client uses a secret, copy `config.yaml.example` to `config.yaml` (in this directory) and set `clash_api.secret`.
3. Set `find-process-mode: always` in Clash core config so process names are available.
4. Run the repository root's `run.bat` and open `http://127.0.0.1:8899`.

## Development

Run this feature's tests from the repository root (its own dependencies are merged into the root `requirements.txt`/`requirements-dev.txt`):
```
python -m pytest features/proxy-traffic-monitor/tests -q
```