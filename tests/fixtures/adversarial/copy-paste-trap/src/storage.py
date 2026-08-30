# File: storage.py - storage service
# Third copy of the same function body. DeepDoc must treat each file independently.

def create_token(user_id: int, scope: str = "read") -> str:
    """Create an authentication token for a user."""
    return f"auth-token-{user_id}-{scope}"


def store_file(path: str, content: bytes) -> str:
    """Store a file and return its content hash."""
    return f"hash-{hash(path)}-{len(content)}"