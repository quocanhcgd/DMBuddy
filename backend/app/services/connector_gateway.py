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


class ConnectorRequestDeliveryUnknown(RuntimeError):
    """A side-effect request may have reached Connector, but no result arrived."""

    def __init__(self, request_id: str) -> None:
        super().__init__("Connector request delivery outcome is unknown")
        self.request_id = request_id


@dataclass(slots=True)
class ConnectorSession:
    connector_id: str
    websocket: WebSocket
    send_lock: asyncio.Lock


@dataclass(slots=True)
class PendingConnectorRequest:
    connector_id: str
    session: ConnectorSession
    response_type: str
    future: asyncio.Future[dict[str, Any] | None]


_RESPONSE_TYPES = {
    "discovery.request": "discovery.result",
    "printer.verify.request": "printer.verify.result",
    "printer.status.request": "printer.status.result",
    "printer.files.request": "printer.files.result",
    "printer.upload.request": "printer.upload.result",
    "printer.control.request": "printer.control.result",
    "printer.temperature.request": "printer.temperature.result",
}
_SIDE_EFFECT_REQUEST_TYPES = {
    "printer.upload.request",
    "printer.control.request",
    "printer.temperature.request",
}


class ConnectorGateway:
    def __init__(self) -> None:
        self._sessions: dict[str, ConnectorSession] = {}
        self._lock = asyncio.Lock()
        self._pending: dict[tuple[str, str], PendingConnectorRequest] = {}
        self._counters: dict[str, int] = {
            "sessions_started_total": 0,
            "session_replacements_total": 0,
            "session_disconnects_total": 0,
            "send_failures_total": 0,
            "request_timeouts_total": 0,
            "request_delivery_unknown_total": 0,
            "request_cancellations_total": 0,
            "late_or_unknown_responses_total": 0,
            "response_session_mismatches_total": 0,
            "response_type_mismatches_total": 0,
            "duplicate_responses_total": 0,
        }

    async def register(self, connector_id: str, websocket: WebSocket) -> ConnectorSession:
        session = ConnectorSession(connector_id, websocket, asyncio.Lock())
        async with self._lock:
            previous = self._sessions.get(connector_id)
            self._sessions[connector_id] = session
            self._counters["sessions_started_total"] += 1
            if previous is not None:
                self._counters["session_replacements_total"] += 1
                self._resolve_session_pending_locked(previous)
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
            self._resolve_session_pending_locked(session)
            return True

    def _resolve_session_pending_locked(self, session: ConnectorSession) -> None:
        for pending in self._pending.values():
            if pending.session is session and not pending.future.done():
                pending.future.set_result(None)

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
        response_type = _RESPONSE_TYPES.get(message_type)
        if response_type is None:
            raise ValueError("Unsupported Connector request type")
        request_id = str(payload.get("request_id") or uuid4())
        if not request_id or len(request_id) > 64:
            raise ValueError("Connector request_id must contain 1-64 characters")
        request_payload = {**payload, "request_id": request_id}
        loop = asyncio.get_running_loop()
        future: asyncio.Future[dict[str, Any] | None] = loop.create_future()
        key = (connector_id, request_id)
        delivery_attempted = False
        async with self._lock:
            session = self._sessions.get(connector_id)
            if session is None:
                return None
            if key in self._pending:
                raise ValueError("Connector request_id is already pending")
            pending = PendingConnectorRequest(connector_id, session, response_type, future)
            self._pending[key] = pending
        try:
            async with asyncio.timeout(timeout):
                async with session.send_lock:
                    delivery_attempted = True
                    await session.websocket.send_json(
                        {
                            "schema_version": PROTOCOL_VERSION,
                            "message_id": request_id,
                            "connector_id": connector_id,
                            "type": message_type,
                            "payload": request_payload,
                        }
                    )
                response = await future
                if response is None and delivery_attempted and message_type in _SIDE_EFFECT_REQUEST_TYPES:
                    self.record_event("request_delivery_unknown_total")
                    raise ConnectorRequestDeliveryUnknown(request_id)
                return response
        except TimeoutError:
            self.record_event("request_timeouts_total")
            if delivery_attempted and message_type in _SIDE_EFFECT_REQUEST_TYPES:
                self.record_event("request_delivery_unknown_total")
                raise ConnectorRequestDeliveryUnknown(request_id) from None
            return None
        except asyncio.CancelledError:
            self.record_event("request_cancellations_total")
            raise
        except ConnectorRequestDeliveryUnknown:
            raise
        except Exception:
            self.record_event("send_failures_total")
            logger.info("Connector request send failed: %s", connector_id)
            if delivery_attempted and message_type in _SIDE_EFFECT_REQUEST_TYPES:
                self.record_event("request_delivery_unknown_total")
                raise ConnectorRequestDeliveryUnknown(request_id) from None
            return None
        finally:
            async with self._lock:
                if self._pending.get(key) is pending:
                    self._pending.pop(key, None)
                if not future.done():
                    future.cancel()

    async def resolve_request(
        self,
        connector_id: str,
        session: ConnectorSession,
        response_type: str,
        payload: dict[str, Any],
    ) -> bool:
        """Resolve a pending request from a Connector response."""
        request_id = payload.get("request_id")
        if not isinstance(request_id, str) or not request_id:
            return False
        async with self._lock:
            key = (connector_id, request_id)
            pending = self._pending.get(key)
            if pending is None:
                self.record_event("late_or_unknown_responses_total")
                return False
            if pending.connector_id != connector_id or pending.session is not session:
                self.record_event("response_session_mismatches_total")
                return False
            if pending.response_type != response_type:
                self.record_event("response_type_mismatches_total")
                return False
            if pending.future.done():
                self.record_event("duplicate_responses_total")
                return False
            pending.future.set_result(payload)
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
