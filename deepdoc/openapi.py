"""OpenAPI/Swagger spec detector and importer.

If the repo has an openapi.json/yaml or swagger.json/yaml, parse it and use it
directly for richer API docs instead of relying on regex detection.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


def find_openapi_specs(repo_root: Path) -> list[Path]:
    """Find all OpenAPI/Swagger spec files in the repo."""
    candidates = [
        "openapi.json", "openapi.yaml", "openapi.yml",
        "swagger.json", "swagger.yaml", "swagger.yml",
        "docs/openapi.json", "docs/openapi.yaml", "docs/openapi.yml",
        "docs/swagger.json", "docs/swagger.yaml", "docs/swagger.yml",
        "api/openapi.json", "api/openapi.yaml", "api/openapi.yml",
        "spec/openapi.json", "spec/openapi.yaml",
    ]
    found = []
    for c in candidates:
        p = repo_root / c
        if p.exists():
            found.append(p)
    return found


def parse_openapi_spec(spec_path: Path) -> dict[str, Any] | None:
    """Parse an OpenAPI/Swagger spec file into a dict."""
    try:
        content = spec_path.read_text(encoding="utf-8")
        if spec_path.suffix == ".json":
            return json.loads(content)
        else:
            try:
                import yaml
                return yaml.safe_load(content)
            except ImportError:
                # Try JSON anyway
                return json.loads(content)
    except Exception:
        return None


def extract_endpoints_from_spec(spec: dict[str, Any]) -> list[dict[str, Any]]:
    """Extract endpoint details from OpenAPI spec.
    Returns enriched endpoint data with schemas, descriptions, etc."""
    endpoints = []
    base_path = ""

    # OpenAPI 3.x
    if "openapi" in spec:
        servers = spec.get("servers", [])
        if servers:
            server_url = str(servers[0].get("url", "") or "").strip()
            if server_url:
                parsed = urlparse(server_url)
                if parsed.scheme or parsed.netloc:
                    base_path = parsed.path.rstrip("/")
                else:
                    base_path = server_url.rstrip("/")

    # Swagger 2.x
    elif "swagger" in spec:
        base_path = spec.get("basePath", "")

    paths = spec.get("paths", {})
    for path, methods in paths.items():
        full_path = base_path + path if not path.startswith("http") else path

        for method, details in methods.items():
            if method.lower() in ("get", "post", "put", "patch", "delete", "head", "options"):
                endpoint = {
                    "method": method.upper(),
                    "path": full_path,
                    "summary": details.get("summary", ""),
                    "description": details.get("description", ""),
                    "operation_id": details.get("operationId", ""),
                    "tags": details.get("tags", []),
                    "parameters": _extract_parameters(details, spec),
                    "request_body": _extract_request_body(details, spec),
                    "responses": _extract_responses(details, spec),
                    "security": details.get("security", spec.get("security", [])),
                    "deprecated": details.get("deprecated", False),
                }
                endpoints.append(endpoint)

    return endpoints


def spec_to_context_string(spec: dict[str, Any]) -> str:
    """Convert an OpenAPI spec into a compact string for LLM context."""
    lines = []
    info = spec.get("info", {})
    lines.append(f"API: {info.get('title', 'Unknown')} v{info.get('version', '?')}")
    if info.get("description"):
        lines.append(f"Description: {info['description'][:200]}")

    endpoints = extract_endpoints_from_spec(spec)
    lines.append(f"\nEndpoints ({len(endpoints)}):")

    for ep in endpoints:
        line = f"  {ep['method']} {ep['path']}"
        if ep["summary"]:
            line += f" — {ep['summary']}"
        lines.append(line)

        if ep["parameters"]:
            for param in ep["parameters"][:5]:
                req = "required" if param.get("required") else "optional"
                lines.append(f"    param: {param['name']} ({param.get('in', '?')}, {param.get('type', '?')}, {req})")

        if ep["request_body"]:
            lines.append(f"    body: {ep['request_body'][:200]}")

        if ep["responses"]:
            for status, resp in list(ep["responses"].items())[:3]:
                lines.append(f"    {status}: {resp[:100]}")

    return "\n".join(lines)


def generate_swagger_ui_html(spec_path_relative: str) -> str:
    """Generate HTML snippet to embed Swagger UI for API playground."""
    return f"""\
<div id="swagger-ui-container"></div>
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/swagger-ui/5.11.0/swagger-ui.min.css">
<script src="https://cdnjs.cloudflare.com/ajax/libs/swagger-ui/5.11.0/swagger-ui-bundle.min.js"></script>
<script src="https://cdnjs.cloudflare.com/ajax/libs/swagger-ui/5.11.0/swagger-ui-standalone-preset.min.js"></script>
<script>
window.onload = function() {{
  SwaggerUIBundle({{
    url: "{spec_path_relative}",
    dom_id: '#swagger-ui-container',
    presets: [SwaggerUIBundle.presets.apis, SwaggerUIStandalonePreset],
    layout: "StandaloneLayout",
    deepLinking: true,
    tryItOutEnabled: true,
  }});
}};
</script>
"""


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _extract_parameters(details: dict, spec: dict) -> list[dict]:
    params = []
    for p in details.get("parameters", []):
        p = _resolve_ref(p, spec)
        params.append({
            "name": p.get("name", "?"),
            "in": p.get("in", "?"),
            "required": p.get("required", False),
            "type": _get_schema_type(p.get("schema", p)),
            "description": p.get("description", ""),
        })
    return params


def _extract_request_body(details: dict, spec: dict) -> str:
    rb = details.get("requestBody", {})
    if not rb:
        return ""
    rb = _resolve_ref(rb, spec)
    content = rb.get("content", {})
    for _media_type, schema_info in content.items():
        schema = _resolve_ref(schema_info.get("schema", {}), spec)
        return json.dumps(schema, indent=2)[:500]
    return ""


def _extract_responses(details: dict, spec: dict) -> dict[str, str]:
    responses = {}
    for status, resp in details.get("responses", {}).items():
        resp = _resolve_ref(resp, spec)
        desc = resp.get("description", "")
        content = resp.get("content", {})
        if content:
            for _media_type, schema_info in content.items():
                schema = _resolve_ref(schema_info.get("schema", {}), spec)
                desc += f" | schema: {json.dumps(schema)[:200]}"
                break
        responses[str(status)] = desc[:300]
    return responses


def _resolve_ref(obj: dict, spec: dict) -> dict:
    """Resolve a $ref pointer."""
    if not isinstance(obj, dict):
        return obj
    ref = obj.get("$ref")
    if not ref or not isinstance(ref, str):
        return obj
    parts = ref.lstrip("#/").split("/")
    resolved = spec
    for part in parts:
        resolved = resolved.get(part, {})
    return resolved if isinstance(resolved, dict) else obj


def _get_schema_type(schema: dict) -> str:
    if not isinstance(schema, dict):
        return "any"
    t = schema.get("type", "")
    if t == "array":
        items = schema.get("items", {})
        return f"array<{_get_schema_type(items)}>"
    if t == "object":
        return "object"
    return t or "any"
