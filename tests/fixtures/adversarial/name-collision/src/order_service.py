# File: order_service.py
def create(customer_id: int, items: list[dict]) -> dict:
    """Create an order."""
    return {"order_id": 101, "customer_id": customer_id, "items": items}