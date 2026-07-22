# Proxy Traffic Monitor

Local dashboard for Clash/Mihomo traffic split between proxy and direct connections.

## Prerequisites

1. Enable `external-controller` in Clash Verge / Mihomo (default `127.0.0.1:9090`).
2. If the client uses a secret, copy `config.yaml.example` to `config.yaml` and set `clash_api.secret`.
3. Set `find-process-mode: always` in Clash core config so process names are available.
4. Run `run.bat` and open `http://127.0.0.1:8899`.

## Development

Run tests:
```
pip install -r requirements-dev.txt
pytest
```