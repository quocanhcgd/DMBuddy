"""In-process gateway for authenticated Connector WebSocket sessions.

Version one supports a single application instance. The registry is kept
behind this service so a shared broker/lease can replace it for scale-out
without changing the HTTP routes or protocol contract.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from fastapi import WebSocket

from connector_protocol import PROTOCOL_VERSION

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
        self._pending: dict[str, tuple[str, asyncio.Future[dict[str, Any]]]] = {}
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

    async def request(
        self,
        connector_id: str,
        message_type: str,
        payload: dict[str, Any],
        *,
        timeout: float = 15.0,
    ) -> dict[str, Any] | None:
        """Send one request and await its matching response payload."""
        request_id = str(payload.get("request_id") or uuid4())
        request_payload = {**payload, "request_id": request_id}
        loop = asyncio.get_running_loop()
        future: asyncio.Future[dict[str, Any]] = loop.create_future()
        async with self._lock:
            if connector_id not in self._sessions:
                return None
            self._pending[request_id] = (connector_id, future)
        sent = await self.send(
            connector_id,
            {
                "schema_version": PROTOCOL_VERSION,
                "message_id": request_id,
                "connector_id": connector_id,
                "type": message_type,
                "payload": request_payload,
            },
        )
        if not sent:
            async with self._lock:
                self._pending.pop(request_id, None)
            return None
        try:
            return await asyncio.wait_for(future, timeout=timeout)
        except asyncio.TimeoutError:
            self.record_event("request_timeouts_total")
            return None
        finally:
            async with self._lock:
                self._pending.pop(request_id, None)

    async def resolve_request(self, connector_id: str, payload: dict[str, Any]) -> bool:
        """Resolve a pending request from a Connector response."""
        request_id = payload.get("request_id")
        if not isinstance(request_id, str):
            return False
        async with self._lock:
            pending = self._pending.get(request_id)
        if pending is None:
            return False
        expected_connector_id, future = pending
        if expected_connector_id != connector_id or future.done():
            return False
        future.set_result(payload)
        return True

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
