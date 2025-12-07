# Issue: /search/aggregate doesn't respect module enablement flags

## Problem

The `/search/aggregate` endpoint in `src/infrastructure_atlas/interfaces/api/routes/search.py` does not check the ModuleRegistry before invoking each integration provider. This causes errors when modules are disabled via `ATLAS_MODULE_*_ENABLED` environment variables.

**Current behavior:**
- When Zabbix is disabled, the endpoint still calls `_zabbix_client()` which raises HTTP 400 "Zabbix not configured"
- Same issue affects Jira, Confluence, NetBox, and vCenter
- The module disable flags are ineffective for aggregate search

**Expected behavior:**
- Check `registry.is_enabled("module_name")` before invoking each provider
- Return `{"enabled": False}` for disabled modules instead of attempting to call them
- Gracefully skip disabled modules without errors

## Solution

Add module enablement checks similar to other routes:

```python
from infrastructure_atlas.infrastructure.modules import get_module_registry

@router.get("/aggregate")
def search_aggregate(...):
    registry = get_module_registry()

    # vCenter section
    vcenter_enabled = registry.is_enabled("vcenter")
    if vcenter_enabled and can_view_vcenter and vlimit != 0:
        # ... existing vCenter code ...

    # Zabbix section
    if not registry.is_enabled("zabbix"):
        out["zabbix"] = {"enabled": False}
    else:
        try:
            client = _zabbix_client()
            # ... existing Zabbix code ...
        except HTTPException as ex:
            out["zabbix"] = {"error": ex.detail}
        except Exception as ex:
            out["zabbix"] = {"error": str(ex)}

    # Similar for Jira, Confluence, NetBox
```

## Affected Sections

1. **vCenter** (line ~184): Add `vcenter_enabled` check, add `"enabled": vcenter_enabled` to payload
2. **Zabbix** (line ~252): Wrap in `if not registry.is_enabled("zabbix")` check
3. **Jira** (line ~425): Wrap in `if not registry.is_enabled("jira")` check
4. **Confluence** (line ~440): Wrap in `if not registry.is_enabled("confluence")` check
5. **NetBox** (line ~450): Wrap in `if not registry.is_enabled("netbox")` check

## Notes

- The search router is always registered in `bootstrap_api()` (not conditional)
- Each provider section needs proper indentation when wrapped in the enablement check
- Consider using a helper function to reduce code duplication across sections

## Priority

**Medium** - This is a user-facing issue but has a workaround (don't use aggregate search when modules are disabled). Should be fixed in next refactoring session.

## Related

- Module system: `src/infrastructure_atlas/infrastructure/modules/`
- Bootstrap API: `src/infrastructure_atlas/interfaces/api/__init__.py`
- Other routes properly check module enablement before calling providers
