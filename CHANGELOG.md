# Changelog

## 1.0.0 — Initial stable release

First stable release of the Synergize MCP server. Provides 21 tools across:

- **Health** — `ping`, `get_service_info`, `get_queues`
- **Discovery** — `list_repos`, `get_schema`, `get_folders`, `get_distinct_values`
- **Search** — `search` (with `%` wildcards), `validate_query`
- **Documents** — `get_document` (PDF/TIF), `get_versions`, `get_cross_refs`
- **Annotations** — `get_annotations`, `add_annotation`, `update_annotation`
- **Workflow & Security** — `get_workflow`, `get_document_log`, `get_acl`
- **BPM Configuration** — `get_workflow_scenarios`, `get_workflow_scenario_info`
- **Storage** — `get_storage_devices`

Highlights:
- Server-token caching (10-minute TTL) and per-repository schema caching.
- Annotation CRUD with concurrency stamps.
- Full BPM scenario introspection (queues, decision questions, routing, DSNs, diagrams).
- Storage device inventory (FTP, LocalFolder, etc.).
