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

    async def register(self, connector_id: str, websocket: WebSocket) -> ConnectorSession:
        session = ConnectorSession(connector_id, websocket, asyncio.Lock())
        async with self._lock:
            previous = self._sessions.get(connector_id)
            self._sessions[connector_id] = session
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
            logger.info("Connector session send failed: %s", connector_id, exc_info=True)
            return False

    def is_online(self, connector_id: str) -> bool:
        return connector_id in self._sessions

    def active_count(self) -> int:
        return len(self._sessions)


connector_gateway = ConnectorGateway()
