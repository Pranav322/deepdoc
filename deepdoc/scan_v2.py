"""V2 Scan Upgrades — Giant-file clustering, endpoint bundles, integration discovery.

Phase 2 of the bucket-based doc pipeline. These run AFTER the basic scan and
BEFORE or DURING the planner, enriching the scan output with:

  2.1 Giant-file clustering: breaks 2000+ line files into feature clusters using
      static symbol extraction + LLM grouping
  2.2 Endpoint evidence bundles: bounded 2-level traversal from handler to evidence
  2.3 Integration discovery: detect external systems from HTTP calls, SDK imports,
      env vars, webhook handlers — normalize aliases via LLM
  2.4 Artifact discovery: expanded setup/deploy/test file detection
"""

from __future__ import annotations

import re
import json
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from rich.console import Console

from .llm import LLMClient
from .parser import parse_file
from .parser.base import ParsedFile, Symbol

console = Console()

IMPORT_FROM_RE = re.compile(r"from\s+([\w.]+)\s+import")
IMPORT_PLAIN_RE = re.compile(r"import\s+([\w.]+)")
JS_FROM_RE = re.compile(r"""from\s+['"]([^'"]+)['"]""")
JS_REQUIRE_RE = re.compile(r"""require\s*\(\s*['"]([^'"]+)['"]\s*\)""")
GO_IMPORT_RE = re.compile(r'"([^"]+)"')
PHP_USE_RE = re.compile(r"use\s+([\w\\]+)")
FILE_EXT_RE = re.compile(r"\.(py|ts|js|tsx|jsx|go|php|mjs|cjs)$")
WORD_TOKEN_RE = re.compile(r"[\w]+")


# ═════════════════════════════════════════════════════════════════════════════
# 2.1  Giant-File Clustering
# ═════════════════════════════════════════════════════════════════════════════

@dataclass
class SymbolCluster:
    """A group of related symbols within a giant file."""
    cluster_name: str                          # e.g. "checkout", "cancel_refund"
    description: str
    symbols: list[str] = field(default_factory=list)       # symbol names
    line_ranges: list[tuple[int, int]] = field(default_factory=list)  # (start, end) per symbol
    related_imports: list[str] = field(default_factory=list)


@dataclass
class GiantFileAnalysis:
    """Result of decomposing a giant file into feature clusters."""
    file_path: str
    line_count: int
    total_symbols: int
    clusters: list[SymbolCluster] = field(default_factory=list)


def cluster_giant_file(
    file_path: str,
    parsed: ParsedFile,
    content: str,
    llm: LLMClient,
) -> GiantFileAnalysis:
    """Break a giant file into feature clusters using static extraction + LLM grouping.

    1. Extract structured symbol inventory from the parser output
    2. Send the inventory to the LLM for business-domain clustering
    3. Return clusters with symbol assignments and line ranges
    """
    line_count = len(content.splitlines())
    symbols = parsed.symbols
    imports = parsed.imports

    if not symbols:
        # Nothing to cluster — return a single cluster with the whole file
        return GiantFileAnalysis(
            file_path=file_path,
            line_count=line_count,
            total_symbols=0,
            clusters=[SymbolCluster(
                cluster_name="main",
                description="All content (no symbols detected)",
                symbols=[],
                line_ranges=[(1, line_count)],
            )],
        )

    # Build structured symbol inventory for the LLM
    symbol_inventory = _build_symbol_inventory(symbols, content)
    import_summary = "\n".join(f"- {imp}" for imp in imports[:30])

    prompt = f"""Analyze this giant file ({line_count} lines, {len(symbols)} symbols) and group
the symbols into logical feature clusters based on business domain.

## File: {file_path}

## Imports
{import_summary}

## Symbols
{symbol_inventory}

---

Group these symbols into feature clusters. Each cluster should represent a coherent
business workflow or functional area (e.g. "checkout", "cancel/refund", "status tracking",
"shared utilities").

Rules:
- A symbol should belong to exactly ONE cluster (assign helpers to the cluster that uses them most).
- If a symbol is truly shared across many clusters, put it in a "shared_helpers" cluster.
- Use domain-meaningful cluster names, not generic ones.
- Aim for 3-10 clusters depending on how many distinct concerns the file has.

Return JSON:
{{
  "clusters": [
    {{
      "cluster_name": "checkout",
      "description": "Order checkout and payment processing",
      "symbols": ["process_checkout", "validate_cart", "apply_discount"]
    }},
    {{
      "cluster_name": "shared_helpers",
      "description": "Utility functions used across multiple workflows",
      "symbols": ["calculate_total", "format_currency"]
    }}
  ]
}}"""

    system = "You are a code analysis expert. Group code symbols into business-domain clusters. Respond with valid JSON only."

    try:
        response = llm.complete(system, prompt)
        result = _parse_json(response)
        clusters = _build_clusters_from_llm(result, symbols)
    except Exception as e:
        console.print(f"  [yellow]⚠ LLM clustering failed for {file_path}: {e} — using heuristic[/yellow]")
        clusters = _heuristic_clustering(symbols)

    return GiantFileAnalysis(
        file_path=file_path,
        line_count=line_count,
        total_symbols=len(symbols),
        clusters=clusters,
    )


def _build_symbol_inventory(symbols: list[Symbol], content: str) -> str:
    """Format symbols as a structured inventory for the LLM."""
    lines = []
    for s in symbols:
        size = s.end_line - s.start_line + 1 if s.end_line > 0 else 0
        entry = f"- **{s.kind}** `{s.name}` (lines {s.start_line}-{s.end_line}, {size}L)"
        if s.signature:
            # Show just the signature line, trimmed
            sig = s.signature.strip()[:120]
            entry += f"\n  Signature: `{sig}`"
        if s.docstring:
            entry += f"\n  Doc: {s.docstring[:150]}"
        if s.body_preview:
            # Show first 2 lines of body for context
            preview_lines = s.body_preview.strip().splitlines()[:2]
            preview = " | ".join(l.strip() for l in preview_lines)
            entry += f"\n  Preview: `{preview[:120]}`"
        lines.append(entry)
    return "\n".join(lines)


def _build_clusters_from_llm(result: dict, symbols: list[Symbol]) -> list[SymbolCluster]:
    """Convert LLM clustering result into SymbolCluster objects."""
    # Index symbols by name for line range lookup
    sym_by_name: dict[str, Symbol] = {s.name: s for s in symbols}

    clusters = []
    assigned: set[str] = set()

    for c in result.get("clusters", []):
        cluster_symbols = c.get("symbols", [])
        line_ranges = []
        valid_symbols = []

        for sym_name in cluster_symbols:
            if sym_name in sym_by_name:
                s = sym_by_name[sym_name]
                line_ranges.append((s.start_line, s.end_line))
                valid_symbols.append(sym_name)
                assigned.add(sym_name)

        if valid_symbols:
            clusters.append(SymbolCluster(
                cluster_name=c.get("cluster_name", "unnamed"),
                description=c.get("description", ""),
                symbols=valid_symbols,
                line_ranges=line_ranges,
            ))

    # Catch unassigned symbols
    unassigned = [s.name for s in symbols if s.name not in assigned]
    if unassigned:
        line_ranges = [(sym_by_name[n].start_line, sym_by_name[n].end_line) for n in unassigned if n in sym_by_name]
        clusters.append(SymbolCluster(
            cluster_name="uncategorized",
            description="Symbols not assigned to any cluster by LLM",
            symbols=unassigned,
            line_ranges=line_ranges,
        ))

    return clusters


def _heuristic_clustering(symbols: list[Symbol]) -> list[SymbolCluster]:
    """Fallback: group symbols by name prefix patterns."""
    groups: dict[str, list[Symbol]] = defaultdict(list)

    for s in symbols:
        # Try to extract a prefix: get_order → order, process_checkout → checkout
        name = s.name.lower()
        # Remove common prefixes
        for prefix in ("get_", "set_", "create_", "update_", "delete_", "process_",
                       "validate_", "handle_", "on_", "do_", "is_", "has_", "can_"):
            if name.startswith(prefix):
                name = name[len(prefix):]
                break

        # Take first word as group
        parts = name.split("_")
        group = parts[0] if parts else "misc"
        groups[group].append(s)

    clusters = []
    for group_name, syms in sorted(groups.items(), key=lambda x: -len(x[1])):
        clusters.append(SymbolCluster(
            cluster_name=group_name,
            description=f"Symbols related to {group_name}",
            symbols=[s.name for s in syms],
            line_ranges=[(s.start_line, s.end_line) for s in syms],
        ))

    # Merge tiny clusters (< 2 symbols) into "misc"
    big = [c for c in clusters if len(c.symbols) >= 2]
    small = [c for c in clusters if len(c.symbols) < 2]
    if small:
        misc_symbols = []
        misc_ranges = []
        for c in small:
            misc_symbols.extend(c.symbols)
            misc_ranges.extend(c.line_ranges)
        if misc_symbols:
            big.append(SymbolCluster(
                cluster_name="misc",
                description="Small utility functions and helpers",
                symbols=misc_symbols,
                line_ranges=misc_ranges,
            ))

    return big or clusters


# ═════════════════════════════════════════════════════════════════════════════
# 2.2  Endpoint Evidence Bundles
# ═════════════════════════════════════════════════════════════════════════════

@dataclass
class EvidenceUnit:
    """A single piece of evidence for an endpoint bundle."""
    file_path: str
    role: str       # "handler", "service", "model", "validator", "task", "config", "test", "auth"
    symbols: list[str] = field(default_factory=list)
    relevance: float = 1.0  # 0.0 to 1.0


@dataclass
class EndpointBundle:
    """Evidence bundle for an endpoint or endpoint family."""
    endpoint_family: str            # e.g. "orders" or "POST /orders/process"
    methods_paths: list[str]        # ["POST /orders", "GET /orders/:id"]
    handler_file: str
    handler_symbols: list[str]
    evidence: list[EvidenceUnit] = field(default_factory=list)
    integration_edges: list[str] = field(default_factory=list)  # integration names touched


# Traversal limits
MAX_EVIDENCE_DEPTH = 2
MAX_EVIDENCE_FILES = 15


def build_endpoint_bundles(
    endpoints: list[dict],
    parsed_files: dict[str, ParsedFile],
    file_summaries: dict[str, str],
    repo_root: Path,
) -> list[EndpointBundle]:
    """Build evidence bundles for endpoint families.

    Groups endpoints by resource, then for each family:
    1. Start from handler file
    2. Follow imports 1-2 levels deep
    3. Cap at MAX_EVIDENCE_FILES per bundle
    4. Classify each file by role
    """
    # Group endpoints by resource family
    families: dict[str, list[dict]] = defaultdict(list)
    for ep in endpoints:
        path = ep.get("path", "")
        clean = re.sub(r"^/(?:api/)?(?:v\d+/)?", "", path)
        parts = [p for p in clean.split("/") if p and not p.startswith(":") and not p.startswith("{")]
        resource = parts[0] if parts else "general"
        families[resource].append(ep)

    bundles = []
    all_files = set(parsed_files.keys())
    import_lookup = _build_import_lookup(all_files)

    for resource, eps in families.items():
        # Collect handler files
        handler_files = sorted(set(ep.get("file", "") for ep in eps if ep.get("file")))
        if not handler_files:
            continue

        methods_paths = [f"{ep['method']} {ep['path']}" for ep in eps]
        handler_symbols = [ep.get("handler", "") for ep in eps if ep.get("handler")]

        # Build evidence through bounded import traversal
        evidence: list[EvidenceUnit] = []
        visited: set[str] = set()

        # Level 0: handler files
        for hf in handler_files:
            if hf in visited:
                continue
            visited.add(hf)
            evidence.append(EvidenceUnit(
                file_path=hf,
                role="handler",
                symbols=handler_symbols,
                relevance=1.0,
            ))

        # Level 1: direct imports from handler files
        level1_files: set[str] = set()
        for hf in handler_files:
            parsed = parsed_files.get(hf)
            if not parsed:
                continue
            resolved = _resolve_imports_to_files(parsed.imports, hf, import_lookup)
            level1_files.update(resolved)

        for f in sorted(level1_files):
            if f in visited or len(evidence) >= MAX_EVIDENCE_FILES:
                break
            visited.add(f)
            role = _classify_file_role(f, parsed_files.get(f))
            evidence.append(EvidenceUnit(
                file_path=f,
                role=role,
                relevance=0.8,
            ))

        # Level 2: imports from level-1 files (lower relevance, stricter cap)
        if len(evidence) < MAX_EVIDENCE_FILES:
            level2_files: set[str] = set()
            for f in level1_files:
                parsed = parsed_files.get(f)
                if not parsed:
                    continue
                resolved = _resolve_imports_to_files(parsed.imports, f, import_lookup)
                level2_files.update(resolved)

            for f in sorted(level2_files):
                if f in visited or len(evidence) >= MAX_EVIDENCE_FILES:
                    break
                visited.add(f)
                role = _classify_file_role(f, parsed_files.get(f))
                evidence.append(EvidenceUnit(
                    file_path=f,
                    role=role,
                    relevance=0.5,
                ))

        # Detect integration edges
        integration_edges = _detect_integration_edges_in_bundle(evidence, parsed_files)

        bundles.append(EndpointBundle(
            endpoint_family=resource,
            methods_paths=methods_paths,
            handler_file=handler_files[0] if handler_files else "",
            handler_symbols=handler_symbols,
            evidence=evidence,
            integration_edges=integration_edges,
        ))

    return bundles


def _build_import_lookup(all_files: set[str]) -> dict[str, set[str]]:
    """Pre-index normalized file suffixes so import resolution avoids full scans."""
    lookup: dict[str, set[str]] = defaultdict(set)
    for file_path in all_files:
        normalized = FILE_EXT_RE.sub("", file_path).replace("\\", "/").lower()
        parts = [part for part in normalized.split("/") if part]
        for i in range(len(parts)):
            lookup["/".join(parts[i:])].add(file_path)
        if parts:
            lookup[parts[-1]].add(file_path)
    return lookup


def _resolve_imports_to_files(
    imports: list[str],
    current_file: str,
    import_lookup: dict[str, set[str]],
) -> set[str]:
    """Resolve import statements to actual repo files.

    Uses suffix matching — not perfect but works for 80%+ of cases.
    """
    resolved: set[str] = set()

    for imp in imports:
        # Normalize the import to a path hint
        hints = _normalize_import(imp)
        for hint in hints:
            hint_parts = hint.replace(".", "/").replace("\\", "/").strip("/").lower()
            if not hint_parts:
                continue
            for candidate in import_lookup.get(hint_parts, set()):
                if candidate != current_file:
                    resolved.add(candidate)

    return resolved


def _normalize_import(imp: str) -> list[str]:
    """Extract clean module path hints from an import statement."""
    hints = []

    # Python: from app.services.auth import X
    m = IMPORT_FROM_RE.match(imp)
    if m:
        hints.append(m.group(1).replace(".", "/"))
        return hints

    # Python: import app.services.auth
    m = IMPORT_PLAIN_RE.match(imp)
    if m:
        hints.append(m.group(1).replace(".", "/"))
        return hints

    # JS/TS: import { X } from '../models/user'
    m = JS_FROM_RE.search(imp)
    if m:
        path = m.group(1)
        # Remove ./ ../ prefixes for matching
        path = re.sub(r"^\.{1,2}/", "", path)
        hints.append(path)
        return hints

    # JS/TS: require('./services/payment')
    m = JS_REQUIRE_RE.search(imp)
    if m:
        path = m.group(1)
        path = re.sub(r"^\.{1,2}/", "", path)
        hints.append(path)
        return hints

    # Go: import "github.com/repo/pkg/auth"
    m = GO_IMPORT_RE.search(imp)
    if m:
        hints.append(m.group(1).split("/")[-1])  # just the package name
        return hints

    # PHP: use App\Services\AuthService
    m = PHP_USE_RE.match(imp)
    if m:
        hints.append(m.group(1).replace("\\", "/"))
        return hints

    return hints


def _classify_file_role(file_path: str, parsed: ParsedFile | None) -> str:
    """Classify a file's role based on its path and symbols."""
    path_lower = file_path.lower()

    role_patterns = [
        ("test", ["test", "spec", "__tests__"]),
        ("config", ["config", "settings", ".env"]),
        ("model", ["model", "schema", "entity"]),
        ("validator", ["validator", "validation", "serializer"]),
        ("middleware", ["middleware", "auth"]),
        ("task", ["task", "job", "queue", "worker", "celery"]),
        ("service", ["service"]),
        ("util", ["util", "helper", "lib", "common"]),
    ]

    for role, patterns in role_patterns:
        for p in patterns:
            if p in path_lower:
                return role

    # Check symbols for route decorators
    if parsed and parsed.symbols:
        for s in parsed.symbols:
            if s.kind == "route" or "route" in s.name.lower() or "handler" in s.name.lower():
                return "handler"

    return "service"  # default


def _detect_integration_edges_in_bundle(
    evidence: list[EvidenceUnit],
    parsed_files: dict[str, ParsedFile],
) -> list[str]:
    """Detect integration system names from the evidence files."""
    integration_hints: set[str] = set()

    for eu in evidence:
        parsed = parsed_files.get(eu.file_path)
        if not parsed:
            continue

        # Check imports for known SDK/client patterns
        for imp in parsed.imports:
            imp_lower = imp.lower()
            if any(kw in imp_lower for kw in ("client", "sdk", "api", "http", "request")):
                # Extract a name hint
                parts = WORD_TOKEN_RE.findall(imp)
                for part in parts:
                    if part.lower() not in ("import", "from", "client", "sdk", "api", "http",
                                            "request", "requests", "axios", "fetch", "self"):
                        if len(part) > 2:
                            integration_hints.add(part.lower())

    return sorted(integration_hints)


# ═════════════════════════════════════════════════════════════════════════════
# 2.3  Integration Discovery
# ═════════════════════════════════════════════════════════════════════════════

@dataclass
class IntegrationCandidate:
    """A raw integration signal before normalization."""
    signal_type: str   # "http_client", "sdk_import", "env_var", "webhook", "queue_task", "vendor_constant"
    name_hint: str     # best guess at the integration name
    file_path: str
    evidence: str      # the actual line/import/pattern found
    confidence: float = 0.5


@dataclass
class IntegrationIdentity:
    """A normalized integration after LLM grouping."""
    name: str              # canonical name: "vinculum", "juspay", "delivery_partners"
    display_name: str      # human-readable: "Vinculum Warehouse Management"
    description: str
    files: list[str] = field(default_factory=list)
    evidence: list[str] = field(default_factory=list)
    is_substantial: bool = True  # True = standalone page; False = embed in feature page


def discover_integrations(
    parsed_files: dict[str, ParsedFile],
    file_contents: dict[str, str],
    config_files: list[str],
    repo_root: Path,
    llm: LLMClient | None = None,
) -> list[IntegrationIdentity]:
    """Detect external integrations and normalize into identities.

    1. Static scan for integration signals
    2. LLM grouping to normalize aliases into identities
    """
    # Step 1: Collect raw candidates
    candidates = _collect_integration_candidates(parsed_files, file_contents, config_files, repo_root)

    if not candidates:
        return []

    console.print(f"  [dim]Found {len(candidates)} integration signals across {len(set(c.file_path for c in candidates))} files[/dim]")

    # Step 2: If LLM available, normalize via LLM; otherwise use heuristic
    if llm:
        return _normalize_integrations_llm(candidates, llm)
    else:
        return _normalize_integrations_heuristic(candidates)


def _collect_integration_candidates(
    parsed_files: dict[str, ParsedFile],
    file_contents: dict[str, str],
    config_files: list[str],
    repo_root: Path,
) -> list[IntegrationCandidate]:
    """Scan code for integration signals."""
    candidates: list[IntegrationCandidate] = []

    # Patterns for outbound HTTP calls
    http_patterns = [
        re.compile(r"requests\.(get|post|put|patch|delete)\s*\("),
        re.compile(r"axios\.(get|post|put|patch|delete)\s*\("),
        re.compile(r"fetch\s*\(\s*['\"]https?://"),
        re.compile(r"http\.(?:Get|Post|Put|Delete)\s*\("),
        re.compile(r"httpx\.(?:get|post|put|patch|delete)\s*\("),
        re.compile(r"aiohttp\.ClientSession"),
        re.compile(r"urllib\.request"),
        re.compile(r"Http::(?:get|post|put|patch|delete)\s*\("),
    ]

    # Patterns for SDK/client class instantiation
    sdk_patterns = [
        re.compile(r"(\w+)Client\s*\("),
        re.compile(r"(\w+)SDK\s*\("),
        re.compile(r"(\w+)API\s*\("),
        re.compile(r"(\w+)Gateway\s*\("),
        re.compile(r"(\w+)Provider\s*\("),
        re.compile(r"(\w+)Adapter\s*\("),
    ]

    # Patterns for env vars that suggest integrations
    env_var_patterns = [
        re.compile(r"""(?:os\.environ|os\.getenv|process\.env|env\(|getenv)\s*[\[(]\s*['"](\w*(?:API|URL|KEY|SECRET|TOKEN|HOST|ENDPOINT|WEBHOOK|BASE_URL)\w*)['"]"""),
        re.compile(r"""(\w+_API_(?:KEY|URL|SECRET|TOKEN|BASE_URL|ENDPOINT))"""),
    ]

    # Webhook handler patterns
    webhook_patterns = [
        re.compile(r"webhook", re.IGNORECASE),
        re.compile(r"callback.*(?:url|endpoint|handler)", re.IGNORECASE),
    ]

    for file_path, parsed in parsed_files.items():
        content = file_contents.get(file_path, "")
        if not content:
            continue
        lines = content.splitlines()
        line_starts = [0]
        for line in lines:
            line_starts.append(line_starts[-1] + len(line) + 1)

        # Check imports for client/SDK patterns
        for imp in parsed.imports:
            for pat in sdk_patterns:
                m = pat.search(imp)
                if m:
                    name = m.group(1)
                    if name.lower() not in ("http", "base", "abstract", "mock", "test"):
                        candidates.append(IntegrationCandidate(
                            signal_type="sdk_import",
                            name_hint=name.lower(),
                            file_path=file_path,
                            evidence=imp.strip()[:200],
                            confidence=0.8,
                        ))

        # Check content for outbound HTTP calls
        for pat in http_patterns:
            for m in pat.finditer(content):
                line_num = _line_number_for_offset(line_starts, m.start())
                line = lines[line_num - 1].strip() if line_num <= len(lines) else ""
                # Try to extract URL or target name
                url_match = re.search(r"""['"]https?://([^/'"\s]+)""", content[m.start():m.start() + 300])
                name = url_match.group(1).split(".")[0] if url_match else "unknown_http"
                candidates.append(IntegrationCandidate(
                    signal_type="http_client",
                    name_hint=name.lower(),
                    file_path=file_path,
                    evidence=line[:200],
                    confidence=0.6,
                ))

        # Check for env vars suggesting integrations
        for pat in env_var_patterns:
            for m in pat.finditer(content):
                env_var = m.group(1)
                # Extract the integration name from the env var
                name = re.sub(r"_(?:API|URL|KEY|SECRET|TOKEN|HOST|ENDPOINT|WEBHOOK|BASE_URL).*$", "", env_var)
                if name and name.lower() not in ("app", "db", "database", "redis", "secret", "debug"):
                    candidates.append(IntegrationCandidate(
                        signal_type="env_var",
                        name_hint=name.lower(),
                        file_path=file_path,
                        evidence=env_var,
                        confidence=0.7,
                    ))

        # Check for webhook handlers
        for pat in webhook_patterns:
            for m in pat.finditer(content):
                line_num = _line_number_for_offset(line_starts, m.start())
                line = lines[line_num - 1].strip() if line_num <= len(lines) else ""
                candidates.append(IntegrationCandidate(
                    signal_type="webhook",
                    name_hint="webhook",
                    file_path=file_path,
                    evidence=line[:200],
                    confidence=0.5,
                ))

    # Check symbol names for integration hints
    for file_path, parsed in parsed_files.items():
        for sym in parsed.symbols:
            name_lower = sym.name.lower()
            for suffix in ("client", "gateway", "provider", "adapter", "connector", "sync", "webhook"):
                if suffix in name_lower and name_lower != suffix:
                    prefix = name_lower.replace(suffix, "").strip("_")
                    if prefix and prefix not in ("http", "base", "abstract", "test", "mock"):
                        candidates.append(IntegrationCandidate(
                            signal_type="sdk_import",
                            name_hint=prefix,
                            file_path=file_path,
                            evidence=f"{sym.kind} {sym.name} (line {sym.start_line})",
                            confidence=0.7,
                        ))

    return candidates


def _line_number_for_offset(line_starts: list[int], offset: int) -> int:
    """Map a character offset to a 1-based line number using the cached line starts."""
    lo = 0
    hi = len(line_starts) - 1
    while lo < hi:
        mid = (lo + hi) // 2
        if line_starts[mid] <= offset:
            lo = mid + 1
        else:
            hi = mid
    return max(1, lo)


def _normalize_integrations_llm(
    candidates: list[IntegrationCandidate],
    llm: LLMClient,
) -> list[IntegrationIdentity]:
    """Use LLM to group integration candidates into normalized identities."""
    # Build candidate summary for the LLM
    candidate_lines = []
    for c in candidates:
        candidate_lines.append(f"- [{c.signal_type}] name_hint='{c.name_hint}' file={c.file_path} evidence='{c.evidence}'")

    prompt = f"""Analyze these integration signals and group them into normalized integration identities.

## Raw Integration Signals ({len(candidates)} total)
{chr(10).join(candidate_lines[:80])}
{"... +" + str(len(candidates) - 80) + " more" if len(candidates) > 80 else ""}

---

Group these signals into distinct external integration identities. Merge aliases
(e.g., "vinculum", "warehouse_sync", "VINCULUM_API_URL" → one identity "vinculum").

For each identity, determine if it's substantial enough for a standalone doc page
(appears in multiple files, has meaningful setup/runtime behavior) or should be
embedded in feature docs only.

Return JSON:
{{
  "integrations": [
    {{
      "name": "vinculum",
      "display_name": "Vinculum Warehouse Management",
      "description": "Warehouse management system for inventory sync and order fulfillment",
      "is_substantial": true,
      "candidate_indices": [0, 3, 7, 12]
    }}
  ]
}}

candidate_indices = which signals (by 0-based index) belong to this identity."""

    system = "You are a code analysis expert. Normalize integration signals into identities. Respond with valid JSON only."

    try:
        response = llm.complete(system, prompt)
        result = _parse_json(response)
    except Exception as e:
        console.print(f"  [yellow]⚠ LLM integration normalization failed: {e}[/yellow]")
        return _normalize_integrations_heuristic(candidates)

    identities = []
    for item in result.get("integrations", []):
        indices = item.get("candidate_indices", [])
        files: set[str] = set()
        evidence: list[str] = []

        for idx in indices:
            if 0 <= idx < len(candidates):
                files.add(candidates[idx].file_path)
                evidence.append(candidates[idx].evidence)

        # Also collect files by name match from all candidates
        name = item.get("name", "").lower()
        for c in candidates:
            if name in c.name_hint.lower() or c.name_hint.lower() in name:
                files.add(c.file_path)

        identities.append(IntegrationIdentity(
            name=name,
            display_name=item.get("display_name", name.title()),
            description=item.get("description", ""),
            files=sorted(files),
            evidence=evidence[:10],
            is_substantial=item.get("is_substantial", len(files) >= 3),
        ))

    return identities


def _normalize_integrations_heuristic(
    candidates: list[IntegrationCandidate],
) -> list[IntegrationIdentity]:
    """Fallback: group candidates by name_hint similarity."""
    groups: dict[str, list[IntegrationCandidate]] = defaultdict(list)
    for c in candidates:
        groups[c.name_hint].append(c)

    identities = []
    for name, cands in sorted(groups.items(), key=lambda x: -len(x[1])):
        if name in ("unknown_http", "webhook", "unknown"):
            continue
        files = sorted(set(c.file_path for c in cands))
        identities.append(IntegrationIdentity(
            name=name,
            display_name=name.replace("_", " ").title(),
            description=f"External integration: {name}",
            files=files,
            evidence=[c.evidence for c in cands[:5]],
            is_substantial=len(files) >= 3,
        ))

    return identities


# ═════════════════════════════════════════════════════════════════════════════
# 2.4  Expanded Artifact Discovery
# ═════════════════════════════════════════════════════════════════════════════

@dataclass
class ModelFileInfo:
    """Info about a model/schema definition file."""
    file_path: str
    orm_framework: str        # django, sqlalchemy, prisma, typeorm, sequelize, eloquent, mongoose, gorm, generic
    model_names: list[str] = field(default_factory=list)   # detected class/table names
    is_migration: bool = False


@dataclass
class DatabaseScan:
    """Database/schema discovery results."""
    model_files: list[ModelFileInfo] = field(default_factory=list)
    migration_files: list[str] = field(default_factory=list)
    schema_files: list[str] = field(default_factory=list)    # prisma.schema, schema.graphql, etc.
    orm_framework: str = ""                                   # primary detected ORM
    total_models: int = 0


@dataclass
class ArtifactScan:
    """Categorized artifact discovery results."""
    setup_artifacts: list[str] = field(default_factory=list)
    deploy_artifacts: list[str] = field(default_factory=list)
    test_artifacts: list[str] = field(default_factory=list)
    ci_artifacts: list[str] = field(default_factory=list)
    ops_artifacts: list[str] = field(default_factory=list)
    database_scan: DatabaseScan | None = None


SETUP_PATTERNS = [
    "requirements.txt", "requirements-dev.txt", "requirements-prod.txt",
    "pyproject.toml", "setup.py", "setup.cfg", "Pipfile",
    "package.json", "package-lock.json", "yarn.lock", "pnpm-lock.yaml",
    "go.mod", "go.sum",
    "composer.json", "composer.lock",
    ".env.example", ".env.sample", ".env.template",
    "Makefile", "Taskfile.yml", "justfile",
    "tsconfig.json", "babel.config", "webpack.config",
    ".eslintrc", ".prettierrc", ".editorconfig",
]

DEPLOY_PATTERNS = [
    "Dockerfile", "docker-compose.yml", "docker-compose.yaml", "docker-compose.prod.yml",
    "Procfile", "vercel.json", "netlify.toml", "fly.toml",
    "nginx.conf", "supervisord.conf", "gunicorn.conf",
    "Vagrantfile", "terraform", ".tf",
    "k8s", "kubernetes", "helm",
    "serverless.yml", "sam-template",
]

CI_PATTERNS = [
    ".github/workflows", ".github/actions",
    ".gitlab-ci.yml", "Jenkinsfile", ".circleci",
    ".travis.yml", "bitbucket-pipelines.yml",
    "azure-pipelines.yml", ".buildkite",
]

TEST_PATTERNS = [
    "pytest.ini", "conftest.py", "jest.config",
    "vitest.config", "karma.conf", ".nycrc",
    "phpunit.xml", "codecov.yml",
]

OPS_PATTERNS = [
    "crontab", "celery", "beat", "scheduler",
    "monitoring", "prometheus", "grafana",
    "sentry", "newrelic", "datadog",
    "logrotate", "fluentd", "filebeat",
]


def discover_artifacts(
    repo_root: Path,
    file_tree: dict[str, list[str]],
    parsed_files: dict[str, ParsedFile] | None = None,
    file_contents: dict[str, str] | None = None,
) -> ArtifactScan:
    """Scan the file tree for setup, deploy, test, CI, ops artifacts AND database schema."""
    result = ArtifactScan()

    all_files: list[str] = []
    for dir_path, files in file_tree.items():
        for f in files:
            rel = f"{dir_path}/{f}" if dir_path != "." else f
            all_files.append(rel)

    for rel in all_files:
        fname = rel.split("/")[-1]
        rel_lower = rel.lower()

        for pat in SETUP_PATTERNS:
            if pat.lower() in rel_lower or fnmatch_simple(fname, pat):
                result.setup_artifacts.append(rel)
                break

        for pat in DEPLOY_PATTERNS:
            if pat.lower() in rel_lower or fnmatch_simple(fname, pat):
                result.deploy_artifacts.append(rel)
                break

        for pat in CI_PATTERNS:
            if pat.lower() in rel_lower:
                result.ci_artifacts.append(rel)
                break

        for pat in TEST_PATTERNS:
            if pat.lower() in rel_lower or fnmatch_simple(fname, pat):
                result.test_artifacts.append(rel)
                break

        for pat in OPS_PATTERNS:
            if pat.lower() in rel_lower:
                result.ops_artifacts.append(rel)
                break

    # Database/schema discovery
    if parsed_files and file_contents:
        result.database_scan = discover_database_schema(
            parsed_files, file_contents, file_tree, repo_root
        )

    return result


def discover_database_schema(
    parsed_files: dict[str, ParsedFile],
    file_contents: dict[str, str],
    file_tree: dict[str, list[str]],
    repo_root: Path,
) -> DatabaseScan:
    """Detect ORM model files, migrations, and schema definitions.

    Supports: Django, SQLAlchemy, Prisma, TypeORM, Sequelize, Eloquent,
    Mongoose, GORM, Alembic, and generic model patterns.
    """
    result = DatabaseScan()

    # ORM detection patterns (searched in file content)
    ORM_PATTERNS: dict[str, list[re.Pattern]] = {
        "django": [
            re.compile(r"from django\.db import models"),
            re.compile(r"models\.Model\b"),
            re.compile(r"class \w+\(models\.Model\)"),
        ],
        "sqlalchemy": [
            re.compile(r"from sqlalchemy"),
            re.compile(r"declarative_base\(\)"),
            re.compile(r"class \w+\(.*Base\)"),
            re.compile(r"Column\("),
            re.compile(r"relationship\("),
        ],
        "prisma": [
            re.compile(r"model\s+\w+\s*\{"),
            re.compile(r"datasource\s+\w+\s*\{"),
        ],
        "typeorm": [
            re.compile(r"@Entity\s*\("),
            re.compile(r"@Column\s*\("),
            re.compile(r"@PrimaryGeneratedColumn"),
            re.compile(r"@ManyToOne|@OneToMany|@ManyToMany|@OneToOne"),
        ],
        "sequelize": [
            re.compile(r"sequelize\.define\("),
            re.compile(r"DataTypes\.\w+"),
            re.compile(r"Model\.init\("),
            re.compile(r"\.belongsTo\(|\.hasMany\(|\.hasOne\(|\.belongsToMany\("),
        ],
        "eloquent": [
            re.compile(r"extends Model\b"),
            re.compile(r"\\$fillable|\\$guarded|\\$casts"),
            re.compile(r"Illuminate\\Database"),
        ],
        "mongoose": [
            re.compile(r"mongoose\.Schema\("),
            re.compile(r"new Schema\("),
            re.compile(r"mongoose\.model\("),
        ],
        "gorm": [
            re.compile(r"gorm\.Model"),
            re.compile(r"gorm\.DB"),
            re.compile(r"db\.AutoMigrate"),
        ],
    }

    # Migration directory/file patterns
    MIGRATION_PATTERNS = [
        "migration", "migrations", "alembic", "migrate",
        "db/migrate", "database/migrations",
    ]
    MIGRATION_FILE_PATTERNS = [
        re.compile(r"^\d{4}_"),        # Django: 0001_initial.py
        re.compile(r"^\d{14}"),        # Alembic/Rails timestamps
        re.compile(r"V\d+__"),         # Flyway
        re.compile(r"\.migration\.\w+$"),
    ]

    # Schema file patterns
    SCHEMA_PATTERNS = [
        "prisma/schema.prisma", "schema.prisma",
        "schema.graphql", "schema.gql",
        "schema.sql", "init.sql", "create_tables.sql",
        "dbdiagram", "erd",
    ]

    # Phase 1: Detect model files from parsed content
    orm_counts: dict[str, int] = defaultdict(int)

    for file_path, content in file_contents.items():
        if not content:
            continue

        path_lower = file_path.lower()
        parsed = parsed_files.get(file_path)

        # Skip test/migration files for model detection
        if any(p in path_lower for p in ("test", "spec", "fixture", "factory", "seed")):
            continue

        # Check migrations
        is_migration = False
        for mp in MIGRATION_PATTERNS:
            if mp in path_lower:
                result.migration_files.append(file_path)
                is_migration = True
                break
        if not is_migration:
            fname = file_path.split("/")[-1]
            for mp in MIGRATION_FILE_PATTERNS:
                if mp.search(fname):
                    result.migration_files.append(file_path)
                    is_migration = True
                    break
        if is_migration:
            continue

        # Check schema files
        for sp in SCHEMA_PATTERNS:
            if sp.lower() in path_lower:
                result.schema_files.append(file_path)

        # Check ORM patterns
        best_orm = ""
        best_score = 0
        for orm_name, patterns in ORM_PATTERNS.items():
            score = sum(1 for p in patterns if p.search(content))
            if score > best_score:
                best_score = score
                best_orm = orm_name
            if score > 0:
                orm_counts[orm_name] += score

        # Only count as model file if we got >= 2 pattern matches (reduces false positives)
        if best_score >= 2 or (
            best_score >= 1 and any(kw in path_lower for kw in ("model", "schema", "entity"))
        ):
            # Extract model/class names
            model_names: list[str] = []
            if parsed and parsed.symbols:
                for s in parsed.symbols:
                    if s.kind == "class":
                        model_names.append(s.name)

            # For Prisma/SQL schema, extract model names from content
            if best_orm == "prisma":
                model_names = re.findall(r"model\s+(\w+)\s*\{", content)

            result.model_files.append(ModelFileInfo(
                file_path=file_path,
                orm_framework=best_orm,
                model_names=model_names,
                is_migration=False,
            ))
            result.total_models += len(model_names)

    # Phase 2: Determine primary ORM
    if orm_counts:
        result.orm_framework = max(orm_counts, key=lambda k: orm_counts[k])

    # Deduplicate
    result.migration_files = sorted(set(result.migration_files))
    result.schema_files = sorted(set(result.schema_files))

    if result.model_files or result.migration_files or result.schema_files:
        console.print(
            f"  [dim]Database: {len(result.model_files)} model file(s), "
            f"{result.total_models} model(s), "
            f"{len(result.migration_files)} migration(s), "
            f"ORM: {result.orm_framework or 'unknown'}[/dim]"
        )

    return result


def fnmatch_simple(filename: str, pattern: str) -> bool:
    """Simple filename matching without glob."""
    return filename.lower() == pattern.lower() or pattern.lower() in filename.lower()


# ═════════════════════════════════════════════════════════════════════════════
# Shared Helpers
# ═════════════════════════════════════════════════════════════════════════════

def _parse_json(response: str) -> dict:
    """Extract JSON from LLM response, handling markdown fences."""
    text = response.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        lines = [l for l in lines if not l.strip().startswith("```")]
        text = "\n".join(lines)
    return json.loads(text)
