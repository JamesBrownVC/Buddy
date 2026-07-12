"""Open the private local dashboard without exposing its token to a server.

The HUB_SECRET is placed in the URL fragment. Browsers do not send fragments
in HTTP requests; the dashboard moves it into sessionStorage and removes it
from the address bar immediately.
"""
from __future__ import annotations

import os
import urllib.parse
import webbrowser

import config
from security_utils import ensure_env_secret


def main() -> None:
    secret = ensure_env_secret()
    dashboard = os.getenv("DASHBOARD_URL", "http://127.0.0.1:5500/").rstrip("/") + "/"
    url = f"{dashboard}#token={urllib.parse.quote(secret, safe='')}"
    webbrowser.open(url)
    print("Opened the private local Buddy dashboard.")


if __name__ == "__main__":
    main()
