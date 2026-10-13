"""How Grid's tools reach the person: each chat registers its UI here, keyed by
the conversation id the SDK hands to every tool executor."""

from __future__ import annotations

import os
import threading
from collections.abc import Callable
from dataclasses import dataclass

from grid.access import AccessStore, folder_for, is_under, pretty, protected_reason


@dataclass
class ToolHost:
    workspace: str
    ask: Callable[[str], str | None]      # returns None when nobody can answer (headless, autonomous)
    say: Callable[[str], None]
    safe_search: bool = False             # Teacher mode for under-18 users


_HOSTS: dict[str, ToolHost] = {}
_LOCK = threading.Lock()


def register(chat_id: str, host: ToolHost) -> None:
    with _LOCK:
        _HOSTS[chat_id] = host


def unregister(chat_id: str) -> None:
    with _LOCK:
        _HOSTS.pop(chat_id, None)


def host_for(conversation) -> tuple[str | None, ToolHost | None]:
    cid = str(getattr(conversation, "id", "") or "") or None
    with _LOCK:
        return cid, _HOSTS.get(cid) if cid else None


def ensure_access(conversation, path: str, reason: str, *, workspace: str | None = None) -> tuple[bool, str]:
    """(allowed, message). Inside the project or a granted folder is fine;
    otherwise ask the person (once / always / no) when someone can answer."""
    chat, host = host_for(conversation)
    ws = workspace or (host.workspace if host else None)
    real = os.path.realpath(os.path.expanduser(path))
    if ws and is_under(real, ws):
        return True, ""
    store = AccessStore()
    if store.allowed(real, chat):
        return True, ""
    folder = folder_for(real)
    why = protected_reason(folder)
    if why:
        return False, f"Grid can't use {pretty(folder)}: {why}."
    answer = None
    if host is not None:
        answer = host.ask(f"Grid wants to use {pretty(folder)} - {reason.strip() or 'to work with files there'}.\n"
                          "Allow? [o]nce for this chat / [a]lways / [n]o: ")
    if answer is None:
        return False, (f"Grid needs access to {pretty(folder)}, and nobody is here to approve it. "
                       "The user can allow it in Settings > Mac access.")
    answer = answer.strip().lower()
    if answer[:1] == "a":
        store.grant(folder, always=True, reason=reason)
        host.say(f"[grid][access] {pretty(folder)} allowed (always). Change it in Settings > Mac access.")
        return True, ""
    if answer[:1] == "o":
        store.grant(folder, chat=chat, reason=reason)
        host.say(f"[grid][access] {pretty(folder)} allowed for this chat.")
        return True, ""
    return False, f"The user didn't allow access to {pretty(folder)}. Don't try again unless they ask."
