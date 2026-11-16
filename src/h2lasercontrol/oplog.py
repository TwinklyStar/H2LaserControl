"""Operation log: who did what, when, with which raw commands. One JSON object per line,
one file per day: logs/oplog-YYYY-MM-DD.jsonl.

Each line is written, flushed and fsync'ed immediately, so a crash loses at most the line
being written. A truncated last line is skipped by `read_oplog` and does not corrupt later lines.
"""

from __future__ import annotations

import getpass
import json
import logging
import os
import threading
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)


class OpLog:
    def __init__(
        self,
        directory: str | os.PathLike[str] = "logs",
        user: str | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now().astimezone(),
    ) -> None:
        self.directory = Path(directory)
        self.user = user or getpass.getuser()
        self._clock = clock
        self._lock = threading.Lock()

    def path_for(self, when: datetime) -> Path:
        return self.directory / f"oplog-{when:%Y-%m-%d}.jsonl"

    def write(
        self,
        *,
        device: str,
        action: str,
        event: str = "done",
        args: dict[str, Any] | None = None,
        result: Any = None,
        error: str | None = None,
        exchanges: list[tuple[bytes, bytes | None]] | None = None,
        duration_s: float | None = None,
    ) -> dict[str, Any]:
        """Append one entry. `event` is "start" (long action begun), "done" or "failed"."""
        now = self._clock()
        entry: dict[str, Any] = {
            "time": now.isoformat(timespec="milliseconds"),
            "user": self.user,
            "device": device,
            "action": action,
            "event": event,
            "args": args or {},
            "result": result,
            "error": error,
            "exchanges": [[_text(tx), _text(rx)] for tx, rx in (exchanges or [])],
            "duration_s": None if duration_s is None else round(duration_s, 3),
        }
        line = json.dumps(entry, ensure_ascii=False, default=str) + "\n"
        path = self.path_for(now)
        with self._lock:
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, "a+b") as f:
                # if a previous crash left a half line, start on a fresh line
                if f.tell() > 0:
                    f.seek(-1, os.SEEK_END)
                    if f.read(1) != b"\n":
                        f.write(b"\n")
                f.write(line.encode("utf-8"))
                f.flush()
                os.fsync(f.fileno())
        return entry


def _text(data: bytes | None) -> str | None:
    """Raw bytes as readable text; control characters survive as JSON escapes (\\r, \\u0007)."""
    return None if data is None else data.decode("latin-1")


def read_oplog(path: str | os.PathLike[str]) -> list[dict[str, Any]]:
    entries = []
    with open(path, encoding="utf-8") as f:
        for n, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                log.warning("%s line %d is incomplete (crash while writing?), skipped", path, n)
    return entries
