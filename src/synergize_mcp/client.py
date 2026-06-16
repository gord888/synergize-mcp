"""Synergize SOAP client — authentication, envelope construction, XML parsing."""

from __future__ import annotations

import time
import json
import os
import xml.etree.ElementTree as ET
from html import unescape
from typing import Any, Optional

import requests


DEFAULT_CONFIG_PATH = os.path.expanduser("~/.synergize/config.json")
SOAP_NS = "http://microdea.com/"
ENVELOPE_NS = "http://schemas.xmlsoap.org/soap/envelope/"


class Config:
    """Configuration loaded from ~/.synergize/config.json."""

    def __init__(self, path: str = DEFAULT_CONFIG_PATH):
        with open(path) as f:
            data = json.load(f)
        self.base_url: str = data["base_url"]
        self.server_name: str = data["server_name"]
        self.username: str = data["username"]
        self.password: str = data["password"]
        self.timeout: int = data.get("request_timeout", 120)


class SynergizeClient:
    """SOAP client for Synergize SynWebService."""

    def __init__(self, config: Optional[Config] = None):
        self.config = config or Config()
        self._token: Optional[str] = None
        self._token_time: float = 0
        self._schema_cache: dict[str, list[str]] = {}

    @property
    def _auth_header(self) -> str:
        return (
            '<m:AuthHeader>'
            '<m:WebUserName>' + self._xml_escape(self.config.username) + '</m:WebUserName>'
            '<m:WebUserPassword>' + self._xml_escape(self.config.password) + '</m:WebUserPassword>'
            '</m:AuthHeader>'
        )

    def _get_token(self) -> str:
        """Get or reuse a server token. Refreshes if older than 10 minutes."""
        if self._token and (time.time() - self._token_time) < 600:
            return self._token
        body = (
            '<m:GetServerToken>'
            '<m:ServerName>' + self._xml_escape(self.config.server_name) + '</m:ServerName>'
            '<m:ServerToken></m:ServerToken>'
            '<m:ErrorMsg></m:ErrorMsg>'
            '</m:GetServerToken>'
        )
        resp = self._soap_call("GetServerToken", body, use_auth_header=True)
        self._token = self._field(resp, "ServerToken")
        self._token_time = time.time()
        if not self._token:
            raise RuntimeError(
                "GetServerToken failed: " + str(self._field(resp, 'ErrorMsg'))
            )
        return self._token

    def _xml_escape(self, s: str) -> str:
        return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    def _build_envelope(self, body_inner: str, extra_header: str = "") -> str:
        return (
            '<?xml version="1.0" encoding="utf-8"?>'
            '<soap:Envelope xmlns:soap="' + ENVELOPE_NS + '" '
            'xmlns:m="' + SOAP_NS + '">'
            '<soap:Header>' + extra_header + '</soap:Header>'
            '<soap:Body>' + body_inner + '</soap:Body>'
            '</soap:Envelope>'
        )

    def _soap_call(self, action, body_inner, use_auth_header=False):
        hdr = self._auth_header if use_auth_header else ""
        envelope = self._build_envelope(body_inner, hdr)
        resp = requests.post(
            self.config.base_url,
            data=envelope.encode("utf-8"),
            headers={
                "Content-Type": "text/xml; charset=utf-8",
                "SOAPAction": SOAP_NS + action,
            },
            timeout=self.config.timeout,
        )
        resp.raise_for_status()
        return ET.fromstring(resp.text)

    def call(self, action, body_inner, use_token=True, use_auth_header=None):
        """Make a SOAP call. If use_token=True, injects ServerToken first."""
        if use_token:
            token_xml = "<m:ServerToken>" + self._get_token() + "</m:ServerToken>"
            body_inner = token_xml + body_inner
        wrapped = "<m:" + action + ">" + body_inner + "</m:" + action + ">"
        auth = use_auth_header if use_auth_header is not None else use_token
        return self._soap_call(action, wrapped, use_auth_header=auth)

    def get_schema(self, repository):
        """Get or fetch and cache the ordered field names for a repository."""
        if repository in self._schema_cache:
            return self._schema_cache[repository]
        resp = self.call("GetInfo", "<m:Repository>" + repository + "</m:Repository>")
        info_xml = self._field(resp, "FieldsInfo")
        if not info_xml:
            return []
        import re
        rows = re.findall(r'<Array\s+Rank="1">(.*?)</Array>', unescape(info_xml), re.DOTALL)
        if not rows:
            return []
        names = re.findall(r"<String>(.*?)</String>", rows[0])
        self._schema_cache[repository] = names
        return names

    @staticmethod
    def parse_positional_array(xml_str, field_names):
        """Parse a Synergize ArrayRank2 where rows contain typed elements with no header row."""
        if not xml_str:
            return []
        raw = unescape(xml_str)
        import re
        rows = re.findall(r'<Array\s+Rank="1">(.*?)</Array>', raw, re.DOTALL)
        if not rows:
            return []

        def parse_row(row_xml):
            vals = []
            for m in re.finditer(r'<(\w+)(?:\s[^>]*)?>([^<]*?)</\1>|<(\w+)(?:\s[^>]*)?/>', row_xml):
                tag1, text1, tag2 = m.groups()
                tag = tag1 or tag2
                val = (text1 or "").strip()
                if tag in ("String", "Date"):
                    vals.append(val if val else None)
                elif tag in ("Int32", "Int16"):
                    vals.append(int(val) if val else 0)
                elif tag == "Double64":
                    vals.append(float(val) if val else 0.0)
                elif tag == "Bool":
                    vals.append(val == "1" or val.lower() == "true")
                elif tag == "Null":
                    vals.append(None)
                elif tag == "Empty":
                    vals.append("")
            return vals

        data_rows = []
        for row_xml in rows:
            vals = parse_row(row_xml)
            row_dict = {}
            for i, val in enumerate(vals):
                name = field_names[i] if i < len(field_names) else "col" + str(i)
                row_dict[name] = val
            data_rows.append(row_dict)
        return data_rows

    @staticmethod
    def _field(resp, name):
        body = resp.find(".//{" + ENVELOPE_NS + "}Body")
        if body is None:
            return None
        resp_el = body[0] if len(body) else None
        if resp_el is None:
            return None
        el = resp_el.find("{" + SOAP_NS + "}" + name)
        return el.text if el is not None else None

    @staticmethod
    def parse_array(xml_str):
        """Parse a Synergize ArrayRank2 XML string into list of dicts."""
        if not xml_str:
            return []
        raw = unescape(xml_str)
        import re
        rows = re.findall(r'<Array\s+Rank="1">(.*?)</Array>', raw, re.DOTALL)
        if len(rows) < 2:
            return []

        def parse_row(row_xml):
            vals = []
            for m in re.finditer(r'<(/?)' + r'(\w+)' + r'>' + r'([^<]*?)(?=<(?:/?\w+|\w+\s))' + r'', row_xml):
                closing, tag, text = m.groups()
                if closing:
                    continue
                val = text.strip()
                if tag in ("String", "Date"):
                    vals.append(val if val else None)
                elif tag in ("Int32", "Int16"):
                    vals.append(int(val) if val else 0)
                elif tag == "Double64":
                    vals.append(float(val) if val else 0.0)
                elif tag == "Bool":
                    vals.append(val == "1" or val.lower() == "true")
                elif tag == "Null":
                    vals.append(None)
                elif tag == "Empty":
                    vals.append("")
            return vals

        headers = parse_row(rows[0])
        data_rows = []
        for row_xml in rows[1:]:
            vals = parse_row(row_xml)
            row_dict = {}
            for i, h in enumerate(headers):
                row_dict[str(h)] = vals[i] if i < len(vals) else None
            data_rows.append(row_dict)
        return data_rows

    @staticmethod
    def parse_columnar_array(xml_str):
        """Parse transposed ArrayRank2 where each inner array is a COLUMN."""
        if not xml_str:
            return []
        raw = unescape(xml_str)
        import re
        cols = re.findall(r'<Array\s+Rank="1">(.*?)</Array>', raw, re.DOTALL)
        if not cols:
            return []

        def parse_col(col_xml):
            vals = []
            for m in re.finditer(r'<(/?)' + r'(\w+)' + r'>' + r'([^<]*?)(?=<(?:/?\w+|\w+\s))', col_xml):
                closing, tag, text = m.groups()
                if closing:
                    continue
                val = text.strip()
                if tag in ("String", "Date"):
                    vals.append(val if val else None)
                elif tag in ("Int32", "Int16"):
                    vals.append(int(val) if val else 0)
                elif tag == "Double64":
                    vals.append(float(val) if val else 0.0)
                elif tag == "Bool":
                    vals.append(val == "1" or val.lower() == "true")
                elif tag == "Null":
                    vals.append(None)
                elif tag == "Empty":
                    vals.append("")
            return vals

        parsed_cols = [parse_col(c) for c in cols]
        num_rows = max(len(c) for c in parsed_cols) if parsed_cols else 0
        rows = []
        for i in range(num_rows):
            row = {}
            for j, col in enumerate(parsed_cols):
                row["col" + str(j)] = col[i] if i < len(col) else None
            rows.append(row)
        return rows

    def parse_response_result(self, resp, method_name):
        """Extract result code (as int), result data, and error message from a SOAP response."""
        raw_code = self._field(resp, method_name + "Result")
        code = int(raw_code) if raw_code and raw_code.lstrip("-").isdigit() else -999
        error = self._field(resp, "ErrorMsg") or self._field(resp, "ErrorMessage")
        data = self._field(resp, "Result") or self._field(resp, "Documents") or \
               self._field(resp, "WorkflowLog") or self._field(resp, "DocumentLog") or \
               self._field(resp, "Annotations") or self._field(resp, "DocACL") or \
               self._field(resp, "FileContent") or self._field(resp, "RepositoriesInfo") or \
               self._field(resp, "FieldsInfo") or self._field(resp, "Scenarios") or \
               self._field(resp, "WebServiceInfo") or self._field(resp, "FormList") or \
               self._field(resp, "CrossReferences") or self._field(resp, "SearchResults") or \
               self._field(resp, "ScenarioInfo")
        return code, data, error
