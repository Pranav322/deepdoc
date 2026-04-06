from .common import *

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
            clusters=[
                SymbolCluster(
                    cluster_name="main",
                    description="All content (no symbols detected)",
                    symbols=[],
                    line_ranges=[(1, line_count)],
                )
            ],
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
        console.print(
            f"  [yellow]⚠ LLM clustering failed for {file_path}: {e} — using heuristic[/yellow]"
        )
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
        normalized = s.normalized_range()
        if normalized:
            start_line, end_line = normalized
            size = end_line - start_line + 1
            line_info = f"lines {start_line}-{end_line}, {size}L"
        else:
            line_info = "lines unknown"
        entry = f"- **{s.kind}** `{s.name}` ({line_info})"
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


def _build_clusters_from_llm(
    result: dict, symbols: list[Symbol]
) -> list[SymbolCluster]:
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
                normalized = s.normalized_range()
                if normalized:
                    line_ranges.append(normalized)
                valid_symbols.append(sym_name)
                assigned.add(sym_name)

        if valid_symbols:
            clusters.append(
                SymbolCluster(
                    cluster_name=c.get("cluster_name", "unnamed"),
                    description=c.get("description", ""),
                    symbols=valid_symbols,
                    line_ranges=line_ranges,
                )
            )

    # Catch unassigned symbols
    unassigned = [s.name for s in symbols if s.name not in assigned]
    if unassigned:
        line_ranges = [
            normalized
            for n in unassigned
            if n in sym_by_name
            for normalized in [sym_by_name[n].normalized_range()]
            if normalized
        ]
        clusters.append(
            SymbolCluster(
                cluster_name="uncategorized",
                description="Symbols not assigned to any cluster by LLM",
                symbols=unassigned,
                line_ranges=line_ranges,
            )
        )

    return clusters


def _heuristic_clustering(symbols: list[Symbol]) -> list[SymbolCluster]:
    """Fallback: group symbols by name prefix patterns."""
    groups: dict[str, list[Symbol]] = defaultdict(list)

    for s in symbols:
        # Try to extract a prefix: get_order → order, process_checkout → checkout
        name = s.name.lower()
        # Remove common prefixes
        for prefix in (
            "get_",
            "set_",
            "create_",
            "update_",
            "delete_",
            "process_",
            "validate_",
            "handle_",
            "on_",
            "do_",
            "is_",
            "has_",
            "can_",
        ):
            if name.startswith(prefix):
                name = name[len(prefix) :]
                break

        # Take first word as group
        parts = name.split("_")
        group = parts[0] if parts else "misc"
        groups[group].append(s)

    clusters = []
    for group_name, syms in sorted(groups.items(), key=lambda x: -len(x[1])):
        clusters.append(
            SymbolCluster(
                cluster_name=group_name,
                description=f"Symbols related to {group_name}",
                symbols=[s.name for s in syms],
                line_ranges=[
                    normalized
                    for s in syms
                    for normalized in [s.normalized_range()]
                    if normalized
                ],
            )
        )

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
            big.append(
                SymbolCluster(
                    cluster_name="misc",
                    description="Small utility functions and helpers",
                    symbols=misc_symbols,
                    line_ranges=misc_ranges,
                )
            )

    return big or clusters


from .utils import _parse_json
