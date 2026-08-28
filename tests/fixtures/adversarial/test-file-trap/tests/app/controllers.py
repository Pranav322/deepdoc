# This file lives in tests/app/ but looks exactly like production code.
# DeepDoc must classify it as "test" regardless of the filename "controllers.py".
# It must NEVER appear in evidence or produce RouteRecords.

from flask import Blueprint, jsonify

users_bp = Blueprint('users', __name__)

@users_bp.route('/api/users', methods=['GET'])
def list_users():
    return jsonify([{"id": 1, "name": "Test User"}])

@users_bp.route('/api/users/<int:user_id>', methods=['GET'])
def get_user(user_id):
    return jsonify({"id": user_id, "name": f"User {user_id}"})