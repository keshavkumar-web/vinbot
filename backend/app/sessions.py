"""In-memory, thread-safe conversation store keyed by session id.

Each browser tab gets its own session id and therefore its own isolated chat
history. History is trimmed to the most recent ``MAX_HISTORY_MESSAGES`` entries,
mirroring the sliding window from the original CLI script.

Note: this store is process-local and non-persistent. For multi-worker or
multi-instance deployments, swap this for Redis or a database.
"""

import threading
import uuid

from . import config


class SessionStore:
    def __init__(self) -> None:
        self._sessions: dict[str, list[dict]] = {}
        self._lock = threading.Lock()

    def create(self) -> str:
        """Create a new empty session and return its id."""
        sid = uuid.uuid4().hex
        with self._lock:
            self._sessions[sid] = []
        return sid

    def exists(self, sid: str) -> bool:
        with self._lock:
            return sid in self._sessions

    def get(self, sid: str) -> list[dict]:
        """Return a copy of the session history (safe to iterate without the lock)."""
        with self._lock:
            return list(self._sessions.get(sid, []))

    def append(self, sid: str, role: str, content: str) -> None:
        """Append a message and trim the history to the configured window."""
        with self._lock:
            history = self._sessions.setdefault(sid, [])
            history.append({"role": role, "content": content})
            if len(history) > config.MAX_HISTORY_MESSAGES:
                self._sessions[sid] = history[-config.MAX_HISTORY_MESSAGES:]

    def reset(self, sid: str) -> None:
        """Clear a session's history (keeps the same session id)."""
        with self._lock:
            if sid in self._sessions:
                self._sessions[sid] = []


# Single shared store for the process.
store = SessionStore()
