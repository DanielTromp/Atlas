ToDo list
=========================

- [x] Rename get_netbox_data.py to get_netbox_devices.py, and update de code.
- [x] Move the "def netbox_status" logic from the cli.py to a script with the other scripts.
  - [x] Done: extracted to netbox-export/bin/netbox_status.py and wired CLI.
- [x] Move the "def netbox_update" logic from the cli.py to a script with the other scripts.
  - [x] Done: created netbox-export/bin/netbox_update.py and wired CLI. Auto SharePoint publish remains in CLI for now.
- [x] Move the "def sharepoint_upload" logic from the cli.py to a script with the other scripts.
  - [x] Done: created netbox-export/bin/sharepoint_upload.py and wired CLI.
- [x] Move the "def sharepoint_publish_cmdb" logic from the cli.py to a script with the other scripts.
  - [x] Done: created netbox-export/bin/sharepoint_publish_cmdb.py and wired CLI (including auto-publish).
- [x] API implementation for endpoints, DuckDB
  - [x] Initial scaffold: FastAPI app with /health, /devices, /vms; CLI `netbox api serve`; dependencies added.
- [x] Create frontend with a filter- and sortable table
- [ ] Update the CLI log output, make the output for Devices and vms the same, and have the other endpoint output similar. 
- [ ] Add logging to a file and make it viewable in the front ui.

- [ ] Refactor common NetBox helpers into `src/enreach_tools/netbox_common.py` (contacts fetching, incremental update helpers, CSV write util) and reuse in device/VM exporters.
- [ ] Split long functions: extract focused helpers from `netbox-export/bin/get_netbox_devices.py:get_full_device_data` and `netbox-export/bin/get_netbox_vms.py:get_vm_details`.
- [ ] Dynamic VM CSV headers: derive headers from collected VM dicts instead of hardcoding; ensure merge script handles dynamic columns.
- [ ] Batch contact fetching: add batched queries for contact assignments with configurable batch size via `CONTACT_BATCH_SIZE`.
- [ ] Type hints: add comprehensive typing across `src/enreach_tools/` and `netbox-export/bin/` and validate with `mypy`.
- [ ] Error handling: add `src/enreach_tools/exceptions.py`, standardize messages, and add simple retry for transient NetBox/API errors.
- [ ] API caching: add simple caching layer for `/devices`, `/vms`, `/all` responses (in‑memory by default; allow Redis via env).
- [ ] Unit tests: set up pytest and add tests for env loader, CLI wiring, API endpoints, and contact helpers (with mocked NetBox).
- [ ] Logging: centralize logging in `src/enreach_tools/logging.py` and replace prints with structured logs.
- [ ] Documentation: update docstrings and README to reflect shared helpers, config, logging, and API caching.
