from .common import *

def _first_mdx_heading(text: str, fallback: str) -> str:
    """Extract the first H1 title from MDX content, or fall back to the file stem."""
    for line in text.splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return fallback


def _split_leading_frontmatter(text: str) -> tuple[list[str], str] | None:
    """Split a leading frontmatter block from the remaining document body."""
    stripped = text.lstrip()
    if not stripped.startswith("---"):
        return None

    lines = stripped.splitlines()
    try:
        end_idx = lines.index("---", 1)
    except ValueError:
        return None

    return lines[1:end_idx], "\n".join(lines[end_idx + 1 :])


def _frontmatter_has_yaml_fields(frontmatter_lines: list[str]) -> bool:
    """Return True when the frontmatter block contains YAML-style key/value fields."""
    return any(
        ":" in line and not line.lstrip().startswith("#")
        for line in frontmatter_lines
        if line.strip()
    )


def _extract_frontmatter_scalar(frontmatter_lines: list[str], key: str) -> str | None:
    prefix = f"{key}:"
    for line in frontmatter_lines:
        stripped = line.strip()
        if stripped.startswith(prefix):
            value = stripped[len(prefix):].strip()
            if value[:1] == value[-1:] and value[:1] in {'"', "'"} and len(value) >= 2:
                return value[1:-1]
            return value
    return None


def _ensure_mdx_frontmatter(output_dir: Path) -> None:
    """Add minimal frontmatter to generated MDX pages and repair malformed blocks."""
    for mdx_path in output_dir.glob("*.mdx"):
        text = mdx_path.read_text(encoding="utf-8", errors="replace")
        fallback_title = mdx_path.stem.replace("-", " ").replace("_", " ").title()
        frontmatter_block = _split_leading_frontmatter(text)
        body_text = text.lstrip()

        if frontmatter_block:
            frontmatter_lines, frontmatter_body = frontmatter_block
            if _frontmatter_has_yaml_fields(frontmatter_lines):
                title = (
                    _extract_frontmatter_scalar(frontmatter_lines, "title")
                    or _first_mdx_heading(frontmatter_body, fallback_title)
                )
                description = (
                    _extract_frontmatter_scalar(frontmatter_lines, "description")
                    or "Auto-generated developer documentation"
                )
                extra_lines = [
                    line
                    for line in frontmatter_lines
                    if not line.strip().startswith("title:")
                    and not line.strip().startswith("description:")
                ]
                normalized_frontmatter = [
                    "---",
                    f"title: {json.dumps(title)}",
                    f"description: {json.dumps(description)}",
                    *extra_lines,
                    "---",
                    "",
                ]
                mdx_path.write_text(
                    "\n".join(normalized_frontmatter) + frontmatter_body.lstrip(),
                    encoding="utf-8",
                )
                continue
            title = _first_mdx_heading(
                "\n".join(frontmatter_lines) + "\n" + frontmatter_body, fallback_title
            )
            repaired_intro = "\n".join(frontmatter_lines).strip()
            if repaired_intro and frontmatter_body.lstrip():
                body_text = repaired_intro + "\n\n" + frontmatter_body.lstrip()
            elif repaired_intro:
                body_text = repaired_intro
            else:
                body_text = frontmatter_body.lstrip()
        else:
            title = _first_mdx_heading(text, fallback_title)

        frontmatter_lines = [
            "---",
            f"title: {json.dumps(title)}",
            f"description: {json.dumps('Auto-generated developer documentation')}",
        ]
        if mdx_path.name != "index.mdx":
            frontmatter_lines.append("_deepdoc_autogen_: true")
        frontmatter = "\n".join(frontmatter_lines) + "\n---\n\n"
        mdx_path.write_text(frontmatter + body_text.lstrip(), encoding="utf-8")

