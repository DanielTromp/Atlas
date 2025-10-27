#!/usr/bin/env python3
"""Upload or replace an attachment on a Confluence page."""

from __future__ import annotations

import argparse
import mimetypes
import os
from pathlib import Path

from rich import print

from infrastructure_atlas.env import get_env, load_env, project_root
from infrastructure_atlas.infrastructure.external import ConfluenceClient, ConfluenceClientConfig


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


def guess_mimetype(filename: str) -> str:
    mime, _ = mimetypes.guess_type(filename)
    return mime or "application/octet-stream"


def print_attachment_result(attachment) -> None:
    print("[green]Attachment upload complete[/green]")
    if getattr(attachment, "title", None):
        print(f"[bold]Name:[/bold] {attachment.title}")
    if getattr(attachment, "version", None):
        print(f"[bold]Version:[/bold] {attachment.version}")
    if getattr(attachment, "web_url", None):
        print(f"[bold]Open:[/bold] {attachment.web_url}")




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
    client = ConfluenceClient(ConfluenceClientConfig(base_url=base, email=email, api_token=token))

    mime = guess_mimetype(attachment_name)
    comment = args.comment.strip() or None

    print(f"[bold]Uploading:[/bold] {file_path} -> page {page_id} as {attachment_name}")

    existing = client.find_attachment(page_id=page_id, name=attachment_name)
    if existing:
        print(f"[dim]Attachment exists (id {existing.id}); uploading new version[/dim]")
        result = client.replace_attachment(
            page_id=page_id,
            attachment_id=existing.id,
            name=attachment_name,
            data=file_bytes,
            content_type=mime,
            comment=comment,
        )
    else:
        result = client.upload_attachment(
            page_id=page_id,
            name=attachment_name,
            data=file_bytes,
            content_type=mime,
            comment=comment,
        )

    print_attachment_result(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
