import base64
import json
import os
import urllib.parse

import requests


def main() -> int:
    base = os.environ.get("ATLASSIAN_BASE_URL")
    email = os.environ.get("ATLASSIAN_EMAIL")
    token = os.environ.get("ATLASSIAN_API_TOKEN")

    if not base or not email or not token:
        print(json.dumps({"ok": False, "error": "Missing ATLASSIAN_* env vars"}))
        return 0

    url = base.rstrip("/") + "/rest/api/3/myself?expand=groups,applicationRoles"
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        print(json.dumps({"ok": False, "error": f"Unsupported URL scheme: {parsed.scheme}"}))
        return 0
    creds = (email + ":" + token).encode("utf-8")
    headers = {
        "Authorization": "Basic " + base64.b64encode(creds).decode("ascii"),
        "Accept": "application/json",
    }

    try:
        response = requests.get(url, headers=headers, timeout=30)
        response.raise_for_status()
        data = response.json()
        summary = {
            "displayName": data.get("displayName"),
            "accountId": data.get("accountId"),
            "emailAddress": data.get("emailAddress"),
            "timeZone": data.get("timeZone"),
            "locale": data.get("locale"),
            "active": data.get("active"),
            "groups": [g.get("name") for g in (data.get("groups", {}).get("items") or [])],
            "applicationRoles": [x.get("name") for x in (data.get("applicationRoles", {}).get("items") or [])],
        }
        print(json.dumps({"ok": True, "summary": summary}, ensure_ascii=False))
    except requests.HTTPError as e:
        response = e.response
        body = response.text if response is not None else ""
        status = response.status_code if response is not None else None
        reason = response.reason if response is not None else None
        print(json.dumps({"ok": False, "status": status, "reason": reason, "body": body[:2000]}))
    except requests.RequestException as e:
        print(json.dumps({"ok": False, "error": str(e)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
