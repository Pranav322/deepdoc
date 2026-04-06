from .common import *

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
        parts = [
            p
            for p in clean.split("/")
            if p and not p.startswith(":") and not p.startswith("{")
        ]
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
            evidence.append(
                EvidenceUnit(
                    file_path=hf,
                    role="handler",
                    symbols=handler_symbols,
                    relevance=1.0,
                )
            )

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
            evidence.append(
                EvidenceUnit(
                    file_path=f,
                    role=role,
                    relevance=0.8,
                )
            )

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
                evidence.append(
                    EvidenceUnit(
                        file_path=f,
                        role=role,
                        relevance=0.5,
                    )
                )

        # Detect integration edges
        integration_edges = _detect_integration_edges_in_bundle(evidence, parsed_files)

        bundles.append(
            EndpointBundle(
                endpoint_family=resource,
                methods_paths=methods_paths,
                handler_file=handler_files[0] if handler_files else "",
                handler_symbols=handler_symbols,
                evidence=evidence,
                integration_edges=integration_edges,
            )
        )

    return bundles


from .utils import _build_import_lookup, _classify_file_role, _resolve_imports_to_files
from .integrations import _detect_integration_edges_in_bundle
