"""Hard per-generation spend cap for the hosted runner.

Python imports ``sitecustomize`` at interpreter start, and the runner puts this
directory on ``PYTHONPATH`` only for the ``deepdoc`` subprocesses it launches. It
does nothing unless ``DEEPDOC_BUDGET_FILE`` is set.

It wraps ``litellm.completion`` so every real response's token usage is priced
(``DEEPDOC_PRICE_IN_PER_M`` / ``DEEPDOC_PRICE_OUT_PER_M`` USD per million tokens)
and added to a running total. When the total passes ``DEEPDOC_MAX_USD`` the process
exits immediately with code 75 and a one-line reason on stderr, which the
runner surfaces to the user as the failure message.

The cap is deliberately enforced outside deepdoc itself: it works for any
provider, needs no change to deepdoc's retry classification, and cannot be
bypassed by a repo's own config.
"""
from __future__ import annotations

import json
import os
import sys
import threading

_BUDGET_FILE = os.environ.get("DEEPDOC_BUDGET_FILE")


def _install() -> None:
    try:
        max_usd = float(os.environ.get("DEEPDOC_MAX_USD", "1.00"))
        price_in = float(os.environ.get("DEEPDOC_PRICE_IN_PER_M", "0"))
        price_out = float(os.environ.get("DEEPDOC_PRICE_OUT_PER_M", "0"))
        import litellm  # noqa: WPS433 - imported lazily, only when armed
    except Exception:  # noqa: BLE001 - never break the host process
        return

    lock = threading.Lock()
    state = {"in": 0, "out": 0, "usd": 0.0, "calls": 0}
    original = litellm.completion

    def account(response) -> None:
        usage = getattr(response, "usage", None)
        if usage is None:
            return
        tin = int(getattr(usage, "prompt_tokens", 0) or 0)
        tout = int(getattr(usage, "completion_tokens", 0) or 0)
        with lock:
            state["in"] += tin
            state["out"] += tout
            state["calls"] += 1
            state["usd"] = (state["in"] * price_in + state["out"] * price_out) / 1_000_000
            snapshot = dict(state)
        try:
            with open(_BUDGET_FILE, "w", encoding="utf-8") as fh:
                json.dump(snapshot, fh)
        except OSError:
            pass
        if snapshot["usd"] > max_usd:
            sys.stderr.write(
                f"BUDGET EXCEEDED: spent ${snapshot['usd']:.2f} of the ${max_usd:.2f} per-generation "
                f"limit after {snapshot['calls']} calls ({snapshot['in']:,} in / {snapshot['out']:,} out tokens). "
                "Stopping so the run does not cost more.\n"
            )
            sys.stderr.flush()
            os._exit(75)

    def completion(*args, **kwargs):
        response = original(*args, **kwargs)
        account(response)
        return response

    litellm.completion = completion


if _BUDGET_FILE:
    _install()
