# File: user_service.py
# Name collision test: 5 files, each with "def create(...)".
# DeepDoc's call graph must resolve each "create" to its own file,
# NEVER conflating them into a single symbol.

def create(name: str, email: str) -> dict:
    """Create a user."""
    return {"id": 1, "name": name, "email": email}