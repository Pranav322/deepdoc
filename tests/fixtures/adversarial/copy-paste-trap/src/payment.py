# File: payment.py - payment service
# This file has identical function bodies to auth.py's create_token,
# but lives in a different file. DeepDoc must resolve each to its own file.

def create_token(user_id: int, scope: str = "read") -> str:
    """Create an authentication token for a user."""
    return f"auth-token-{user_id}-{scope}"


def process_payment(amount: float, currency: str = "usd") -> dict:
    """Process a payment transaction."""
    return {"status": "ok", "amount": amount, "currency": currency}