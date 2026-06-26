# ChatNet

ChatNet is the ChatArch generic network helper package. It owns reusable network and portal/session helpers such as:

- ICMP ping scanning and TCP port scanning;
- URL collection and link checking;
- browser/chromedriver/playwright service URL health checks;
- service URL helpers such as `append_token()` and `ensure_path()`;
- browser-like `requests.Session` setup with common headers;
- state-file backed cookie persistence;
- cookie header parsing/export;
- simple HTML table parsing helpers;
- safe request-spec / curl-preview generation for dry-run workflows.

Application-level campus portal logic belongs in packages such as `ChatECNU`, which depends on ChatNet for generic network and portal helpers.

## Quick start

```bash
pip install -e ".[dev]"
chatnet --help
chatnet links --url https://example.com
python -m pytest -q
```

## Boundary

ChatNet should stay application-neutral. ECNU login, visitor management, ECNU-specific ChatEnv schema, and ECNU CAPTCHA behavior belong in `ChatECNU`, not in ChatNet.
