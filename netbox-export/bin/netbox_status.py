#!/usr/bin/env python3
import os
import sys

import pynetbox
from rich import print

from enreach_tools.env import apply_extra_headers, load_env, require_env


def main():
    # Load env and validate
    load_env()
    require_env(["NETBOX_URL"])  # token may be optional for /api/status/
    url = os.getenv("NETBOX_URL", "").rstrip("/")
    token = os.getenv("NETBOX_TOKEN", "")

    nb = pynetbox.api(url, token=token if token else None)
    apply_extra_headers(nb.http_session)

    status_url = f"{url}/api/status/"
    devices_url = f"{url}/api/dcim/devices/?limit=1"

    print(f"[bold]Base:[/bold] {url}")
    if token:
        print(f"[bold]Auth:[/bold] Token present (len={len(token)})")
    else:
        print("[bold]Auth:[/bold] No token set")

    # Status probe
    try:
        r = nb.http_session.get(status_url, timeout=15)
        print(f"[bold]/api/status/:[/bold] HTTP {r.status_code}")
        ctype = r.headers.get("content-type", "")
        if "json" in ctype:
            try:
                data = r.json()
                keys = ", ".join(list(data.keys())[:8])
                print(f"  JSON keys: {keys}")
                version = data.get("netbox-version") or data.get("version")
                if version:
                    print(f"  Version: {version}")
            except Exception:
                pass
        else:
            snippet = (r.text or "").strip().splitlines()[0:1]
            if snippet:
                print(f"  Response snippet: {snippet[0][:120]}")
    except Exception as e:
        print(f"Error requesting /api/status/: {e}")

    # Token/access probe
    try:
        r2 = nb.http_session.get(devices_url, timeout=15)
        print(f"[bold]/api/dcim/devices/:[/bold] HTTP {r2.status_code}")
        if r2.status_code == 403:
            print("  403 Forbidden: check API token permissions or WAF/Access requirements.")
            snippet = (r2.text or "").strip().replace("\n", " ")
            if snippet:
                print(f"  Response snippet: {snippet[:200]}")
        elif r2.status_code == 200 and "json" in r2.headers.get("content-type", ""):
            try:
                data = r2.json()
                count_hint = data.get("count")
                if count_hint is not None:
                    print(f"  Result: count={count_hint}")
            except Exception:
                pass
        else:
            snippet = (r2.text or "").strip().replace("\n", " ")
            if snippet:
                print(f"  Response snippet: {snippet[:200]}")
    except Exception as e:
        print(f"Error requesting devices: {e}")


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception as e:
        print(f"[red]Unhandled error:[/red] {e}")
        sys.exit(1)

