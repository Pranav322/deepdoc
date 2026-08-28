# File: notification_service.py
def create(user_id: int, event: str, message: str) -> dict:
    """Create a notification."""
    return {"notif_id": 1, "user_id": user_id, "event": event, "message": message}