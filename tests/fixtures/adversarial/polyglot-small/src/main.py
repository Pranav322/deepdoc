# File: main.py - Python service
# Part of the polyglot-small fixture: supported language, fully parsed.

def process(data: dict) -> dict:
    """Process incoming data."""
    return {"result": data.get("value", 0) * 2}