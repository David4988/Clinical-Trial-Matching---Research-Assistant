"""ONE-TIME, INTERACTIVE. Run this yourself, on your own machine, once, to
obtain a Gmail OAuth refresh token. TrialGuard's application code never runs
this flow itself — it has no browser, and a request must never block on
human consent.

Requires `GMAIL_CLIENT_ID` and `GMAIL_CLIENT_SECRET` already set (from
`.env.local` or the environment) — the OAuth client itself, which the
project already has configured. This script obtains the missing piece:
`GMAIL_REFRESH_TOKEN`.

Run:

    python scripts/gmail_oauth_setup.py

It opens a browser to Google's consent screen, receives the redirect on a
local loopback port, exchanges the authorization code for tokens, and PRINTS
the refresh token to your terminal — it never writes it to any file. Paste
the printed line into `.env.local` yourself:

    GMAIL_REFRESH_TOKEN=<the printed value>

The OAuth client's "Authorized redirect URIs" must include
`http://localhost:8765/` (a Desktop-app OAuth client accepts loopback URIs
on any port; if the client is a Web-app type, add that exact URI in the
Google Cloud Console first).
"""

from __future__ import annotations

import os
import sys
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT.parent / ".env.local")

AUTH_URI = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URI = "https://oauth2.googleapis.com/token"
SCOPE = "https://www.googleapis.com/auth/gmail.send https://www.googleapis.com/auth/gmail.readonly"
REDIRECT_URI = "http://localhost:8765/"

_received_code: str | None = None


class _RedirectHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802 - stdlib method name
        global _received_code
        query = urllib.parse.urlparse(self.path).query
        params = urllib.parse.parse_qs(query)
        _received_code = params.get("code", [None])[0]
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        self.wfile.write(b"Authorization received. You can close this tab and return to the terminal.")

    def log_message(self, *args) -> None:  # silence the default stderr noise
        pass


def main() -> None:
    client_id = os.environ.get("GMAIL_CLIENT_ID", "").strip()
    client_secret = os.environ.get("GMAIL_CLIENT_SECRET", "").strip()
    if not client_id or not client_secret:
        print("GMAIL_CLIENT_ID and GMAIL_CLIENT_SECRET must be set first.", file=sys.stderr)
        raise SystemExit(1)

    auth_url = AUTH_URI + "?" + urllib.parse.urlencode(
        {
            "client_id": client_id,
            "redirect_uri": REDIRECT_URI,
            "response_type": "code",
            "scope": SCOPE,
            "access_type": "offline",
            "prompt": "consent",  # forces a refresh_token even on a re-consent
        }
    )

    print("Opening a browser for Google's consent screen.")
    print("If it does not open automatically, visit this URL manually:\n")
    print(auth_url, "\n")
    webbrowser.open(auth_url)

    server = HTTPServer(("localhost", 8765), _RedirectHandler)
    print(f"Waiting for the redirect on {REDIRECT_URI} ...")
    server.handle_request()  # blocks for exactly one request, then returns

    if not _received_code:
        print("No authorization code received.", file=sys.stderr)
        raise SystemExit(1)

    import httpx

    response = httpx.post(
        TOKEN_URI,
        data={
            "client_id": client_id,
            "client_secret": client_secret,
            "code": _received_code,
            "grant_type": "authorization_code",
            "redirect_uri": REDIRECT_URI,
        },
        timeout=15.0,
    )
    if response.status_code != 200:
        print(f"Token exchange failed: HTTP {response.status_code}: {response.text}", file=sys.stderr)
        raise SystemExit(1)

    body = response.json()
    refresh_token = body.get("refresh_token")
    if not refresh_token:
        print(
            "No refresh_token in the response. This usually means consent "
            "was already granted before without access_type=offline — "
            "revoke TrialGuard's access at https://myaccount.google.com/permissions "
            "and run this script again.",
            file=sys.stderr,
        )
        raise SystemExit(1)

    print("\nSuccess. Add this line to .env.local:\n")
    print(f"GMAIL_REFRESH_TOKEN={refresh_token}\n")


if __name__ == "__main__":
    main()
