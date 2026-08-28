# File: product_service.py
def create(sku: str, price: float, stock: int = 0) -> dict:
    """Create a product listing."""
    return {"sku": sku, "price": price, "stock": stock}