# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

#!/usr/bin/env python3
"""Post-deploy smoke test: check what a customer's browser actually hits.

Server-side health says little about this app: a bad Content-Security-Policy or missing
images leave every AWS resource healthy while the site is broken. This script checks the
deployed site from the outside:

  1. The page's CSP is valid and allows the Cognito and AgentCore endpoints the app uses.
  2. runtime-config.json is served and matches the deployed stack.
  3. Every menu image is served as an image, not as a fallback page.
  4. The agent WebSocket endpoint is reachable and rejects unauthenticated clients.

Usage: python3 smoke_test.py    (reads cdk/backend-outputs.json; stdlib only)
Exits 0 when every check passes, 1 otherwise.
"""

import http.client
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
import uuid

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUTS_FILE = os.path.join(SCRIPT_DIR, "cdk", "backend-outputs.json")
MENU_FILE = os.path.join(SCRIPT_DIR, "data", "menu_items.json")
TIMEOUT_SECONDS = 30

# --- CSP evaluation (CSP Level 3, section 2.3.1 grammar and section 6.7.2 matching) ---

_KEYWORDS = {"'self'", "'none'", "'unsafe-inline'", "'unsafe-eval'", "'strict-dynamic'",
             "'unsafe-hashes'", "'report-sample'", "'wasm-unsafe-eval'"}
_SCHEME_SOURCE = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.-]*:$")
_HOST_SOURCE = re.compile(
    r"^(?:(?P<scheme>[a-zA-Z][a-zA-Z0-9+.-]*)://)?(?P<host>[^:/]+)(?::(?P<port>\d+|\*))?(?P<path>/.*)?$"
)
# A wildcard may only be the whole host or its leftmost label: "*" or "*.example.com".
_HOST_PART = re.compile(r"^(\*|(\*\.)?[a-zA-Z0-9-]+(\.[a-zA-Z0-9-]+)*\.?)$")
_DEFAULT_PORTS = {"http": 80, "https": 443, "ws": 80, "wss": 443}


def parse_csp(header: str) -> dict[str, list[str]]:
    """Split a CSP header into {directive: [source, ...]}."""
    directives = {}
    for part in header.split(";"):
        tokens = part.split()
        if tokens:
            directives.setdefault(tokens[0].lower(), tokens[1:])
    return directives


def _scheme_matches(source_scheme: str, url_scheme: str) -> bool:
    """CSP scheme-part matching, including the allowed secure upgrades."""
    a, b = source_scheme.lower(), url_scheme.lower()
    return a == b or (a == "http" and b == "https") or (a == "ws" and b in ("wss", "http", "https")) \
        or (a == "wss" and b == "https")


def _source_matches(source: str, url: urllib.parse.SplitResult, page_scheme: str) -> bool:
    if source == "*":
        return url.scheme in ("http", "https")
    if _SCHEME_SOURCE.match(source):
        return _scheme_matches(source[:-1], url.scheme)
    m = _HOST_SOURCE.match(source)
    if not m or not _HOST_PART.match(m["host"]):
        return False  # invalid sources are ignored by browsers, so they match nothing
    if not _scheme_matches(m["scheme"] or page_scheme, url.scheme):
        return False
    pattern, host = m["host"].lower(), (url.hostname or "").lower()
    if pattern != "*" and not (host.endswith(pattern[1:]) if pattern.startswith("*.") else host == pattern):
        return False
    if m["port"] != "*":
        wanted = int(m["port"]) if m["port"] else _DEFAULT_PORTS.get(url.scheme)
        if (url.port or _DEFAULT_PORTS.get(url.scheme)) != wanted:
            return False
    return True


def csp_problems(header: str, required_connect_urls: list[str], page_scheme: str = "https") -> list[str]:
    """Return human-readable problems with a CSP; an empty list means it is fine.

    Flags sources browsers silently ignore (like a wildcard in the middle of a host), and
    any required URL that connect-src would block.
    """
    directives = parse_csp(header)
    problems = []
    for directive, sources in directives.items():
        for source in sources:
            if source.lower() in _KEYWORDS or source.startswith(("'nonce-", "'sha")) or _SCHEME_SOURCE.match(source):
                continue
            m = _HOST_SOURCE.match(source)
            if not m or not _HOST_PART.match(m["host"]):
                problems.append(f"{directive}: invalid source {source!r} — browsers ignore it")
    connect_sources = directives.get("connect-src", directives.get("default-src", []))
    for url in required_connect_urls:
        parsed = urllib.parse.urlsplit(url)
        if not any(_source_matches(s, parsed, page_scheme) for s in connect_sources):
            problems.append(f"connect-src blocks {url}")
    return problems


# --- HTTP helpers ---

def _request(url: str, method: str = "GET"):
    req = urllib.request.Request(url, method=method, headers={"User-Agent": "drive-thru-smoke-test"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_SECONDS) as resp:
            return resp.status, resp.headers, resp.read() if method == "GET" else b""
    except urllib.error.HTTPError as err:
        return err.code, err.headers, b""


def _websocket_handshake_status(host: str, path: str) -> int:
    """Send a WebSocket upgrade request with no credentials and return the HTTP status."""
    conn = http.client.HTTPSConnection(host, timeout=TIMEOUT_SECONDS)
    try:
        conn.request("GET", path, headers={
            "Connection": "Upgrade", "Upgrade": "websocket", "Sec-WebSocket-Version": "13",
            "Sec-WebSocket-Key": "c21va2UtdGVzdC1ub25jZQ==",
        })
        return conn.getresponse().status
    finally:
        conn.close()


# --- Checks ---

def main() -> int:
    with open(OUTPUTS_FILE) as f:
        outputs = json.load(f)["BackendStack"]
    site = f"https://{outputs['DistributionDomainName']}"
    runtime_arn = outputs["AgentRuntimeArn"]
    region = runtime_arn.split(":")[3]
    agent_host = f"bedrock-agentcore.{region}.amazonaws.com"
    failures = []

    def check(name: str, problems: list[str]) -> None:
        print(f"{'PASS' if not problems else 'FAIL'}  {name}")
        for problem in problems:
            print(f"      - {problem}")
        failures.extend(problems)

    print(f"Smoke testing {site}\n")

    # 1. Page + CSP
    status, headers, _ = _request(f"{site}/")
    csp = headers.get("Content-Security-Policy", "")
    page = [] if status == 200 else [f"GET / returned HTTP {status}"]
    if not csp:
        page.append("no Content-Security-Policy header")
    else:
        page += csp_problems(csp, [f"https://cognito-idp.{region}.amazonaws.com", f"wss://{agent_host}"])
    check("page loads and its CSP allows Cognito and the agent WebSocket", page)

    # 2. runtime-config.json
    status, _, body = _request(f"{site}/runtime-config.json")
    config_problems = []
    if status != 200:
        config_problems.append(f"HTTP {status}")
    else:
        config = json.loads(body)
        expected = {"userPoolId": outputs["UserPoolId"], "userPoolClientId": outputs["UserPoolClientId"],
                    "agentRuntimeArn": runtime_arn, "awsRegion": region}
        config_problems += [f"{key} is {config.get(key)!r}, stack has {value!r}"
                            for key, value in expected.items() if config.get(key) != value]
    check("runtime-config.json matches the deployed stack", config_problems)

    # 3. Menu images
    with open(MENU_FILE) as f:
        image_paths = sorted({item["imageUrl"] for item in json.load(f) if "imageUrl" in item})
    image_problems = []
    for path in image_paths:
        status, headers, _ = _request(f"{site}/{path}", method="HEAD")
        content_type = headers.get("Content-Type", "")
        if status != 200 or not content_type.startswith("image/"):
            image_problems.append(f"{path}: HTTP {status}, {content_type or 'no content type'}")
    check(f"all {len(image_paths)} menu images are served as images", image_problems)

    # 4. Agent endpoint
    path = (f"/runtimes/{urllib.parse.quote(runtime_arn, safe='')}/ws?qualifier=DEFAULT"
            f"&X-Amzn-Bedrock-AgentCore-Runtime-Session-Id={uuid.uuid4()}")
    status = _websocket_handshake_status(agent_host, path)
    ws_problems = [] if status in (401, 403) else [
        "accepted an unauthenticated WebSocket" if status == 101 else f"unexpected HTTP {status}"]
    check("agent WebSocket is reachable and requires sign-in", ws_problems)

    print(f"\n{'All checks passed.' if not failures else f'{len(failures)} problem(s) found.'}")
    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(main())
