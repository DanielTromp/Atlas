#!/usr/bin/env python3
"""Upload or replace an attachment on a Confluence page."""

from __future__ import annotations

import argparse
import json
import mimetypes
import os
from pathlib import Path

import requests
from rich import print

from enreach_tools.env import get_env, load_env, project_root


def read_file(path: Path) -> bytes:
    try:
        return path.read_bytes()
    except FileNotFoundError:
        print(f"[red]File not found:[/red] {path}")
        raise SystemExit(1) from None


def ensure_page_id(raw: str | None) -> str:
    if raw:
        return raw.strip()
    print("[red]Missing page identifier[/red]. Pass --page-id or set CONFLUENCE_CMDB_PAGE_ID/CONFLUENCE_PAGE_ID.")
    raise SystemExit(2)



def build_session(base: str, email: str, token: str) -> requests.Session:
    sess = requests.Session()
    sess.auth = (email, token)
    sess.headers.update({"Accept": "application/json"})
    return sess


def guess_mimetype(filename: str) -> str:
    mime, _ = mimetypes.guess_type(filename)
    return mime or "application/octet-stream"


def fetch_attachment_id(session: requests.Session, api_base: str, page_id: str, name: str) -> str | None:
    url = f"{api_base}/rest/api/content/{page_id}/child/attachment"
    params = {"filename": name, "limit": 25}
    try:
        resp = session.get(url, params=params, timeout=30)
    except requests.RequestException as exc:
        print(f"[red]Failed to query attachments:[/red] {exc}")
        raise SystemExit(1) from None
    if resp.status_code != 200:
        print(f"[red]Failed to query attachments ({resp.status_code}):[/red] {resp.text[:200]}")
        raise SystemExit(1)
    data = resp.json()
    for item in data.get("results", []):
        if item.get("title") == name:
            return item.get("id")
    return None


def perform_upload(
    session: requests.Session,
    url: str,
    files: dict,
    comment: str | None,
    action: str,
) -> dict:
    data = {"minorEdit": "true"}
    if comment:
        data["comment"] = comment
    try:
        resp = session.post(url, headers={"X-Atlassian-Token": "nocheck"}, files=files, data=data, timeout=60)
    except requests.RequestException as exc:
        print(f"[red]{action} request failed:[/red] {exc}")
        raise SystemExit(1) from None
    if resp.status_code not in (200, 201):
        print(f"[red]{action} failed ({resp.status_code}):[/red] {resp.text[:400]}")
        raise SystemExit(1)
    return resp.json()


def print_result(payload: dict) -> None:
    results = payload.get("results") or payload.get("version") or {}
    if isinstance(results, list) and results:
        latest = results[0]
    elif isinstance(results, dict):
        latest = results
    else:
        latest = payload
    title = latest.get("title") or payload.get("title")
    version = latest.get("version", {}).get("number") if isinstance(latest.get("version"), dict) else latest.get("version")
    link = None
    links = latest.get("_links") or payload.get("_links") or {}
    if isinstance(links, dict):
        base = links.get("base")
        webui = links.get("webui") or links.get("download")
        if base and webui:
            link = base + webui
    print("[green]Attachment upload complete[/green]")
    if title:
        print(f"[bold]Name:[/bold] {title}")
    if version:
        print(f"[bold]Version:[/bold] {version}")
    if link:
        print(f"[bold]Open:[/bold] {link}")


def main() -> int:
    load_env()

    parser = argparse.ArgumentParser(description="Upload or replace a Confluence attachment")
    parser.add_argument("--file", default="data/Systems CMDB.xlsx", help="Path to local file")
    parser.add_argument("--page-id", default=os.getenv("CONFLUENCE_CMDB_PAGE_ID") or os.getenv("CONFLUENCE_PAGE_ID"), help="Confluence page ID")
    parser.add_argument("--name", default="", help="Attachment name (defaults to source filename)")
    parser.add_argument("--comment", default="", help="Version comment")
    args = parser.parse_args()

    file_path = project_root() / args.file if not os.path.isabs(args.file) else Path(args.file)
    file_bytes = read_file(file_path)
    attachment_name = args.name.strip() or file_path.name
    page_id = ensure_page_id(args.page_id)

    base = get_env("ATLASSIAN_BASE_URL", required=True)
    email = get_env("ATLASSIAN_EMAIL", required=True)
    token = get_env("ATLASSIAN_API_TOKEN", required=True)

    api_base = base.rstrip("/") + "/wiki"
    session = build_session(base, email, token)

    mime = guess_mimetype(attachment_name)
    comment = args.comment.strip() or None

    print(f"[bold]Uploading:[/bold] {file_path} -> page {page_id} as {attachment_name}")

    existing = fetch_attachment_id(session, api_base, page_id, attachment_name)
    files = {"file": (attachment_name, file_bytes, mime)}
    if existing:
        print(f"[dim]Attachment exists (id {existing}); uploading new version[/dim]")
        url = f"{api_base}/rest/api/content/{page_id}/child/attachment/{existing}/data"
        payload = perform_upload(session, url, files, comment, "Attachment replace")
    else:
        url = f"{api_base}/rest/api/content/{page_id}/child/attachment"
        payload = perform_upload(session, url, files, comment, "Attachment upload")

    try:
        print_result(payload)
    except Exception:
        print("[yellow]Upload succeeded but could not parse response[/yellow]")
        print(json.dumps(payload)[:400])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
