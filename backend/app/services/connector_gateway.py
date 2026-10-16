"""In-process gateway for authenticated Connector WebSocket sessions.

Version one supports a single application instance. The registry is kept
behind this service so a shared broker/lease can replace it for scale-out
without changing the HTTP routes or protocol contract.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

from fastapi import WebSocket

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class ConnectorSession:
    connector_id: str
    websocket: WebSocket
    send_lock: asyncio.Lock


class ConnectorGateway:
    def __init__(self) -> None:
        self._sessions: dict[str, ConnectorSession] = {}
        self._lock = asyncio.Lock()
        self._counters: dict[str, int] = {
            "sessions_started_total": 0,
            "session_replacements_total": 0,
            "session_disconnects_total": 0,
            "send_failures_total": 0,
        }

    async def register(self, connector_id: str, websocket: WebSocket) -> ConnectorSession:
        session = ConnectorSession(connector_id, websocket, asyncio.Lock())
        async with self._lock:
            previous = self._sessions.get(connector_id)
            self._sessions[connector_id] = session
            self._counters["sessions_started_total"] += 1
            if previous is not None:
                self._counters["session_replacements_total"] += 1
        if previous and previous.websocket is not websocket:
            try:
                await previous.websocket.close(code=4001, reason="Replaced by a newer Connector session")
            except Exception:  # pragma: no cover - peer may already be gone
                logger.debug("Previous Connector session already closed: %s", connector_id)
        return session

    async def get(self, connector_id: str) -> ConnectorSession | None:
        async with self._lock:
            return self._sessions.get(connector_id)

    async def unregister(self, session: ConnectorSession) -> bool:
        async with self._lock:
            if self._sessions.get(session.connector_id) is not session:
                return False
            del self._sessions[session.connector_id]
            self._counters["session_disconnects_total"] += 1
            return True

    async def send(self, connector_id: str, message: dict) -> bool:
        async with self._lock:
            session = self._sessions.get(connector_id)
        if not session:
            return False
        try:
            async with session.send_lock:
                await session.websocket.send_json(message)
            return True
        except Exception:
            async with self._lock:
                self._counters["send_failures_total"] += 1
            logger.info("Connector session send failed: %s", connector_id, exc_info=True)
            return False

    def is_online(self, connector_id: str) -> bool:
        return connector_id in self._sessions

    def active_count(self) -> int:
        return len(self._sessions)

    def record_event(self, name: str) -> None:
        """Record a bounded event counter for gateway observability."""
        if name.endswith("_total"):
            self._counters[name] = self._counters.get(name, 0) + 1

    def metrics(self) -> dict[str, int]:
        """Return a copy suitable for metrics exposition and tests."""
        return {**self._counters, "active_sessions": len(self._sessions)}


connector_gateway = ConnectorGateway()
