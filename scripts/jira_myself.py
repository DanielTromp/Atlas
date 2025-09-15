import os
import json
import base64
import urllib.request
from urllib.error import HTTPError, URLError


def main() -> int:
    base = os.environ.get("ATLASSIAN_BASE_URL")
    email = os.environ.get("ATLASSIAN_EMAIL")
    token = os.environ.get("ATLASSIAN_API_TOKEN")

    if not base or not email or not token:
        print(json.dumps({"ok": False, "error": "Missing ATLASSIAN_* env vars"}))
        return 0

    url = base.rstrip("/") + "/rest/api/3/myself?expand=groups,applicationRoles"
    req = urllib.request.Request(url)
    creds = (email + ":" + token).encode("utf-8")
    req.add_header("Authorization", "Basic " + base64.b64encode(creds).decode("ascii"))
    req.add_header("Accept", "application/json")

    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            data = json.loads(r.read().decode("utf-8"))
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
    except HTTPError as e:
        body = e.read().decode("utf-8", "ignore") if hasattr(e, "read") else ""
        print(
            json.dumps(
                {"ok": False, "status": getattr(e, "code", None), "reason": getattr(e, "reason", None), "body": body[:2000]}
            )
        )
    except URLError as e:
        print(json.dumps({"ok": False, "error": str(e)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

