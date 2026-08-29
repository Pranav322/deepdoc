"""Claim extraction and validation for generated documentation pages.

``ClaimExtractor`` parses generated Markdown and extracts assertion claims
(route claims, call-edge claims, framework claims, file references).

``ClaimValidator`` cross-references extracted claims against the
``RepositoryModel`` evidence layer and produces a ``ClaimValidation`` result.
Ungrounded claims trigger hard-fail validation in ``PageValidator``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


@dataclass
class Claim:
    """A single claim extracted from a generated documentation page."""

    claim_type: str  # route, call_edge, framework, file_ref, integration, inferred
    claim_text: str  # the actual text of the claim
    evidence_sources: list[dict[str, Any]] = field(default_factory=list)
    confidence: float = 0.0


@dataclass
class ClaimValidation:
    """Result of validating claims against repository evidence."""

    total_claims: int = 0
    grounded_claims: int = 0
    ungrounded_route_claims: int = 0
    ungrounded_call_claims: int = 0
    hallucinated_files: list[str] = field(default_factory=list)
    fabricated_frameworks: list[str] = field(default_factory=list)
    is_valid: bool = True
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# ClaimExtractor — parse generated Markdown into claims
# ---------------------------------------------------------------------------


class ClaimExtractor:
    """Extracts claim assertions from generated documentation pages."""

    _ROUTE_PATTERN = re.compile(
        r"(?:`|\*\*)?((?:GET|POST|PUT|PATCH|DELETE|HEAD|OPTIONS)\s+/[\w\-_{}/?=&.]+)(?:`|\*\*)?",
        re.IGNORECASE,
    )
    _FILE_REF_PATTERN = re.compile(r"`([^`]+):(\d+)`")
    _CALL_PATTERN = re.compile(
        r"(?:calls|invokes|dispatches|triggers|delegates to)\s+`?(\w+(?:\.\w+)*)`?",
        re.IGNORECASE,
    )
    _FRAMEWORK_PATTERN = re.compile(
        r"(?:built with|using|framework[: ]|powered by)\s+`?((?:Spring(?:\s*Boot)?|Django|FastAPI|Express|Fastify|NestJS|Laravel|Flask|Rails|Actix|Axum|Gin|Echo|Fiber|Chi))`?",
        re.IGNORECASE,
    )

    # Lines inside code fences are not claims
    _CODE_FENCE_RE = re.compile(r"```[\s\S]*?```")

    def extract(self, markdown: str) -> list[Claim]:
        """Extract all claim assertions from a generated page."""
        body = self._strip_code_fences(markdown)
        claims: list[Claim] = []

        claims.extend(self._extract_route_claims(body))
        claims.extend(self._extract_call_claims(body))
        claims.extend(self._extract_framework_claims(body))
        claims.extend(self._extract_file_refs(body))

        return claims

    @staticmethod
    def _strip_code_fences(markdown: str) -> str:
        return re.sub(r"```[\s\S]*?```", "", markdown)

    def _extract_route_claims(self, body: str) -> list[Claim]:
        claims: list[Claim] = []
        for m in self._ROUTE_PATTERN.finditer(body):
            claims.append(Claim(
                claim_type="route",
                claim_text=m.group(0).strip(),
            ))
        return claims

    def _extract_call_claims(self, body: str) -> list[Claim]:
        claims: list[Claim] = []
        for m in self._CALL_PATTERN.finditer(body):
            claims.append(Claim(
                claim_type="call_edge",
                claim_text=m.group(0).strip(),
            ))
        return claims

    def _extract_framework_claims(self, body: str) -> list[Claim]:
        claims: list[Claim] = []
        for m in self._FRAMEWORK_PATTERN.finditer(body):
            claims.append(Claim(
                claim_type="framework",
                claim_text=m.group(0).strip(),
            ))
        return claims

    def _extract_file_refs(self, body: str) -> list[Claim]:
        claims: list[Claim] = []
        for m in self._FILE_REF_PATTERN.finditer(body):
            file_path = m.group(1)
            if _is_false_positive_file_ref(file_path):
                continue
            claims.append(Claim(
                claim_type="file_ref",
                claim_text=f"{file_path}:{m.group(2)}",
            ))
        return claims


def _is_false_positive_file_ref(text: str) -> bool:
    """Return True if text looks like a URL, IP address, bare number, or numeric range, not a file path."""
    if re.match(r"^\d+$", text):
        return True
    if re.match(r"^\d+\.\d+\.\d+\.\d+$", text):
        return True
    if re.match(r"^(https?|ftp)://", text):
        return True
    if re.match(r"^\d+\.\d+$", text):
        return True
    if re.match(r"^[0-9a-fA-F:]+$", text):
        return True
    if re.match(r"^\d+-\d+$", text):
        return True
    return False


# ---------------------------------------------------------------------------
# ClaimValidator — cross-reference claims against RepositoryModel evidence
# ---------------------------------------------------------------------------


class ClaimValidator:
    """Validates claims against repository evidence from RepositoryModel.

    Route claims must have matching RouteRecords in scan.api_endpoints.
    Call-edge claims must have matching CallEdges in scan.call_graph.
    File references must exist in repo_model.files.
    Framework claims must match scan.frameworks_detected.
    """

    def __init__(
        self,
        scan: Any,
        repo_model: Any | None = None,
    ):
        self.scan = scan
        self.repo_model = repo_model

        self._known_files: set[str] = set(
            getattr(scan, "file_summaries", {}).keys()
        ) | set(getattr(scan, "file_contents", {}).keys())

        self._known_routes: set[str] = set()
        for ep in getattr(scan, "published_api_endpoints", []) or []:
            path = (ep.get("path") or "").strip().lower()
            if path:
                self._known_routes.add(path)

        self._known_frameworks: set[str] = {
            f.lower() for f in (getattr(scan, "frameworks_detected", []) or [])
        }

    def validate(self, claims: list[Claim]) -> ClaimValidation:
        """Cross-reference claims against known evidence."""
        result = ClaimValidation()
        result.total_claims = len(claims)

        for claim in claims:
            if claim.claim_type == "route":
                self._check_route_claim(claim, result)
            elif claim.claim_type == "call_edge":
                self._check_call_claim(claim, result)
            elif claim.claim_type == "file_ref":
                self._check_file_ref(claim, result)
            elif claim.claim_type == "framework":
                self._check_framework(claim, result)
            else:
                result.grounded_claims += 1  # give benefit of doubt

        if result.ungrounded_route_claims >= 5:
            result.is_valid = False
            result.errors.append(
                f"Page has {result.ungrounded_route_claims} ungrounded route claims "
                f"(max 4 allowed). Remove fabricated routes or add to evidence."
            )

        if result.ungrounded_call_claims >= 5:
            result.is_valid = False
            result.errors.append(
                f"Page has {result.ungrounded_call_claims} ungrounded call-edge claims "
                f"(max 4 allowed). Remove fabricated call chains or add to evidence."
            )

        if result.hallucinated_files:
            result.is_valid = False
            result.errors.append(
                f"Page references {len(result.hallucinated_files)} nonexistent files: "
                f"{', '.join(result.hallucinated_files[:5])}"
            )

        if result.fabricated_frameworks:
            result.is_valid = False
            result.errors.append(
                f"Page claims unsupported frameworks: "
                f"{', '.join(result.fabricated_frameworks)}. "
                f"Remove or add framework detector support."
            )

        return result

    def _check_route_claim(self, claim: Claim, result: ClaimValidation) -> None:
        claim_path = ClaimValidator._normalize_route(claim.claim_text)
        if not claim_path:
            return
        if any(
            ClaimValidator._normalize_route(r) == claim_path
            for r in self._known_routes
        ):
            result.grounded_claims += 1
        else:
            result.ungrounded_route_claims += 1

    def _check_call_claim(self, claim: Claim, result: ClaimValidation) -> None:
        symbol_name = self._extract_symbol_from_call(claim.claim_text)
        if not symbol_name:
            result.grounded_claims += 1
            return
        known_symbols: set[str] = set()
        for pf in getattr(self.scan, "parsed_files", {}).values():
            for s in getattr(pf, "symbols", []) or []:
                known_symbols.add(s.name)
        if symbol_name in known_symbols:
            result.grounded_claims += 1
        else:
            result.ungrounded_call_claims += 1

    def _check_file_ref(self, claim: Claim, result: ClaimValidation) -> None:
        file_path = claim.claim_text.rsplit(":", 1)[0]
        if file_path in self._known_files:
            result.grounded_claims += 1
        else:
            result.hallucinated_files.append(file_path)

    def _check_framework(self, claim: Claim, result: ClaimValidation) -> None:
        claim_text = claim.claim_text.lower()
        matched = any(fw in claim_text for fw in self._known_frameworks)
        if matched:
            result.grounded_claims += 1
        else:
            result.fabricated_frameworks.append(claim.claim_text[:60])

    @staticmethod
    def _normalize_route(text: str) -> str:
        text = re.sub(r"[`*]", "", text).strip().lower()
        text = re.sub(r"^(get|post|put|patch|delete|head|options)\s+", "", text)
        text = re.sub(r"\?.+$", "", text)
        text = re.sub(r"/+$", "", text)
        if not text.startswith("/"):
            return ""
        return text

    @staticmethod
    def _extract_symbol_from_call(text: str) -> str:
        m = re.search(r"`?(\w+(?:\.\w+)*)`?", text)
        return m.group(1) if m else ""


# ---------------------------------------------------------------------------
# Source trust scoring (used by EvidenceAssembler filtering)
# ---------------------------------------------------------------------------


_GENERATED_MARKERS = re.compile(
    r"@generated|auto-generated|DO NOT EDIT|GENERATED CODE|THIS FILE IS AUTO",
    re.IGNORECASE,
)


def has_generated_marker(content: str) -> bool:
    """Check if a file's first 50 lines contain a generated-code marker."""
    lines = content.splitlines()[:50]
    return any(_GENERATED_MARKERS.search(line) for line in lines)


def compute_source_trust(
    source_kind: str, content: str = "", lockfile_hashes: set | None = None,
) -> float:
    """Compute source trust score for a file.

    Returns 0.0-1.0 where lower = less trustworthy as production evidence.
    """
    if source_kind in ("test", "fixture", "example"):
        return 0.1
    if source_kind == "generated":
        return 0.0
    if content and has_generated_marker(content):
        return 0.0
    if lockfile_hashes is not None:
        import hashlib
        ch = hashlib.sha256(content.encode("utf-8")).hexdigest()
        if ch in lockfile_hashes:
            return 0.0
    if source_kind == "config":
        return 0.8
    if source_kind in ("docs", "ops", "tooling"):
        return 0.5
    return 1.0


__all__ = [
    "Claim", "ClaimValidation",
    "ClaimExtractor", "ClaimValidator",
    "compute_source_trust", "has_generated_marker",
]