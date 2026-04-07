from __future__ import annotations

import json
import re
from typing import Any

TRAILING_COMMA_RE = re.compile(r",(\s*[}\]])")
VALUE_END_CHARS = set('}]"0123456789eln')
VALUE_START_CHARS = set('{"[-0123456789tfn')
SMART_QUOTES = str.maketrans(
    {
        "\u2018": "'",
        "\u2019": "'",
        "\u201c": '"',
        "\u201d": '"',
    }
)


def parse_llm_json(response: str) -> Any:
    """Parse LLM-emitted JSON with light recovery for common formatting mistakes."""
    text = _strip_code_fences(response).translate(SMART_QUOTES).strip()
    if not text:
        raise ValueError("empty LLM JSON response")

    last_error: Exception | None = None
    candidates = [text]
    extracted = _extract_first_json_value(text)
    if extracted and extracted != text:
        candidates.append(extracted)

    for candidate in candidates:
        try:
            return _loads_with_repairs(candidate)
        except Exception as exc:  # pragma: no cover - keeps original failure detail
            last_error = exc

    if last_error is not None:
        raise last_error
    raise ValueError("no JSON object found in LLM response")


def _strip_code_fences(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        lines = [line for line in lines if not line.strip().startswith("```")]
        stripped = "\n".join(lines)
    return stripped


def _extract_first_json_value(text: str) -> str | None:
    start = None
    for idx, ch in enumerate(text):
        if ch in "{[":
            start = idx
            break
    if start is None:
        return None

    stack = [text[start]]
    in_string = False
    escape = False

    for idx in range(start + 1, len(text)):
        ch = text[idx]
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            continue

        if ch == '"':
            in_string = True
            continue
        if ch in "{[":
            stack.append(ch)
            continue
        if ch in "}]":
            if not stack:
                return None
            opener = stack.pop()
            if (opener, ch) not in {("{", "}"), ("[", "]")}:
                return None
            if not stack:
                return text[start : idx + 1]

    return None


def _loads_with_repairs(text: str) -> Any:
    candidate = text.strip()
    seen: set[str] = set()
    last_error: json.JSONDecodeError | None = None

    for _ in range(8):
        if candidate in seen:
            break
        seen.add(candidate)
        try:
            return json.loads(candidate)
        except json.JSONDecodeError as exc:
            last_error = exc
            repaired = _repair_json_candidate(candidate, exc)
            if repaired == candidate:
                break
            candidate = repaired

    if last_error is not None:
        raise last_error
    return json.loads(candidate)


def _repair_json_candidate(text: str, exc: json.JSONDecodeError) -> str:
    trimmed = TRAILING_COMMA_RE.sub(r"\1", text)
    if trimmed != text:
        return trimmed

    if exc.msg == "Extra data":
        extracted = _extract_first_json_value(text)
        if extracted and extracted != text:
            return extracted

    if "Expecting ',' delimiter" in exc.msg:
        insert_at = _missing_comma_position(text, exc.pos)
        if insert_at is not None:
            return text[:insert_at] + "," + text[insert_at:]

    if exc.msg in ("Expecting value", "Unexpected UTF-8 BOM"):
        extracted = _extract_first_json_value(text)
        if extracted and extracted != text:
            return extracted

    return text


def _missing_comma_position(text: str, error_pos: int) -> int | None:
    current = _next_significant_index(text, error_pos)
    previous = _previous_significant_index(
        text, current - 1 if current is not None else error_pos - 1
    )
    if current is None or previous is None:
        return None

    prev_char = text[previous]
    curr_char = text[current]
    if prev_char in VALUE_END_CHARS and curr_char in VALUE_START_CHARS:
        return current
    return None


def _previous_significant_index(text: str, start: int) -> int | None:
    idx = start
    while idx >= 0:
        if not text[idx].isspace():
            return idx
        idx -= 1
    return None


def _next_significant_index(text: str, start: int) -> int | None:
    idx = max(start, 0)
    while idx < len(text):
        if not text[idx].isspace():
            return idx
        idx += 1
    return None
