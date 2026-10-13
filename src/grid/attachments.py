"""Images in chats: what the user pasted or dropped in, and screenshots tools took.

Stored under ~/.grid/attachments so the app can show them again (chat history)
and the model gets them as data URLs. Old files are pruned after 30 days.
"""

from __future__ import annotations

import base64
import binascii
import os
import random
import re
import time
import uuid
from pathlib import Path

from grid.project import grid_home

MAX_BYTES = 8 * 1024 * 1024
MAX_IMAGES = 6
MIME_EXT = {"image/png": "png", "image/jpeg": "jpg", "image/gif": "gif", "image/webp": "webp"}
EXT_MIME = {v: k for k, v in MIME_EXT.items()} | {"jpeg": "image/jpeg"}
_ID = re.compile(r"^[0-9a-f]{20}\.(png|jpg|gif|webp)$")
_SIGS = {b"\x89PNG": "image/png", b"\xff\xd8\xff": "image/jpeg", b"GIF8": "image/gif"}


class AttachmentError(ValueError):
    pass


def root() -> Path:
    return grid_home() / "attachments"


def sniff(data: bytes) -> str | None:
    for sig, mime in _SIGS.items():
        if data.startswith(sig):
            return mime
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


def save(data: bytes, mime: str | None = None) -> str:
    """Store image bytes; returns the attachment id (e.g. '3f2a...c1.png')."""
    if len(data) > MAX_BYTES:
        raise AttachmentError("images must be under 8 MB")
    real = sniff(data)
    if real is None or (mime and mime in MIME_EXT and MIME_EXT[mime] != MIME_EXT[real]):
        raise AttachmentError("only PNG, JPEG, GIF or WebP images")
    d = root()
    d.mkdir(parents=True, exist_ok=True)
    aid = f"{uuid.uuid4().hex[:20]}.{MIME_EXT[real]}"
    (d / aid).write_bytes(data)
    _prune(d)
    return aid


def save_data_url(url: str) -> str:
    m = re.match(r"^data:(image/[\w+.-]+);base64,(.+)$", url or "", re.S)
    if not m:
        raise AttachmentError("expected an image")
    try:
        data = base64.b64decode(m.group(2), validate=False)
    except (binascii.Error, ValueError) as exc:
        raise AttachmentError("that image couldn't be read") from exc
    return save(data, m.group(1))


def path_for(aid: str) -> Path:
    if not _ID.match(aid or ""):
        raise AttachmentError("no such attachment")
    p = root() / aid
    if not p.is_file():
        raise AttachmentError("no such attachment")
    return p


def data_url(aid: str) -> str:
    p = path_for(aid)
    mime = EXT_MIME[p.suffix.lstrip(".")]
    return f"data:{mime};base64,{base64.b64encode(p.read_bytes()).decode()}"


def _prune(d: Path, days: int = 30) -> None:
    if random.random() > 0.05:      # only now and then
        return
    cutoff = time.time() - days * 86400
    for f in d.iterdir():
        try:
            if f.stat().st_mtime < cutoff:
                os.remove(f)
        except OSError:
            pass


def shrink(data: bytes, max_side: int = 1568) -> tuple[bytes, str, int, int]:
    """Downscale big images (models see ~1.5k px anyway). Returns (bytes, mime, w, h)."""
    from io import BytesIO

    from PIL import Image

    im = Image.open(BytesIO(data))
    im.load()
    w, h = im.size
    scale = min(1.0, max_side / max(w, h))
    if scale < 1.0:
        im = im.resize((max(1, int(w * scale)), max(1, int(h * scale))), Image.LANCZOS)
    out = BytesIO()
    if im.mode in ("RGBA", "LA", "P"):
        im.save(out, "PNG", optimize=True)
        mime = "image/png"
    else:
        im.convert("RGB").save(out, "JPEG", quality=85)
        mime = "image/jpeg"
    return out.getvalue(), mime, im.size[0], im.size[1]
