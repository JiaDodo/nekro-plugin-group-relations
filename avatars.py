"""Fetch bounded QQ avatars once and embed them in self-contained reports."""
from __future__ import annotations

import asyncio
import base64
import re
import time
from pathlib import Path

import httpx

TTL = 86400 * 3
MAX_BYTES = 512 * 1024
UIN = re.compile(r"[1-9]\d{4,11}\Z")


def data_uri(data: bytes) -> str:
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        mime = "image/png"
    elif data.startswith(b"\xff\xd8\xff"):
        mime = "image/jpeg"
    elif data.startswith((b"GIF87a", b"GIF89a")):
        mime = "image/gif"
    elif data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        mime = "image/webp"
    else:
        return ""
    return f"data:{mime};base64," + base64.b64encode(data).decode()


class AvatarCache:
    def __init__(self, folder: Path):
        self.folder = folder
        self.slots = asyncio.Semaphore(6)
        self.locks = {}
        self.failed = {}

    async def get(self, uid: str, client: httpx.AsyncClient) -> str:
        if not UIN.fullmatch(uid):
            return ""
        async with self.locks.setdefault(uid, asyncio.Lock()):
            path = self.folder / f"{uid}.bin"
            stale = ""
            if path.exists() and path.stat().st_size <= MAX_BYTES:
                stale = data_uri(await asyncio.to_thread(path.read_bytes))
                if stale and time.time() - path.stat().st_mtime < TTL:
                    return stale
            if time.monotonic() - self.failed.get(uid, -1000) < 300:
                return stale
            try:
                async with self.slots:
                    async with client.stream("GET", f"https://q1.qlogo.cn/g?b=qq&nk={uid}&s=100") as response:
                        response.raise_for_status()
                        content = bytearray()
                        async for chunk in response.aiter_bytes():
                            content.extend(chunk)
                            if len(content) > MAX_BYTES:
                                raise ValueError("头像过大")
                result = data_uri(bytes(content))
                if not result:
                    raise ValueError("头像格式无效")
                self.folder.mkdir(parents=True, exist_ok=True)
                await asyncio.to_thread(path.write_bytes, bytes(content))
                self.failed.pop(uid, None)
                return result
            except (httpx.HTTPError, OSError, ValueError):
                self.failed[uid] = time.monotonic()
                return stale

    async def load(self, ids: list[str]) -> dict[str, str]:
        async with httpx.AsyncClient(timeout=6, follow_redirects=False) as client:
            values = await asyncio.gather(*(self.get(uid, client) for uid in dict.fromkeys(ids)))
        return {uid: value for uid, value in zip(dict.fromkeys(ids), values) if value}

    def purge(self):
        if self.folder.exists():
            for file in self.folder.glob("*.bin"):
                file.unlink(missing_ok=True)
        self.failed.clear()
