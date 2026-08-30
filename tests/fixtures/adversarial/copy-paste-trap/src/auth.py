# File: auth.py - authentication service
# DeepDoc must NOT conflate the 3 create_token functions across files.
# Each is distinct because it lives in a different file.

def create_token(user_id: int, scope: str = "read") -> str:
    """Create an authentication token for a user."""
    return f"auth-token-{user_id}-{scope}"


def verify_token(token: str) -> dict:
    """Verify and decode an authentication token."""
    parts = token.split("-")
    return {"user_id": int(parts[2]), "scope": parts[3]}