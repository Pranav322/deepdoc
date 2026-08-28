# This file lives in tests/fixtures/ and defines realistic endpoints.
# DeepDoc must classify it as "fixture" and never produce RouteRecords from it.

from flask import Flask

app = Flask(__name__)

@app.route('/api/payments/charge', methods=['POST'])
def charge():
    return {"status": "ok"}

@app.route('/api/payments/refund/<string:txn_id>', methods=['POST'])
def refund(txn_id):
    return {"status": "ok", "txn_id": txn_id}