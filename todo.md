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
- [ ] API implementation for endpoints, DuckDB
  - [x] Initial scaffold: FastAPI app with /health, /devices, /vms; CLI `netbox api serve`; dependencies added.
- [x] Create frontend with a filter- and sortable table
