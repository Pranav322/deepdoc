"""Universal repository model — the stable intermediate representation between
scanning and planning.

Every analyzer — whether tree-sitter, language server, or inventory-only — writes
into this model. The planner and generator read from it. The model is the universal
contract that makes every file visible regardless of parse status.

This is an additive layer. RepoScan (v2_models.py) remains the active pipeline
model until downstream consumers migrate. RepositoryModel is constructed from the
same scan data and gradually becomes authoritative.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Parse status — how well we understand a file
# ---------------------------------------------------------------------------


class ParseStatus(str, Enum):
    """How thoroughly a file was analyzed."""

    FULL = "full"  # tree-sitter parse succeeded, symbols extracted
    PARTIAL = "partial"  # parse attempted, errors encountered
    INVENTORY_ONLY = "inventory_only"  # no parser available for this language
    SKIPPED = "skipped"  # oversized, binary, or otherwise excluded
    UNKNOWN = "unknown"  # extension not recognized at all


# ---------------------------------------------------------------------------
# Source trust — how much we trust a file's content as production evidence
# ---------------------------------------------------------------------------


class SourceKind(str, Enum):
    """Coarse classification of a file's role in the repository."""

    PRODUCT = "product"
    TEST = "test"
    FIXTURE = "fixture"
    EXAMPLE = "example"
    GENERATED = "generated"
    DOCS = "docs"
    CONFIG = "config"
    OPS = "ops"
    TOOLING = "tooling"


LOW_TRUST_SOURCE_KINDS: set[SourceKind] = {
    SourceKind.TEST,
    SourceKind.FIXTURE,
    SourceKind.EXAMPLE,
    SourceKind.GENERATED,
}

# Extended from source_metadata.py to provide forward-looking coverage for
# languages we plan to support in future slices.
KNOWN_UNSUPPORTED_LANGUAGES: dict[str, str] = {
    ".kt": "Kotlin",
    ".kts": "Kotlin",
    ".cs": "C#",
    ".rb": "Ruby",
    ".swift": "Swift",
    ".c": "C",
    ".h": "C/C++",
    ".cpp": "C++",
    ".cc": "C++",
    ".hpp": "C++",
    ".scala": "Scala",
    ".ex": "Elixir",
    ".exs": "Elixir",
    ".clj": "Clojure",
    ".dart": "Dart",
    ".m": "Objective-C",
    ".mm": "Objective-C++",
    ".groovy": "Groovy",
    ".r": "R",
}


# ---------------------------------------------------------------------------
# Language info per file
# ---------------------------------------------------------------------------


@dataclass
class LanguageInfo:
    """Description of a file's language and how well we analyzed it."""

    name: str  # e.g. "python", "typescript", "java", "unknown"
    parse_status: ParseStatus = ParseStatus.INVENTORY_ONLY
    parse_error: str | None = None  # set when parse_status is PARTIAL or SKIPPED

    @property
    def is_parseable(self) -> bool:
        return self.parse_status in (ParseStatus.FULL, ParseStatus.PARTIAL)

    @property
    def is_fully_parseable(self) -> bool:
        return self.parse_status == ParseStatus.FULL


# ---------------------------------------------------------------------------
# File entry — the universal record for every discovered file
# ---------------------------------------------------------------------------


@dataclass
class FileEntry:
    """Every file discovered by the walk gets one FileEntry.

    Fields left empty are populated by successive analyzer passes.
    """

    path: str  # repo-relative path (Posix-style)
    language: LanguageInfo  # what language and how well we parsed it
    source_kind: SourceKind = SourceKind.PRODUCT
    source_trust: float = 1.0  # 1.0 = production source, 0.0 = untrusted
    line_count: int = 0
    byte_count: int = 0
    content_hash: str = ""  # sha256[:16] of file content
    symbol_count: int = 0  # how many symbols were extracted (0 if unparseable)
    import_count: int = 0  # how many import statements were found
    is_multi_language_sfc: bool = False  # true for .vue, .svelte etc.
    frameworks: list[str] = field(default_factory=list)  # detected frameworks

    def __post_init__(self) -> None:
        if self.source_trust < 0.0:
            self.source_trust = 0.0
        elif self.source_trust > 1.0:
            self.source_trust = 1.0

    @property
    def is_low_trust(self) -> bool:
        return self.source_kind in LOW_TRUST_SOURCE_KINDS

    @property
    def is_product_source(self) -> bool:
        return self.source_kind == SourceKind.PRODUCT and self.source_trust >= 0.5


# ---------------------------------------------------------------------------
# Import record
# ---------------------------------------------------------------------------


class ImportResolutionStatus(str, Enum):
    RESOLVED = "resolved"
    UNRESOLVED = "unresolved"
    EXTERNAL = "external"  # third-party package
    NOT_APPLICABLE = "not_applicable"  # no resolution attempted


@dataclass
class ImportRecord:
    """A single import statement from a file."""

    raw_text: str
    resolved_to: str | None = None
    resolution_status: ImportResolutionStatus = ImportResolutionStatus.NOT_APPLICABLE
    source_file: str = ""  # file this import was found in


# ---------------------------------------------------------------------------
# Symbol entry — language-agnostic symbol reference
# ---------------------------------------------------------------------------


@dataclass
class SymbolEntry:
    """A code symbol stored in the persistent index.

    Lightweight reference to avoid duplicating parser/base.py Symbol dataclass
    fields. The full Symbol object remains in parsed_files for backward compat.
    """

    name: str
    kind: str  # function, class, method, interface, type, route, constant, enum, component, hook
    file_path: str
    start_line: int = 0
    end_line: int = 0
    signature: str = ""
    is_exported: bool = False


# ---------------------------------------------------------------------------
# Coverage report — what did we find and how well did we understand it?
# ---------------------------------------------------------------------------


@dataclass
class LanguageCoverage:
    """Per-language scan coverage."""

    language: str
    total_files: int
    fully_parsed: int
    partially_parsed: int
    inventory_only: int
    skipped: int
    parse_rate: float = 0.0  # fraction of files that were fully parsed

    def __post_init__(self) -> None:
        if self.total_files > 0:
            self.parse_rate = self.fully_parsed / self.total_files


@dataclass
class SourceKindCoverage:
    """Per-source-kind file counts."""

    kind: SourceKind
    count: int


@dataclass
class CoverageReport:
    """Complete scan coverage report — answers 'what did we find?'"""

    total_files_discovered: int = 0
    total_files_parsed: int = 0  # files with parse_status FULL
    total_files_partial: int = 0  # files with parse_status PARTIAL
    total_files_inventory_only: int = 0  # no parser available
    total_files_skipped: int = 0  # oversized, binary, excluded
    languages: list[LanguageCoverage] = field(default_factory=list)
    source_kinds: list[SourceKindCoverage] = field(default_factory=list)
    unsupported_languages: list[str] = field(default_factory=list)  # languages found but no parser
    total_source_bytes: int = 0
    scan_timestamp: str = ""  # ISO 8601

    @property
    def overall_parse_rate(self) -> float:
        total = self.total_files_discovered
        if total == 0:
            return 0.0
        return self.total_files_parsed / total

    @property
    def has_unsupported_languages(self) -> bool:
        return len(self.unsupported_languages) > 0


# ---------------------------------------------------------------------------
# RepositoryModel — the top-level container
# ---------------------------------------------------------------------------


@dataclass
class RepositoryModel:
    """Universal repository representation.

    Populated by the scan phase. Every file has a FileEntry. Coverage is complete.
    This model is the single source of truth for what the repository contains
    and how well we understand it.
    """

    repo_root: str = ""
    files: dict[str, FileEntry] = field(default_factory=dict)  # rel_path → FileEntry
    coverage: CoverageReport = field(default_factory=CoverageReport)

    def add_file(self, entry: FileEntry) -> None:
        self.files[entry.path] = entry

    def get_file(self, rel_path: str) -> FileEntry | None:
        return self.files.get(rel_path)

    def product_files(self) -> list[FileEntry]:
        return [f for f in self.files.values() if f.is_product_source]

    def parsed_files(self) -> list[FileEntry]:
        return [f for f in self.files.values() if f.language.is_fully_parseable]

    def files_by_language(self, language: str) -> list[FileEntry]:
        return [f for f in self.files.values() if f.language.name == language]

    def files_by_kind(self, kind: SourceKind) -> list[FileEntry]:
        return [f for f in self.files.values() if f.source_kind == kind]

    def unsupported_files(self) -> list[FileEntry]:
        return [
            f
            for f in self.files.values()
            if f.language.parse_status
            in (ParseStatus.INVENTORY_ONLY, ParseStatus.UNKNOWN)
        ]

    def build_coverage_report(self) -> None:
        """Compute CoverageReport from all FileEntry records."""
        report = CoverageReport()
        report.total_files_discovered = len(self.files)
        by_lang: dict[str, dict[str, int]] = {}
        by_kind: dict[SourceKind, int] = {}

        for entry in self.files.values():
            report.total_source_bytes += entry.byte_count
            lang = entry.language.name
            if lang not in by_lang:
                by_lang[lang] = {"total": 0, "parsed": 0, "partial": 0, "inventory": 0, "skipped": 0}
            by_lang[lang]["total"] += 1
            if entry.language.parse_status == ParseStatus.FULL:
                by_lang[lang]["parsed"] += 1
                report.total_files_parsed += 1
            elif entry.language.parse_status == ParseStatus.PARTIAL:
                by_lang[lang]["partial"] += 1
                report.total_files_partial += 1
            elif entry.language.parse_status == ParseStatus.SKIPPED:
                by_lang[lang]["skipped"] += 1
                report.total_files_skipped += 1
            else:
                by_lang[lang]["inventory"] += 1
                report.total_files_inventory_only += 1

            by_kind[entry.source_kind] = by_kind.get(entry.source_kind, 0) + 1

        report.languages = [
            LanguageCoverage(
                language=lang,
                total_files=counts["total"],
                fully_parsed=counts["parsed"],
                partially_parsed=counts["partial"],
                inventory_only=counts["inventory"],
                skipped=counts["skipped"],
            )
            for lang, counts in sorted(by_lang.items())
        ]
        report.source_kinds = [
            SourceKindCoverage(kind=kind, count=count)
            for kind, count in sorted(by_kind.items(), key=lambda kv: kv[1], reverse=True)
        ]
        report.unsupported_languages = [
            lc.language
            for lc in report.languages
            if lc.total_files > 0 and lc.parse_rate == 0.0 and lc.language != "unknown"
        ]
        self.coverage = report

    def coverage_summary(self) -> str:
        """Human-readable coverage summary for CLI output."""
        if not self.coverage.languages:
            return "No files scanned."
        lines: list[str] = []
        for lc in self.coverage.languages:
            if lc.inventory_only > 0 and lc.fully_parsed == 0:
                lines.append(
                    f"  {lc.language}: {lc.total_files} files (inventory only)"
                )
            elif lc.inventory_only > 0:
                rate = int(lc.parse_rate * 100)
                lines.append(
                    f"  {lc.language}: {lc.fully_parsed}/{lc.total_files} parsed "
                    f"({rate}%), {lc.inventory_only} inventory only"
                )
            elif lc.skipped > 0:
                lines.append(
                    f"  {lc.language}: {lc.fully_parsed}/{lc.total_files} parsed, "
                    f"{lc.skipped} skipped"
                )
            else:
                lines.append(
                    f"  {lc.language}: {lc.fully_parsed}/{lc.total_files} parsed (100%)"
                )
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Factory: build RepositoryModel from the existing RepoScan
# ---------------------------------------------------------------------------


def build_repo_model_from_scan(scan: Any, repo_root: str) -> RepositoryModel:
    """Construct a RepositoryModel from the current RepoScan output.

    This is the migration bridge — all fields are derived from existing RepoScan
    data. No new scanning; just a structured view of what we already know.
    """
    from .source_metadata import LOW_TRUST_SOURCE_KINDS as LEGACY_LOW_TRUST_KINDS
    from .source_metadata import SOURCE_KIND_CORE, KNOWN_UNSUPPORTED_LANGUAGE_EXTENSIONS

    model = RepositoryModel(repo_root=repo_root)

    kind_map: dict[str, SourceKind] = {
        "product": SourceKind.PRODUCT,
        "test": SourceKind.TEST,
        "fixture": SourceKind.FIXTURE,
        "example": SourceKind.EXAMPLE,
        "generated": SourceKind.GENERATED,
        "docs": SourceKind.DOCS,
        "config": SourceKind.CONFIG,
        "ops": SourceKind.OPS,
        "tooling": SourceKind.TOOLING,
    }

    supported_extensions: set[str] = set()
    try:
        from .parser.registry import supported_extensions as _sup_ext

        supported_extensions = _sup_ext()
    except Exception:
        pass

    all_rel_paths: set[str] = set()

    file_summaries = getattr(scan, "file_summaries", None) or {}
    source_kinds = getattr(scan, "source_kind_by_file", None) or {}
    frameworks = getattr(scan, "file_frameworks", None) or {}
    line_counts = getattr(scan, "file_line_counts", None) or {}
    parsed = getattr(scan, "parsed_files", None) or {}
    contents = getattr(scan, "file_contents", None) or {}
    content_hashes = getattr(scan, "file_content_hashes", None) or {}
    file_services = getattr(scan, "file_services", None) or {}
    skipped_sources = getattr(scan, "skipped_source_files", None) or {}

    for rel in sorted(contents.keys()):
        all_rel_paths.add(rel)

    for rel in sorted(all_rel_paths):
        ext = Path(rel).suffix.lower()
        legacy_kind = source_kinds.get(rel, SOURCE_KIND_CORE)
        source_kind = kind_map.get(legacy_kind, SourceKind.PRODUCT)

        is_supported = ext in supported_extensions
        has_parsed = rel in parsed
        was_skipped = any(
            reason
            for reason in skipped_sources
            if reason in ("oversized", "binary", "minified")
        )

        if was_skipped:
            parse_status = ParseStatus.SKIPPED
            lang_name = KNOWN_UNSUPPORTED_LANGUAGE_EXTENSIONS.get(ext, ext.lstrip(".") if ext else "unknown")
        elif has_parsed:
            pf = parsed[rel]
            parse_status = ParseStatus.FULL
            lang_name = pf.language
        elif is_supported:
            parse_status = ParseStatus.PARTIAL
            from .parser.registry import _REGISTRY

            lang_name = _REGISTRY.get(ext, ("unknown", None))[0]
        elif ext:
            parse_status = ParseStatus.INVENTORY_ONLY
            lang_name = KNOWN_UNSUPPORTED_LANGUAGE_EXTENSIONS.get(ext, ext.lstrip("."))
        else:
            parse_status = ParseStatus.UNKNOWN
            lang_name = "unknown"

        source_trust = 1.0
        if legacy_kind in LEGACY_LOW_TRUST_KINDS:
            source_trust = 0.1
        elif legacy_kind == "config":
            source_trust = 0.8
        elif legacy_kind in ("docs", "ops", "tooling"):
            source_trust = 0.5

        file_entry = FileEntry(
            path=rel,
            language=LanguageInfo(name=lang_name, parse_status=parse_status),
            source_kind=source_kind,
            source_trust=source_trust,
            line_count=line_counts.get(rel, 0),
            byte_count=len(contents.get(rel, "")),
            content_hash=content_hashes.get(rel, ""),
            symbol_count=len(parsed[rel].symbols) if has_parsed else 0,
            import_count=len(parsed[rel].imports) if has_parsed else 0,
            frameworks=list(frameworks.get(rel, [])),
        )
        model.add_file(file_entry)

    model.build_coverage_report()
    return model


__all__ = [
    "ParseStatus",
    "SourceKind",
    "LanguageInfo",
    "FileEntry",
    "ImportRecord",
    "ImportResolutionStatus",
    "SymbolEntry",
    "LanguageCoverage",
    "SourceKindCoverage",
    "CoverageReport",
    "RepositoryModel",
    "build_repo_model_from_scan",
    "LOW_TRUST_SOURCE_KINDS",
    "KNOWN_UNSUPPORTED_LANGUAGES",
]