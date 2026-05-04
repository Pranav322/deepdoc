from .common import *
from ..llm.json_utils import parse_llm_json

def _normalize_repo_rel_path(repo_root: Path, file_path: str) -> str:
    if not file_path:
        return ""
    path = Path(file_path)
    if not path.is_absolute():
        return path.as_posix()
    try:
        return path.relative_to(repo_root).as_posix()
    except ValueError:
        return path.as_posix()


def _is_doc_context_candidate(rel_path: str, file_name: str) -> bool:
    lower_rel = rel_path.lower()
    lower_name = file_name.lower()
    if lower_name in DOC_CONTEXT_FILENAMES:
        return True
    if lower_rel.startswith("docs/") and lower_name.endswith((".md", ".mdx", ".txt")):
        return True
    if any(
        token in lower_name
        for token in (
            "readme",
            "changelog",
            "glossary",
            "design",
            "experiment",
            "notes",
            "history",
        )
    ):
        return lower_name.endswith((".md", ".mdx", ".txt"))
    return lower_name.endswith(".ipynb")


def _summarize_doc_context(
    rel_path: str, content: str
) -> tuple[str, dict[str, Any] | None]:
    lines = content.splitlines()
    headings = [
        line.strip().lstrip("# ").strip()
        for line in lines
        if line.strip().startswith("#")
    ]
    nonempty = [
        line.strip()
        for line in lines
        if line.strip() and not line.strip().startswith("#")
    ]
    summary_lines: list[str] = []
    if headings:
        summary_lines.append(f"Headings: {', '.join(headings[:8])}")
    if nonempty:
        summary_lines.append(f"Summary: {' '.join(nonempty[:3])[:300]}")
    summary = " | ".join(summary_lines)[:800]

    lower_rel = rel_path.lower()
    headings_blob = " ".join(headings).lower()
    kind = ""
    title = Path(rel_path).stem.replace("_", " ").replace("-", " ").title()
    if "glossary" in lower_rel:
        kind = "glossary"
    elif any(
        token in lower_rel for token in ("experiment", "ablation", "results")
    ) or any(token in headings_blob for token in ("experiment", "ablation", "results")):
        kind = "experiment_log"
    elif any(
        token in lower_rel for token in ("design", "architecture", "history")
    ) or any(
        token in headings_blob
        for token in ("design", "architecture history", "history")
    ):
        kind = "design_history"
    elif any(
        token in lower_rel for token in ("note", "notes", "devlog", "development")
    ) or any(token in headings_blob for token in ("development", "notes", "devlog")):
        kind = "development_notes"
    if kind:
        return summary, {
            "kind": kind,
            "title": title,
            "file_path": rel_path,
            "summary": summary,
            "headings": headings[:12],
        }
    return summary, None


def _summarize_notebook_context(
    rel_path: str, content: str
) -> tuple[str, dict[str, Any] | None]:
    try:
        notebook = json.loads(content)
    except Exception:
        return "", None
    markdown_cells: list[str] = []
    for cell in notebook.get("cells", []):
        if cell.get("cell_type") != "markdown":
            continue
        source = cell.get("source", [])
        if isinstance(source, list):
            markdown_cells.append("".join(source))
        elif isinstance(source, str):
            markdown_cells.append(source)
    if not markdown_cells:
        return "", None
    combined = "\n".join(markdown_cells[:8])
    summary, context = _summarize_doc_context(rel_path, combined)
    if context is None:
        lower_rel = rel_path.lower()
        if any(
            token in lower_rel
            for token in ("experiment", "ablation", "analysis", "notebook")
        ):
            context = {
                "kind": "experiment_log",
                "title": Path(rel_path)
                .stem.replace("_", " ")
                .replace("-", " ")
                .title(),
                "file_path": rel_path,
                "summary": summary,
                "headings": [],
            }
    return summary, context


def _parse_json_response(response: str) -> dict:
    """Extract JSON from LLM response, handling markdown fences."""
    return parse_llm_json(response)


def _format_file_tree_compressed(
    tree: dict[str, list[str]], summaries: dict[str, str]
) -> str:
    """Compress file tree to directory-level summaries so 300+ files fit."""
    lines = []
    for dir_path in sorted(tree.keys()):
        files = tree[dir_path]
        if not files:
            continue
        ext_counts: dict[str, int] = defaultdict(int)
        for f in files:
            ext = f.rsplit(".", 1)[-1] if "." in f else "other"
            ext_counts[ext] += 1
        ext_summary = ", ".join(
            f"{count} .{ext}"
            for ext, count in sorted(ext_counts.items(), key=lambda x: -x[1])
        )
        shown = sorted(files)[:5]
        rest = len(files) - len(shown)
        file_list = ", ".join(shown) + (f", +{rest} more" if rest > 0 else "")
        lines.append(f"\n{dir_path}/ ({len(files)} files: {ext_summary})")
        lines.append(f"  Files: {file_list}")
        all_symbols: list[str] = []
        for rel_path, summary in summaries.items():
            file_dir = "/".join(rel_path.split("/")[:-1]) if "/" in rel_path else "."
            if file_dir == dir_path and "symbols=[" in summary:
                try:
                    sym_part = summary.split("symbols=[")[1].split("]")[0]
                    names = [
                        s.split(":")[-1].strip()
                        for s in sym_part.split(",")
                        if ":" in s
                    ]
                    all_symbols.extend(names[:5])
                except Exception:
                    pass
        if all_symbols:
            lines.append(f"  Key symbols: {', '.join(all_symbols[:12])}")
    return "\n".join(lines)


def _format_summaries_compressed(summaries: dict[str, str]) -> str:
    """Compressed per-file summaries."""
    lines: list[str] = []
    for path in sorted(summaries.keys()):
        summary = summaries[path]
        line_count = ""
        if "lines=" in summary:
            try:
                line_count = summary.split("lines=")[-1].split("|")[0].strip()
                line_count = f" ({line_count}L)"
            except Exception:
                pass
        symbols = ""
        if "symbols=[" in summary:
            try:
                sym_part = summary.split("symbols=[")[1].split("]")[0]
                names = [
                    s.split(":")[-1].strip() for s in sym_part.split(",") if ":" in s
                ]
                if names:
                    symbols = f" → {', '.join(names[:8])}"
                    if len(names) > 8:
                        symbols += f" +{len(names) - 8}"
            except Exception:
                pass
        lines.append(f"- {path}{line_count}{symbols}")
    return "\n".join(lines)


def _format_endpoints(endpoints: list[dict]) -> str:
    if not endpoints:
        return "(none)"
    lines = []
    for ep in endpoints[:50]:
        lines.append(
            f"- {ep['method']} {ep['path']} → {ep.get('handler', '?')} ({ep.get('file', '')}:{ep.get('line', 0)})"
        )
    if len(endpoints) > 50:
        lines.append(f"... +{len(endpoints) - 50} more endpoints")
    return "\n".join(lines)


def _build_classification_summary(classification: dict) -> str:
    """Build a human-readable summary of the classification for Step 2."""
    lines = []

    source_files = classification.get("source_files", {})
    # Count by primary role
    role_counts: dict[str, int] = defaultdict(int)
    domain_counts: dict[str, int] = defaultdict(int)
    for _path, info in source_files.items():
        if isinstance(info, dict):
            role_counts[info.get("primary", "other")] += 1
            domain = info.get("domain_hint", "unknown")
            if domain:
                domain_counts[domain] += 1

    lines.append("### File Roles")
    for role, count in sorted(role_counts.items(), key=lambda x: -x[1]):
        lines.append(f"- {role}: {count} files")

    lines.append("\n### Business Domains")
    for domain, count in sorted(domain_counts.items(), key=lambda x: -x[1]):
        lines.append(f"- {domain}: {count} files")

    lines.append(
        f"\n### Setup artifacts: {len(classification.get('setup_artifacts', []))}"
    )
    lines.append(f"### Test artifacts: {len(classification.get('test_artifacts', []))}")
    lines.append(
        f"### Deploy artifacts: {len(classification.get('deploy_artifacts', []))}"
    )
    lines.append(
        f"### Integration signals: {len(classification.get('integration_signals', []))}"
    )
    lines.append(
        f"### Cross-cutting concerns: {len(classification.get('cross_cutting', []))}"
    )
    lines.append(f"### Giant files: {len(classification.get('giant_files', []))}")
    repo_profile = classification.get("repo_profile", {})
    if repo_profile:
        primary_type = repo_profile.get("primary_type", "other")
        traits = ", ".join(repo_profile.get("secondary_traits", [])) or "none"
        confidence = repo_profile.get("confidence", "unknown")
        lines.append(
            f"### Repo profile: {primary_type} (traits: {traits}; confidence: {confidence})"
        )

    return "\n".join(lines)


def _print_classification_summary(classification: dict) -> None:
    """Print a rich summary of the classification step."""
    source_files = classification.get("source_files", {})
    integrations = classification.get("integration_signals", [])
    cross_cutting = classification.get("cross_cutting", [])
    giant_files = classification.get("giant_files", [])
    repo_profile = classification.get("repo_profile", {})

    console.print(f"  [green]✓[/green] Classified {len(source_files)} source files")
    if repo_profile:
        primary = repo_profile.get("primary_type", "other")
        traits = ", ".join(repo_profile.get("secondary_traits", [])) or "none"
        confidence = repo_profile.get("confidence", "unknown")
        console.print(
            f"  [green]✓[/green] Repo profile: {primary} (traits: {traits}; confidence: {confidence})"
        )
    if integrations:
        names = [i.get("name", "?") for i in integrations]
        console.print(
            f"  [green]✓[/green] Found {len(integrations)} integration signal(s): {', '.join(names)}"
        )
    if cross_cutting:
        concerns = [c.get("concern", "?") for c in cross_cutting]
        console.print(
            f"  [green]✓[/green] Found {len(cross_cutting)} cross-cutting concern(s): {', '.join(concerns)}"
        )
    if giant_files:
        console.print(
            f"  [yellow]⚠[/yellow] {len(giant_files)} giant file(s) detected: {', '.join(giant_files[:5])}"
        )


def _print_proposal_summary(proposal: dict) -> None:
    """Print a rich summary of the proposed buckets."""
    buckets = proposal.get("buckets", [])
    by_type: dict[str, int] = defaultdict(int)
    for b in buckets:
        by_type[b.get("bucket_type", "?")] += 1

    console.print(f"  [green]✓[/green] Proposed {len(buckets)} buckets:")
    for btype, count in sorted(by_type.items()):
        console.print(f"    • {btype}: {count}")


def _print_plan_summary(plan: DocPlan) -> None:
    """Print the final plan as a rich table."""
    table = Table(
        title="Documentation Plan (Bucket-Based)", show_header=True, header_style="bold"
    )
    table.add_column("#", style="dim", width=3)
    table.add_column("Bucket", style="cyan")
    table.add_column("Type", style="green")
    table.add_column("Section")
    table.add_column("Files", justify="right")
    table.add_column("Sections", justify="right")
    table.add_column("Depends On", style="dim")

    for i, bucket in enumerate(plan.buckets, 1):
        deps = ", ".join(bucket.depends_on[:3])
        if len(bucket.depends_on) > 3:
            deps += f" +{len(bucket.depends_on) - 3}"
        table.add_row(
            str(i),
            bucket.title,
            bucket.bucket_type,
            bucket.section,
            str(len(bucket.owned_files)),
            str(len(bucket.required_sections)),
            deps or "—",
        )

    console.print(table)

    total_files = sum(len(b.owned_files) for b in plan.buckets)
    type_counts = defaultdict(int)
    for b in plan.buckets:
        type_counts[b.bucket_type] += 1
    type_str = ", ".join(
        f"{count} {btype}" for btype, count in sorted(type_counts.items())
    )

    console.print(
        f"\n[dim]{len(plan.buckets)} buckets ({type_str}) covering {total_files} source files | "
        f"{len(plan.skipped_files)} files skipped"
        f"{f' | {len(plan.orphaned_files)} orphaned → auto-assigned' if plan.orphaned_files else ''}[/dim]"
    )


def _format_topic_candidates(candidates: list[dict[str, Any]]) -> str:
    if not candidates:
        return "(none)"
    lines = []
    for item in candidates[:20]:
        files = ", ".join(item.get("evidence_files", [])[:4]) or "none"
        docs = ", ".join(item.get("evidence_docs", [])[:3]) or "none"
        signals = ", ".join(item.get("signals", [])[:6]) or "none"
        lines.append(
            f"- {item['title']} [{item['category']}] score={item['score']} | files: {files} | docs: {docs} | signals: {signals}"
        )
    return "\n".join(lines)


def _format_research_context(scan: RepoScan) -> str:
    if not scan.research_contexts and not scan.doc_contexts:
        return "(none)"
    lines = []
    for item in scan.research_contexts[:12]:
        lines.append(
            f"- {item.get('kind', 'doc')}: {item.get('title', Path(item.get('file_path', '')).name)} "
            f"({item.get('file_path', '')}) | {item.get('summary', '')[:180]}"
        )
    if not lines:
        for path, summary in list(scan.doc_contexts.items())[:12]:
            lines.append(f"- {path}: {summary[:200]}")
    return "\n".join(lines)


def _format_topology_clusters(scan: Any) -> str:
    """Format topology clusters for the classify prompt.

    Each cluster shows its entry files with key symbols, the files it owns,
    side effects, and external calls — giving the LLM full context to name it.
    Returns '(none)' when no topology map is available.
    """
    tmap = getattr(scan, "topology_map", None)
    if not tmap or not tmap.clusters:
        return "(none)"

    lines: list[str] = []
    for cluster in tmap.clusters:
        if cluster.is_foundational:
            lines.append(
                f"\n[foundational — shared infrastructure]\n"
                f"  Files ({len(cluster.all_files)}): "
                + ", ".join(cluster.all_files[:8])
                + (f" +{len(cluster.all_files) - 8} more" if len(cluster.all_files) > 8 else "")
            )
            continue

        entry_parts: list[str] = []
        for ef in cluster.entry_files[:3]:
            syms = ""
            pf = getattr(scan, "parsed_files", {}).get(ef)
            if pf and pf.symbols:
                sym_names = [s.name for s in pf.symbols[:4]]
                syms = f" [{', '.join(sym_names)}]"
            entry_parts.append(f"{ef}{syms}")
        entry_str = "; ".join(entry_parts) or "(none)"

        owned = cluster.all_files
        owned_str = ", ".join(owned[:6])
        if len(owned) > 6:
            owned_str += f" +{len(owned) - 6} more"

        extras: list[str] = []
        if cluster.side_effects:
            extras.append("side-effects: " + ", ".join(cluster.side_effects[:4]))
        if cluster.external_calls:
            extras.append("external: " + ", ".join(cluster.external_calls[:4]))
        if cluster.shared_dep_files:
            extras.append("uses-infra: " + ", ".join(cluster.shared_dep_files[:3]))
        extras_str = (" | " + " | ".join(extras)) if extras else ""

        lines.append(
            f"\n[cluster:{cluster.cluster_id}]\n"
            f"  Entry: {entry_str}\n"
            f"  Files ({len(owned)}): {owned_str}"
            + extras_str
        )

    return "\n".join(lines) if lines else "(none)"


def _build_named_clusters_str(classification: dict, scan: Any) -> str:
    """Build the named-clusters context string for the PROPOSE_PROMPT.

    Merges:
    - LLM cluster names/sections/descriptions from the classify step
      (classification["cluster_names"][cluster_id] → {name, section, description, nav_position})
    - Topology cluster file lists, entry files, side effects, and external calls
      from scan.topology_map

    Falls back to a file-summary-only blob when no topology map is available.
    """
    cluster_names: dict[str, dict] = classification.get("cluster_names", {})
    tmap = getattr(scan, "topology_map", None)

    if not tmap or not tmap.clusters:
        # Graceful degradation: just echo the cluster_names from classify
        if not cluster_names:
            return _format_summaries_compressed(scan.file_summaries)
        lines: list[str] = []
        for cid, info in cluster_names.items():
            lines.append(
                f"\n[cluster:{cid}]\n"
                f"  Name: {info.get('name', cid)}\n"
                f"  Section: {info.get('section', '')}\n"
                f"  Description: {info.get('description', '')}"
            )
        return "\n".join(lines)

    lines = []
    for cluster in tmap.clusters:
        cid = cluster.cluster_id
        info = cluster_names.get(cid, {})
        name = info.get("name") or cid
        section = info.get("section", "")
        description = info.get("description", "")
        nav_position = info.get("nav_position", "")

        if cluster.is_foundational:
            foundational_files_str = ", ".join(cluster.all_files[:8])
            if len(cluster.all_files) > 8:
                foundational_files_str += f" +{len(cluster.all_files) - 8} more"
            lines.append(
                f"\n[cluster:{cid}] {name} — foundational shared infrastructure\n"
                f"  Section: {section or 'Supporting Infrastructure'}\n"
                f"  Files ({len(cluster.all_files)}): {foundational_files_str}"
            )
            continue

        # Entry files with symbol names
        entry_parts: list[str] = []
        for ef in cluster.entry_files[:3]:
            syms = ""
            pf = getattr(scan, "parsed_files", {}).get(ef)
            if pf and pf.symbols:
                sym_names = [s.name for s in pf.symbols[:4]]
                syms = f" [{', '.join(sym_names)}]"
            entry_parts.append(f"{ef}{syms}")
        entry_str = "; ".join(entry_parts) or "(none)"

        # All owned files
        owned = cluster.all_files
        owned_str = ", ".join(owned[:8])
        if len(owned) > 8:
            owned_str += f" +{len(owned) - 8} more"

        # Extra signals
        extras: list[str] = []
        if cluster.side_effects:
            extras.append("side-effects: " + ", ".join(cluster.side_effects[:4]))
        if cluster.external_calls:
            extras.append("external: " + ", ".join(cluster.external_calls[:4]))
        if cluster.shared_dep_files:
            extras.append("uses-infra: " + ", ".join(cluster.shared_dep_files[:3]))
        extras_str = ("\n  Signals: " + " | ".join(extras)) if extras else ""

        lines.append(
            f"\n[cluster:{cid}] {name}\n"
            f"  Section: {section}"
            + (f" | nav_position: {nav_position}" if nav_position else "")
            + f"\n  Description: {description}\n"
            f"  Entry files: {entry_str}\n"
            f"  Files ({len(owned)}): {owned_str}"
            + extras_str
        )

    return "\n".join(lines) if lines else _format_summaries_compressed(scan.file_summaries)


def _format_flow_candidates(candidates: list[Any]) -> str:
    if not candidates:
        return "(none)"
    lines: list[str] = []
    for candidate in candidates[:12]:
        entry_labels = []
        for ep in candidate.entry_points[:4]:
            entry_labels.append(ep.label)
        entries = ", ".join(entry_labels) or "(no entrypoints)"
        files = ", ".join(candidate.involved_files[:5])
        if len(candidate.involved_files) > 5:
            files += f" +{len(candidate.involved_files) - 5} more"
        lines.append(
            f"- {candidate.title} [{candidate.flow_id}] :: entries: {entries} :: files: {files} :: score={candidate.score:.1f}"
        )
    return "\n".join(lines)
