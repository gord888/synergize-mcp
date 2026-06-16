"""Synergize MCP Server - JSON-RPC over stdio."""

from __future__ import annotations

import asyncio
import json
import sys
import xml.etree.ElementTree as ET
from typing import Any

from synergize_mcp.client import SynergizeClient, Config


TOOLS: list[dict[str, Any]] = []
TOOL_HANDLERS: dict[str, Any] = {}


def tool(name, description, input_schema):
    def decorator(fn):
        TOOLS.append({
            "name": name,
            "description": description,
            "inputSchema": input_schema,
        })
        TOOL_HANDLERS[name] = fn
        return fn
    return decorator


_client = None


def get_client():
    global _client
    if _client is None:
        try:
            config = Config()
        except FileNotFoundError:
            raise RuntimeError(
                "Config not found at ~/.synergize/config.json. See README for setup."
            )
        _client = SynergizeClient(config)
    return _client


def cdata(xml):
    return "<![CDATA[" + xml + "]]>"


def search_array(fields):
    header = "".join("<String>" + k + "</String>" for k in fields)
    values = "".join("<String>" + v + "</String>" for v in fields.values())
    return cdata("<Array><Array>" + header + "</Array><Array>" + values + "</Array></Array>")


# === HEALTH ===

@tool("synergize_ping", "Check if the Synergize server is alive.", {
    "type": "object", "properties": {}, "required": []
})
def synergize_ping():
    c = get_client()
    resp = c.call("PingServer", "")
    code = c._field(resp, "PingServerResult")
    return {"alive": code == "0", "result_code": code}


@tool("synergize_get_service_info",
      "Get Synergize instance name, deployment ID, and product version.",
      {"type": "object", "properties": {}, "required": []})
def synergize_get_service_info():
    c = get_client()
    resp = c.call("GetServiceInfo", "")
    info_xml = c._field(resp, "WebServiceInfo")
    result = {}
    if info_xml:
        rows = c.parse_array(info_xml)
        if rows:
            result["instance_name"] = str(rows[0].get("InstanceName", ""))
            result["deployment_id"] = str(rows[0].get("DeploymentID", ""))
    try:
        resp2 = c.call("GetRepSettings", "<m:Repository>APDOCS</m:Repository>")
        settings_xml = c._field(resp2, "RepositorySettings")
        if settings_xml:
            rows = c.parse_array(settings_xml)
            if rows and "version" in rows[0]:
                result["product_version"] = str(rows[0]["version"])
    except Exception:
        result["product_version"] = "unknown"
    return result


@tool("synergize_get_queues",
      "List workflow queues for a repository with configuration details.",
      {"type": "object", "properties": {
          "repository": {"type": "string", "description": "Repository name"}
      }, "required": ["repository"]})
def synergize_get_queues(repository):
    c = get_client()
    resp = c.call("GetQueuesInfo", "<m:Repository>" + repository + "</m:Repository>")
    ns_env = "http://schemas.xmlsoap.org/soap/envelope/"
    ns_m = "http://microdea.com/"
    body_el = resp.find("{" + ns_env + "}Body")
    resp_el = body_el[0] if body_el is not None and len(body_el) else None
    queues_el = resp_el.find("{" + ns_m + "}queues") if resp_el is not None else None
    if queues_el is None:
        return {"queues": []}
    raw = ET.tostring(queues_el, encoding="unicode")
    import re
    queue_blocks = re.findall(r"<ns0:QueueInfo>(.*?)</ns0:QueueInfo>", raw, re.DOTALL)
    if not queue_blocks:
        queue_blocks = re.findall(r"<QueueInfo>(.*?)</QueueInfo>", raw, re.DOTALL)
    queues = []
    for block in queue_blocks:
        q = {}
        for field in ["RepositoryQueueID", "Name", "Emails", "IsInitial",
                       "IsShared", "ScenarioFamilyID", "Age", "Depth"]:
            m = re.search("<ns0:" + field + ">(.*?)</ns0:" + field + ">", block)
            if not m:
                m = re.search("<" + field + ">(.*?)</" + field + ">", block)
            if m:
                val = m.group(1)
                if field in ("RepositoryQueueID", "ScenarioFamilyID", "Age", "Depth"):
                    q[field] = int(val) if val else 0
                elif field in ("IsInitial", "IsShared"):
                    q[field] = val.lower() == "true"
                else:
                    q[field] = val
        queues.append(q)
    return {"queues": queues}


# === DISCOVERY ===

@tool("synergize_list_repos", "List all available repositories.", {
    "type": "object", "properties": {}, "required": []
})
def synergize_list_repos():
    c = get_client()
    resp = c.call("GetRepositories", "")
    info_xml = c._field(resp, "RepositoriesInfo")
    if not info_xml:
        return {"repositories": []}
    import re
    rows = re.findall(r'<Array\s+Rank="1">(.*?)</Array>', info_xml, re.DOTALL)
    if len(rows) < 2:
        return {"repositories": []}
    server_names = re.findall(r"<String>(.*?)</String>", rows[0])
    repo_names = re.findall(r"<String>(.*?)</String>", rows[1])
    repos = []
    for srv, name in zip(server_names, repo_names):
        repos.append({"server": srv, "name": name})
    return {"repositories": repos}


@tool("synergize_get_schema",
      "Get field names, types, and lengths for a repository.",
      {"type": "object", "properties": {
          "repository": {"type": "string", "description": "Repository name"}
      }, "required": ["repository"]})
def synergize_get_schema(repository):
    c = get_client()
    resp = c.call("GetInfo", "<m:Repository>" + repository + "</m:Repository>")
    info_xml = c._field(resp, "FieldsInfo")
    if not info_xml:
        return {"fields": []}
    import re
    rows = re.findall(r'<Array\s+Rank="1">(.*?)</Array>', info_xml, re.DOTALL)
    if len(rows) < 3:
        return {"fields": []}
    names = re.findall(r"<String>(.*?)</String>", rows[0])
    types = re.findall(r"<String>(.*?)</String>", rows[1])
    lengths = re.findall(r"<Int32>([^<]*)</Int32>", rows[2])
    fields = []
    for i, name in enumerate(names):
        fields.append({
            "name": name,
            "type": types[i] if i < len(types) else "Unknown",
            "length": int(lengths[i]) if i < len(lengths) and lengths[i] else 0,
        })
    return {"fields": fields}


@tool("synergize_get_folders",
      "Browse folder structure in a repository.",
      {"type": "object", "properties": {
          "repository": {"type": "string", "description": "Repository name"}
      }, "required": ["repository"]})
def synergize_get_folders(repository):
    c = get_client()
    resp = c.call("GetRepositoryFolders", "<m:Repository>" + repository + "</m:Repository>")
    code, data, error = c.parse_response_result(resp, "GetRepositoryFolders")
    if not data and error:
        return {"error": error, "folders": []}
    if data:
        return {"folders": c.parse_array(data)}
    return {"folders": []}


@tool("synergize_get_distinct_values",
      "Get distinct values for a field. Useful for auto-complete.",
      {"type": "object", "properties": {
          "repository": {"type": "string", "description": "Repository name"},
          "field": {"type": "string", "description": "Field name"},
          "limit": {"type": "integer", "description": "Max values (default 100)"},
      }, "required": ["repository", "field"]})
def synergize_get_distinct_values(repository, field, limit=100):
    c = get_client()
    body = "<m:Repository>" + repository + "</m:Repository>" + "<m:FieldName>" + field + "</m:FieldName>" + "<m:RecLimit>" + str(limit) + "</m:RecLimit>"
    resp = c.call("GetDistinctFieldValues", body)
    code, data, error = c.parse_response_result(resp, "GetDistinctFieldValues")
    if not data and error:
        return {"error": error, "values": []}
    if data:
        import re
        vals = re.findall(r"<String>(.*?)</String>", data)
        return {"values": vals}
    return {"values": []}


# === SEARCH ===

@tool("synergize_search",
      "Search documents in a repository. Use % as wildcard (SQL LIKE syntax).",
      {"type": "object", "properties": {
          "repository": {"type": "string", "description": "Repository name"},
          "field": {"type": "string", "description": "Field name to search on"},
          "value": {"type": "string", "description": "Search value. Use % for wildcards."},
          "limit": {"type": "integer", "description": "Max records (default 20)"},
      }, "required": ["repository", "field", "value"]})
def synergize_search(repository, field, value, limit=20):
    c = get_client()
    query = search_array({field: value})
    body = "<m:Repository>" + repository + "</m:Repository>" + "<m:Query>" + query + "</m:Query>" + "<m:RecordLimit>" + str(limit) + "</m:RecordLimit>"
    resp = c.call("SearchLike", body)
    code, data, error = c.parse_response_result(resp, "SearchLike")
    if data:
        schema = c.get_schema(repository)
        return {
            "documents": c.parse_positional_array(data, schema),
            "result_code": code,
            "note": error if code != 0 else None,
        }
    return {"error": error or "Result code " + str(code), "documents": [], "result_code": code}


@tool("synergize_validate_query",
      "Validate a search query before executing it.",
      {"type": "object", "properties": {
          "repository": {"type": "string", "description": "Repository name"},
          "field": {"type": "string", "description": "Field name to query on"},
          "value": {"type": "string", "description": "Value to test"},
      }, "required": ["repository", "field", "value"]})
def synergize_validate_query(repository, field, value):
    c = get_client()
    query = search_array({field: value})
    body = "<m:Repository>" + repository + "</m:Repository>" + "<m:Criteria>" + query + "</m:Criteria>"
    resp = c.call("ValidateQuery", body)
    code, data, error = c.parse_response_result(resp, "ValidateQuery")
    return {"valid": code == 0, "result_code": code, "error": error}


# === DOCUMENTS ===

@tool("synergize_get_document",
      "Retrieve a document (PDF or TIF). Returns base64 content. Optionally saves to disk.",
      {"type": "object", "properties": {
          "repository": {"type": "string", "description": "Repository name"},
          "docid": {"type": "string", "description": "Document ID (e.g., Syn423383)"},
          "format": {"type": "string", "description": "Output format: PDF or TIF (default PDF)"},
          "save_path": {"type": "string", "description": "Optional local path to save the file"},
      }, "required": ["repository", "docid"]})
def synergize_get_document(repository, docid, format="PDF", save_path=None):
    c = get_client()
    import base64
    options_xml = (
        "<Array><Array><String>SortField</String><String>SortOrder</String>"
        "<String>DocViewID</String><String>ImageFormat</String></Array>"
        "<Array><String>BillNumber</String><String>ASC</String>"
        "<String>1</String><String>" + format + "</String></Array></Array>"
    )
    body = "<m:Repository>" + repository + "</m:Repository>" + "<m:DocID>" + docid + "</m:DocID>" + "<m:Options>" + cdata(options_xml) + "</m:Options>" + "<m:ChunkMaxSize>-1</m:ChunkMaxSize>"
    resp = c.call("OpenDocument", body)
    code, file_content_b64, error = c.parse_response_result(resp, "OpenDocument")
    result = {"docid": docid, "result_code": code}
    if not file_content_b64:
        result["error"] = error or "No file content"
        return result
    file_bytes = base64.b64decode(file_content_b64)
    result["file_size_bytes"] = len(file_bytes)
    result["file_content_base64"] = file_content_b64
    if save_path:
        with open(save_path, "wb") as f:
            f.write(file_bytes)
        result["saved_to"] = save_path
    return result


@tool("synergize_get_versions",
      "Get version history for a document.",
      {"type": "object", "properties": {
          "repository": {"type": "string", "description": "Repository name"},
          "docid": {"type": "string", "description": "Document ID"},
      }, "required": ["repository", "docid"]})
def synergize_get_versions(repository, docid):
    c = get_client()
    body = "<m:Repository>" + repository + "</m:Repository>" + "<m:DocID>" + docid + "</m:DocID>" + "<m:RecordLimit>20</m:RecordLimit>"
    resp = c.call("GetVersions", body)
    code, data, error = c.parse_response_result(resp, "GetVersions")
    if not data and error:
        return {"error": error, "versions": []}
    if data:
        return {"versions": c.parse_array(data)}
    return {"versions": []}


@tool("synergize_get_cross_refs",
      "Get cross-reference links between documents.",
      {"type": "object", "properties": {
          "repository": {"type": "string", "description": "Repository name"},
          "docid": {"type": "string", "description": "Document ID"},
      }, "required": ["repository", "docid"]})
def synergize_get_cross_refs(repository, docid):
    c = get_client()
    body = "<m:Repository>" + repository + "</m:Repository>" + "<m:DocID>" + docid + "</m:DocID>"
    resp = c.call("GetCrossReferences", body)
    code, data, error = c.parse_response_result(resp, "GetCrossReferences")
    if not data and error:
        return {"error": error, "cross_references": []}
    if data:
        return {"cross_references": c.parse_array(data)}
    return {"cross_references": []}


# === ANNOTATIONS ===

@tool("synergize_get_annotations",
      "Get all annotations (comments/tags) on a document.",
      {"type": "object", "properties": {
          "repository": {"type": "string", "description": "Repository name"},
          "docid": {"type": "string", "description": "Document ID"},
      }, "required": ["repository", "docid"]})
def synergize_get_annotations(repository, docid):
    c = get_client()
    body = "<m:Repository>" + repository + "</m:Repository>" + "<m:DocID>" + docid + "</m:DocID>"
    resp = c.call("GetDocumentAnnotations", body)
    code, data, error = c.parse_response_result(resp, "GetDocumentAnnotations")
    if not data:
        return {"annotations": [], "error": error}
    import re
    raw = data
    cols = re.findall(r'<Array\s+Rank="1">(.*?)</Array>', raw, re.DOTALL)
    if len(cols) < 5:
        return {"annotations": []}
    annotation_ids = re.findall(r"<Int32>([^<]*)</Int32>", cols[1])
    dates = re.findall(r"<Date>([^<]*)</Date>", cols[2])
    users = re.findall(r"<String>(.*?)</String>", cols[3])
    contents = re.findall(r"<String>(.*?)</String>", cols[4])
    annotations = []
    n = len(annotation_ids)
    for i in range(n):
        annotations.append({
            "id": int(annotation_ids[i]) if i < n and annotation_ids[i] else 0,
            "date": dates[i] if i < len(dates) else None,
            "user": users[i] if i < len(users) else None,
            "content": contents[i] if i < len(contents) else None,
        })
    return {"annotations": annotations}


@tool("synergize_add_annotation",
      "Add a comment or tag to a document (e.g., TAG: Reweigh).",
      {"type": "object", "properties": {
          "repository": {"type": "string", "description": "Repository name"},
          "docid": {"type": "string", "description": "Document ID"},
          "content": {"type": "string", "description": "Annotation text"},
      }, "required": ["repository", "docid", "content"]})
def synergize_add_annotation(repository, docid, content):
    c = get_client()
    body = "<m:Repository>" + repository + "</m:Repository>" + "<m:DocID>" + docid + "</m:DocID>" + "<m:Annotation>" + content + "</m:Annotation>"
    resp = c.call("AddDocumentAnnotation", body)
    code = c._field(resp, "AddDocumentAnnotationResult")
    annotation_id = c._field(resp, "AnnotationID")
    error = c._field(resp, "ErrorMsg")
    return {
        "result_code": code,
        "annotation_id": int(annotation_id) if annotation_id else None,
        "error": error,
    }


@tool("synergize_update_annotation",
      "Edit an existing annotation. Requires the annotation stamp for concurrency control.",
      {"type": "object", "properties": {
          "repository": {"type": "string", "description": "Repository name"},
          "annotation_id": {"type": "integer", "description": "Annotation ID to update"},
          "content": {"type": "string", "description": "New annotation text"},
          "annotation_stamp": {"type": "integer", "description": "Current stamp from get_annotations"},
      }, "required": ["repository", "annotation_id", "content", "annotation_stamp"]})
def synergize_update_annotation(repository, annotation_id, content, annotation_stamp):
    c = get_client()
    body = "<m:Repository>" + repository + "</m:Repository>" + "<m:AnnotationID>" + str(annotation_id) + "</m:AnnotationID>" + "<m:Annotation>" + content + "</m:Annotation>" + "<m:AnnotationStamp>" + str(annotation_stamp) + "</m:AnnotationStamp>"
    resp = c.call("UpdateDocumentAnnotation", body)
    code = c._field(resp, "UpdateDocumentAnnotationResult")
    new_stamp = c._field(resp, "AnnotationStamp")
    error = c._field(resp, "ErrorMsg")
    return {
        "result_code": code,
        "new_stamp": int(new_stamp) if new_stamp else None,
        "error": error,
    }


# === WORKFLOW & SECURITY ===

@tool("synergize_get_workflow",
      "Get workflow state transitions for a document.",
      {"type": "object", "properties": {
          "repository": {"type": "string", "description": "Repository name"},
          "docid": {"type": "string", "description": "Document ID"},
      }, "required": ["repository", "docid"]})
def synergize_get_workflow(repository, docid):
    c = get_client()
    body = "<m:Repository>" + repository + "</m:Repository>" + "<m:DocID>" + docid + "</m:DocID>"
    resp = c.call("GetWorkflowLog", body)
    code, data, error = c.parse_response_result(resp, "GetWorkflowLog")
    if not data:
        return {"error": error, "transitions": []}
    import re
    cols = re.findall(r'<Array\s+Rank="1">(.*?)</Array>', data, re.DOTALL)
    def col_vals(col_xml):
        return re.findall(r"<(?:Int32|String|Date)>(.*?)</(?:Int32|String|Date)>", col_xml)
    if len(cols) >= 6:
        ids = col_vals(cols[0])
        from_states = col_vals(cols[1])
        to_states = col_vals(cols[2])
        users = col_vals(cols[3])
        starts = col_vals(cols[4])
        ends = col_vals(cols[5])
        transitions = []
        for i in range(len(ids)):
            transitions.append({
                "entry_id": int(ids[i]) if i < len(ids) else 0,
                "from_state": from_states[i] if i < len(from_states) else None,
                "to_state": to_states[i] if i < len(to_states) else None,
                "user": users[i] if i < len(users) else None,
                "start": starts[i] if i < len(starts) else None,
                "end": ends[i] if i < len(ends) else None,
            })
        return {"transitions": transitions}
    return {"transitions": []}


@tool("synergize_get_document_log",
      "Get audit trail entries for a document.",
      {"type": "object", "properties": {
          "repository": {"type": "string", "description": "Repository name"},
          "docid": {"type": "string", "description": "Document ID"},
      }, "required": ["repository", "docid"]})
def synergize_get_document_log(repository, docid):
    c = get_client()
    body = "<m:Repository>" + repository + "</m:Repository>" + "<m:DocID>" + docid + "</m:DocID>"
    resp = c.call("GetDocumentLog", body)
    code, data, error = c.parse_response_result(resp, "GetDocumentLog")
    if not data and error:
        return {"error": error, "entries": []}
    if data:
        import re
        cols = re.findall(r'<Array\s+Rank="1">(.*?)</Array>', data, re.DOTALL)
        vals_by_col = []
        for col in cols:
            vals_by_col.append(re.findall(r"<(?:String|Date|Empty)>(.*?)</(?:String|Date|Empty)>", col))
        entries = []
        if vals_by_col:
            max_rows = max(len(v) for v in vals_by_col)
            field_names = ["user", "date", "event", "detail"]
            for i in range(max_rows):
                entry = {}
                for j, col in enumerate(vals_by_col):
                    name = field_names[j] if j < len(field_names) else "col" + str(j)
                    entry[name] = col[i] if i < len(col) else None
                entries.append(entry)
        return {"entries": entries}
    return {"entries": []}


@tool("synergize_get_acl",
      "Get access control list for a document.",
      {"type": "object", "properties": {
          "repository": {"type": "string", "description": "Repository name"},
          "docid": {"type": "string", "description": "Document ID"},
      }, "required": ["repository", "docid"]})
def synergize_get_acl(repository, docid):
    c = get_client()
    body = "<m:Repository>" + repository + "</m:Repository>" + "<m:DocID>" + docid + "</m:DocID>"
    resp = c.call("GetACLList", body)
    code, data, error = c.parse_response_result(resp, "GetACLList")
    if not data and error:
        return {"error": error, "acl": []}
    if data:
        import re
        rows = re.findall(r'<Array\s+Rank="1">(.*?)</Array>', data, re.DOTALL)
        if len(rows) >= 2:
            users = re.findall(r"<String>(.*?)</String>", rows[0])
            levels = re.findall(r"<Int32>([^<]*)</Int32>", rows[1])
            acl = []
            n = min(len(users), len(levels))
            for i in range(n):
                acl.append({
                    "user": users[i],
                    "level": int(levels[i]) if levels[i] else 0,
                })
            return {"acl": acl}
    return {"acl": []}


# === JSON-RPC SERVER ===

def handle_request(request):
    req_id = request.get("id")
    method = request.get("method")
    if method == "initialize":
        return {
            "jsonrpc": "2.0", "id": req_id,
            "result": {
                "protocolVersion": "2024-11-05",
                "serverInfo": {"name": "synergize-mcp", "version": "0.1.0"},
                "capabilities": {"tools": {}},
            },
        }
    if method == "notifications/initialized":
        return None
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": req_id, "result": {"tools": TOOLS}}
    if method == "tools/call":
        params = request.get("params", {})
        tool_name = params.get("name", "")
        arguments = params.get("arguments", {})
        handler = TOOL_HANDLERS.get(tool_name)
        if handler is None:
            return {"jsonrpc": "2.0", "id": req_id, "error": {"code": -32601, "message": "Unknown tool: " + tool_name}}
        try:
            result = handler(**arguments)
            return {"jsonrpc": "2.0", "id": req_id, "result": {"content": [{"type": "text", "text": json.dumps(result, default=str, indent=2)}]}}
        except Exception as e:
            return {"jsonrpc": "2.0", "id": req_id, "result": {"content": [{"type": "text", "text": json.dumps({"error": str(e)}, default=str)}]}, "error": {"code": -32000, "message": str(e)}}
    return {"jsonrpc": "2.0", "id": req_id, "error": {"code": -32601, "message": "Method not found: " + str(method)}}


async def run_stdio():
    reader = asyncio.StreamReader()
    protocol = asyncio.StreamReaderProtocol(reader)
    await asyncio.get_event_loop().connect_read_pipe(lambda: protocol, sys.stdin)
    writer_transport, writer_protocol = await asyncio.get_event_loop().connect_write_pipe(
        asyncio.streams.FlowControlMixin, sys.stdout
    )
    writer = asyncio.StreamWriter(writer_transport, writer_protocol, reader, asyncio.get_event_loop())
    buffer = ""
    while True:
        try:
            chunk = await reader.read(65536)
            if not chunk:
                break
            buffer += chunk.decode("utf-8")
            while "\n" in buffer:
                line, buffer = buffer.split("\n", 1)
                line = line.strip()
                if not line:
                    continue
                try:
                    request = json.loads(line)
                except json.JSONDecodeError:
                    continue
                response = handle_request(request)
                if response is not None:
                    resp_bytes = (json.dumps(response) + "\n").encode("utf-8")
                    writer.write(resp_bytes)
                    await writer.drain()
        except asyncio.CancelledError:
            break
        except Exception:
            break


def main():
    asyncio.run(run_stdio())


if __name__ == "__main__":
    main()
