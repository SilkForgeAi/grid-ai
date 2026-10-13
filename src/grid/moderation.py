"""Independent policy service gate, required in restricted execution mode.

The user configures the endpoint; nothing is sent to a default third party.
Only an explicit `{"decision": "allow"}` permits execution. Failures stop work.
"""

from __future__ import annotations

import os
import threading
from collections import OrderedDict
from urllib.parse import urlsplit

import httpx

_CONTEXTS = OrderedDict()
_LOCK = threading.Lock()


def set_context(chat_id, history):
    with _LOCK:
        _CONTEXTS[chat_id] = list(history)
        _CONTEXTS.move_to_end(chat_id)
        while len(_CONTEXTS) > 128:
            _CONTEXTS.popitem(last=False)


def get_context(chat_id):
    with _LOCK:
        return list(_CONTEXTS.get(chat_id, []))


def restricted_mode() -> bool:
    return os.environ.get("GRID_RESTRICTED", "").lower() in ("1", "true", "yes")


def policy_reason(text: str, *, kind: str, context: list[str] | None = None) -> str | None:
    endpoint = os.environ.get("GRID_POLICY_URL", "")
    if not endpoint:
        return "Restricted mode requires GRID_POLICY_URL." if restricted_mode() else None
    parts = urlsplit(endpoint)
    if (
        parts.username
        or parts.password
        or not parts.hostname
        or (
            parts.scheme != "https"
            and not (parts.scheme == "http" and parts.hostname in ("127.0.0.1", "localhost", "::1"))
        )
    ):
        return "Policy service must use HTTPS or a loopback HTTP endpoint, without URL credentials."
    payload = {"text": text, "kind": kind, "context": context or []}
    if len(text) + sum(map(len, payload["context"])) > 200_000:
        return "Policy input is too large; split the task into a smaller reviewable change."
    headers = {}
    if token := os.environ.get("GRID_POLICY_TOKEN"):
        headers["Authorization"] = f"Bearer {token}"
    try:
        with httpx.Client(timeout=15, follow_redirects=False, trust_env=False) as client:
            response = client.post(endpoint, json=payload, headers=headers)
            response.raise_for_status()
            if len(response.content) > 16_384:
                return "Policy service returned an invalid response; execution stopped."
            result = response.json()
        if not isinstance(result, dict) or result.get("decision") not in ("allow", "deny"):
            return "Policy service did not return an explicit decision; execution stopped."
        if result["decision"] == "deny":
            return "Independent safety review declined this request."
        return None
    except (httpx.HTTPError, ValueError):
        return "Independent safety review is unavailable; execution stopped."
