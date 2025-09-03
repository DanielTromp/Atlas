#!/usr/bin/env python3
"""
Visit the local Dataset Viewer grid using Playwright or the system browser.

Usage:
  # Open in system browser (no screenshot)
  python scripts/visit_app.py --system --url http://127.0.0.1:8000/app/

  # Headless screenshot via Playwright
  python scripts/visit_app.py --url http://127.0.0.1:8000/app/ --screenshot app.png --headless --delay-ms 1200

Requires (for Playwright mode):
  python -m pip install playwright
  python -m playwright install chromium
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
import webbrowser


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Visit local grid UI with Playwright or system browser")
    parser.add_argument(
        "--system",
        action="store_true",
        help="Open using the system default browser (no screenshot)",
    )
    parser.add_argument(
        "--url",
        default="http://127.0.0.1:8000/app/",
        help="Target URL to open",
    )
    parser.add_argument(
        "--screenshot",
        default="app.png",
        help="Path to write a PNG screenshot (set to '' to skip)",
    )
    parser.add_argument(
        "--headless",
        action="store_true",
        help="Run browser headless (no GUI)",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=15000,
        help="Timeout in ms for page loads and waits",
    )
    parser.add_argument(
        "--delay-ms",
        type=int,
        default=1200,
        help="Extra delay before screenshot (ms)",
    )
    args = parser.parse_args(argv)

    # System browser mode: bypass Playwright entirely
    if args.system:
        print(f"Opening in system browser: {args.url}")
        ok = webbrowser.open(args.url)
        if args.screenshot:
            print("Note: --screenshot is ignored when using --system", file=sys.stderr)
        if not ok:
            print("Warning: webbrowser.open() returned False (browser may not have opened)", file=sys.stderr)
        return 0

    try:
        from playwright.sync_api import sync_playwright
    except Exception:
        print("Playwright is not installed. Install it with:", file=sys.stderr)
        print("  python -m pip install playwright", file=sys.stderr)
        print("  python -m playwright install chromium", file=sys.stderr)
        return 2

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=args.headless)
        context = browser.new_context(viewport={"width": 1440, "height": 900})
        page = context.new_page()
        print(f"Opening {args.url} ...")
        page.goto(args.url, timeout=args.timeout, wait_until="domcontentloaded")
        # Wait for the grid root or tabs to be present if the app loaded
        try:
            page.wait_for_selector("#grid-root, #tabs", timeout=args.timeout)
        except Exception:
            # Fall back to network idle if selectors don't appear in time
            try:
                page.wait_for_load_state("networkidle", timeout=args.timeout)
            except Exception:
                pass

        if args.delay_ms and args.delay_ms > 0:
            # Allow the UI time to render rows after initial ready state
            page.wait_for_timeout(args.delay_ms)

        if args.screenshot:
            out = Path(args.screenshot)
            out.parent.mkdir(parents=True, exist_ok=True)
            page.screenshot(path=str(out), full_page=True)
            print(f"Saved screenshot → {out}")

        context.close()
        browser.close()

    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
