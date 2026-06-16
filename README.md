# Synergize MCP Server

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

MCP (Model Context Protocol) server that wraps the Synergize SynWebService SOAP API. Provides AI agents with structured access to document repositories, search, workflow monitoring, and annotation management.

## Supported Operations

| Category | Tools |
|---|---|
| **Health** | ping, service info (includes version), queue inventory |
| **Discovery** | list repos, get schema, list folders, distinct field values |
| **Search** | search documents with `%` wildcards, validate queries |
| **Documents** | get document (PDF/TIF), get versions, get cross-references |
| **Annotations** | get, add, update annotations (comments/tags) |
| **Workflow** | get workflow log, get document log, get ACL |

## Quick Start

### 1. Create config file

```bash
mkdir -p ~/.synergize
cat > ~/.synergize/config.json << 'EOF'
{
    "base_url": "http://10.62.5.9/SynWebService/Explorer.asmx",
    "server_name": "M-O",
    "username": "M-O\\SYNERGIZEADMIN",
    "password": "1m@ging!00"
}
EOF
chmod 600 ~/.synergize/config.json
```

### 2a. Install via uvx (recommended — zero install)

Add to your opencode or Copilot CLI MCP config:

```json
{
    "mcpServers": {
        "synergize": {
            "command": "uvx",
            "args": ["git+https://github.com/gord888/synergize-mcp.git"]
        }
    }
}
```

### 2b. Install via pipx

```bash
pipx install git+https://github.com/gord888/synergize-mcp.git
```

Then in MCP config:

```json
{
    "mcpServers": {
        "synergize": {
            "command": "synergize-mcp"
        }
    }
}
```

## Tool Reference

### Health
- **`synergize_ping`** — Check if the Synergize server is alive
- **`synergize_get_service_info`** — Get instance name, deployment ID, and product version
- **`synergize_get_queues`** — List workflow queues for a repository with configuration details

### Discovery
- **`synergize_list_repos`** — List all available repositories
- **`synergize_get_schema`** — Get field names, types, and constraints for a repository
- **`synergize_get_folders`** — Browse folder structure in a repository
- **`synergize_get_distinct_values`** — List all distinct values for a given field (e.g., all vendor names)

### Search
- **`synergize_search`** — Search documents by field/value. Use `%` for wildcards (SQL LIKE syntax)
- **`synergize_validate_query`** — Check if a search query is valid before executing it

### Documents
- **`synergize_get_document`** — Retrieve a document as base64 (PDF or TIF). Optionally save to disk
- **`synergize_get_versions`** — Get version history for a document
- **`synergize_get_cross_refs`** — Get cross-reference links between documents

### Annotations (Comments/Tags)
- **`synergize_get_annotations`** — Read all annotations on a document
- **`synergize_add_annotation`** — Add a comment or tag (e.g., `TAG: Reweigh`)
- **`synergize_update_annotation`** — Edit an existing annotation

### Workflow & Security
- **`synergize_get_workflow`** — Get workflow state transitions for a document
- **`synergize_get_document_log`** — Get audit trail entries for a document
- **`synergize_get_acl`** — Who has what access level on a document

## Configuration Reference

```json
{
    "base_url": "http://server/SynWebService/Explorer.asmx",
    "server_name": "M-O",
    "username": "DOMAIN\\Username",
    "password": "your-password",
    "request_timeout": 120
}
```

| Key | Required | Default | Description |
|---|---|---|---|
| `base_url` | Yes | — | SOAP endpoint URL |
| `server_name` | Yes | — | Synergize server name (used in GetServerToken) |
| `username` | Yes | — | Domain\\Username for authentication |
| `password` | Yes | — | Password for authentication |
| `request_timeout` | No | 120 | HTTP request timeout in seconds |

## License

MIT — see LICENSE file.
