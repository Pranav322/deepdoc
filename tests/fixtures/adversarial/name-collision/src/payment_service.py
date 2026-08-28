# File: payment_service.py
def create(amount: float, method: str, reference: str = "") -> dict:
    """Create a payment transaction."""
    return {"txn_id": "txn_001", "amount": amount, "method": method, "reference": reference}