import base64
import html
import json
import os
import re
import urllib.request
from urllib.error import HTTPError, URLError


def extract_page_id(s: str) -> str | None:
    # Accept plain numeric ID or URL containing /pages/{id}/
    m = re.search(r"/pages/(\d+)", s)
    if m:
        return m.group(1)
    if re.fullmatch(r"\d+", s):
        return s
    return None


def strip_html(text: str, limit: int = 300) -> str:
    # Very simple HTML tag stripper for small excerpts
    text = re.sub(r"<script[\s\S]*?</script>", " ", text, flags=re.I)
    text = re.sub(r"<style[\s\S]*?</style>", " ", text, flags=re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) > limit:
        return text[:limit].rstrip() + "…"
    return text


def confluence_request(path: str, base_url: str, auth_header: str):
    url = base_url.rstrip("/") + path
    req = urllib.request.Request(url)
    req.add_header("Authorization", auth_header)
    req.add_header("Accept", "application/json")
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


def main() -> int:
    import sys

    if len(sys.argv) < 2:
        print(json.dumps({"ok": False, "error": "Usage: confluence_page_info.py <page_id_or_url>"}))
        return 0

    target = sys.argv[1]
    page_id = extract_page_id(target)
    if not page_id:
        print(json.dumps({"ok": False, "error": "Could not parse Confluence page ID from input"}))
        return 0

    base = os.environ.get("ATLASSIAN_BASE_URL")
    email = os.environ.get("ATLASSIAN_EMAIL")
    token = os.environ.get("ATLASSIAN_API_TOKEN")
    if not base or not email or not token:
        print(json.dumps({"ok": False, "error": "Missing ATLASSIAN_* env vars"}))
        return 0

    # Confluence Cloud REST base lives under /wiki
    wiki_base = base.rstrip("/") + "/wiki"
    auth = "Basic " + base64.b64encode((email + ":" + token).encode("utf-8")).decode("ascii")

    try:
        # Fetch page core details
        page = confluence_request(
            f"/rest/api/content/{page_id}?expand=space,version,metadata.labels,body.view", wiki_base, auth
        )

        # Optional: try to fetch children/attachments counts (best-effort)
        try:
            attachments = confluence_request(
                f"/rest/api/content/{page_id}/child/attachment?limit=25", wiki_base, auth
            )
            attachments_count = attachments.get("size") if isinstance(attachments, dict) else None
        except Exception:
            attachments_count = None

        try:
            children = confluence_request(
                f"/rest/api/content/{page_id}/child/page?limit=25", wiki_base, auth
            )
            children_count = children.get("size") if isinstance(children, dict) else None
        except Exception:
            children_count = None

        title = page.get("title")
        space = page.get("space") or {}
        version = page.get("version") or {}
        labels = (page.get("metadata", {}).get("labels", {}).get("results") or [])
        body_view_html = page.get("body", {}).get("view", {}).get("value", "")

        summary = {
            "id": page_id,
            "title": title,
            "space": {"key": space.get("key"), "name": space.get("name")},
            "status": page.get("status"),
            "type": page.get("type"),
            "version": {
                "number": version.get("number"),
                "by": (version.get("by") or {}).get("displayName"),
                "when": version.get("when"),
            },
            "labels": [l.get("name") for l in labels if isinstance(l, dict)],
            "attachments_count": attachments_count,
            "children_count": children_count,
            "excerpt": strip_html(body_view_html, 400),
            "url": page.get("_links", {}).get("base") + page.get("_links", {}).get("webui", "")
            if page.get("_links")
            else None,
        }

        print(json.dumps({"ok": True, "summary": summary}, ensure_ascii=False))
    except HTTPError as e:
        body = e.read().decode("utf-8", "ignore") if hasattr(e, "read") else ""
        print(json.dumps({"ok": False, "status": getattr(e, "code", None), "reason": getattr(e, "reason", None), "body": body[:2000]}))
    except URLError as e:
        print(json.dumps({"ok": False, "error": str(e)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

