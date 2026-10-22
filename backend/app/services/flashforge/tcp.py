"""Exclusive AD5M TCP command channel for full file listing."""

from __future__ import annotations

import asyncio
import re
import socket
import threading
import time
import weakref

from backend.app.services.flashforge.errors import (
    FlashForgeCommandBusyError,
    FlashForgeResponseTooLargeError,
    FlashForgeTransportError,
)
from backend.app.services.printer_providers.flashforge_contract import (
    contract_for,
    normalize_flashforge_host,
    validate_flashforge_options,
)

DEFAULT_CONNECT_TIMEOUT_SECONDS = 3.0
DEFAULT_COMMAND_TIMEOUT_SECONDS = 8.0
DEFAULT_SETTLE_SECONDS = 1.4
DEFAULT_MAX_RESPONSE_BYTES = 2 * 1024 * 1024
_LOCKS: dict[tuple[str, int], threading.Lock] = {}
_LOCKS_GUARD = threading.Lock()
_ASYNC_LOCKS: weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, dict[tuple[str, int], asyncio.Lock]] = (
    weakref.WeakKeyDictionary()
)
_ASYNC_LOCKS_GUARD = threading.Lock()


class FlashForgeTcpClient:
    """TCP command client. Creator 5 is rejected by contract before socket use."""

    def __init__(
        self,
        *,
        host: str,
        provider: str,
        model: str | None = None,
        port: int | None = None,
        connect_timeout: float = DEFAULT_CONNECT_TIMEOUT_SECONDS,
        command_timeout: float = DEFAULT_COMMAND_TIMEOUT_SECONDS,
        settle_seconds: float = DEFAULT_SETTLE_SECONDS,
        max_response_bytes: int = DEFAULT_MAX_RESPONSE_BYTES,
        lock_timeout: float = 1.0,
        socket_factory=socket.create_connection,
    ) -> None:
        contract, self.model = contract_for(provider, model)
        if contract.tcp_port is None:
            raise ValueError("This FlashForge model does not support the TCP command port")
        options = validate_flashforge_options(provider, self.model, {"tcp_port": port} if port is not None else None)
        if min(connect_timeout, command_timeout, settle_seconds, max_response_bytes, lock_timeout) <= 0:
            raise ValueError("FlashForge TCP limits must be positive")
        self.host = normalize_flashforge_host(host)
        self.port = options["tcp_port"]
        self.connect_timeout = connect_timeout
        self.command_timeout = command_timeout
        self.settle_seconds = settle_seconds
        self.max_response_bytes = max_response_bytes
        self.lock_timeout = lock_timeout
        self._socket_factory = socket_factory
        self._lock = _endpoint_lock((self.host, self.port))
        self._async_lock_key = (self.host, self.port)

    async def list_files_raw_async(self) -> str:
        """Async-native M601/M661/M602 transaction with cancellation cleanup."""

        lock = _async_endpoint_lock(self._async_lock_key)
        try:
            await asyncio.wait_for(lock.acquire(), timeout=self.lock_timeout)
        except TimeoutError as exc:
            raise FlashForgeCommandBusyError("FlashForge TCP command channel is busy") from exc

        writer: asyncio.StreamWriter | None = None
        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(self.host, self.port),
                timeout=self.connect_timeout,
            )
            sock = writer.get_extra_info("socket")
            if sock is not None:
                sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)

            writer.write(b"~M601 S1\n")
            await asyncio.wait_for(writer.drain(), timeout=self.command_timeout)
            acquire_response = await _async_read_until_quiet(
                reader, self.settle_seconds, self.command_timeout, self.max_response_bytes
            )
            if _is_busy_or_failed(acquire_response):
                raise FlashForgeCommandBusyError("FlashForge printer control channel is busy")
            if not _control_acquired(acquire_response):
                raise FlashForgeTransportError("FlashForge printer did not accept the TCP control session")

            writer.write(b"~M661\n")
            await asyncio.wait_for(writer.drain(), timeout=self.command_timeout)
            response = await _async_read_until_quiet(
                reader, self.settle_seconds, self.command_timeout, self.max_response_bytes
            )
            return response.decode("utf-8", errors="replace")
        except (FlashForgeCommandBusyError, FlashForgeResponseTooLargeError, FlashForgeTransportError):
            raise
        except TimeoutError as exc:
            raise FlashForgeTransportError("FlashForge TCP file listing timed out") from exc
        except OSError as exc:
            raise FlashForgeTransportError("FlashForge TCP file listing failed") from exc
        finally:
            if writer is not None:
                cleanup = asyncio.create_task(_async_release_and_close(writer, self.command_timeout))
                try:
                    await asyncio.shield(cleanup)
                except asyncio.CancelledError:
                    await cleanup
                    raise
            lock.release()

    def list_files_raw(self) -> str:
        """Acquire the printer lock, read M661 chunks until idle, then release."""

        if not self._lock.acquire(timeout=self.lock_timeout):
            raise FlashForgeCommandBusyError("FlashForge TCP command channel is busy")
        sock: socket.socket | None = None
        try:
            sock = self._socket_factory((self.host, self.port), timeout=self.connect_timeout)
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            sock.settimeout(self.command_timeout)
            sock.sendall(b"~M601 S1\n")
            acquire_response = _read_until_quiet(sock, self.settle_seconds, self.command_timeout, self.max_response_bytes)
            if _is_busy_or_failed(acquire_response):
                raise FlashForgeCommandBusyError("FlashForge printer control channel is busy")
            if not _control_acquired(acquire_response):
                raise FlashForgeTransportError("FlashForge printer did not accept the TCP control session")

            sock.sendall(b"~M661\n")
            return _read_until_quiet(sock, self.settle_seconds, self.command_timeout, self.max_response_bytes).decode(
                "utf-8", errors="replace"
            )
        except (FlashForgeCommandBusyError, FlashForgeResponseTooLargeError):
            raise
        except (OSError, TimeoutError) as exc:
            raise FlashForgeTransportError("FlashForge TCP file listing failed") from exc
        finally:
            if sock is not None:
                _release_printer_lock(sock, self.command_timeout)
                try:
                    sock.close()
                except OSError:
                    pass
            self._lock.release()


def _endpoint_lock(endpoint: tuple[str, int]) -> threading.Lock:
    with _LOCKS_GUARD:
        return _LOCKS.setdefault(endpoint, threading.Lock())


def _async_endpoint_lock(endpoint: tuple[str, int]) -> asyncio.Lock:
    loop = asyncio.get_running_loop()
    with _ASYNC_LOCKS_GUARD:
        loop_locks = _ASYNC_LOCKS.setdefault(loop, {})
        return loop_locks.setdefault(endpoint, asyncio.Lock())


def _read_until_quiet(sock: socket.socket, settle_seconds: float, timeout_seconds: float, max_bytes: int) -> bytes:
    deadline = time.monotonic() + timeout_seconds
    chunks = bytearray()
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            if chunks:
                return bytes(chunks)
            raise TimeoutError("No response from FlashForge TCP endpoint")
        sock.settimeout(min(settle_seconds, remaining))
        try:
            chunk = sock.recv(min(65536, max_bytes + 1 - len(chunks)))
        except TimeoutError:
            if chunks:
                return bytes(chunks)
            continue
        if not chunk:
            return bytes(chunks)
        chunks.extend(chunk)
        if len(chunks) > max_bytes:
            raise FlashForgeResponseTooLargeError("FlashForge TCP response exceeded the configured size limit")


async def _async_read_until_quiet(
    reader: asyncio.StreamReader, settle_seconds: float, timeout_seconds: float, max_bytes: int
) -> bytes:
    deadline = time.monotonic() + timeout_seconds
    chunks = bytearray()
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            if chunks:
                return bytes(chunks)
            raise TimeoutError("No response from FlashForge TCP endpoint")
        try:
            chunk = await asyncio.wait_for(reader.read(min(65536, max_bytes + 1 - len(chunks))), timeout=min(settle_seconds, remaining))
        except TimeoutError:
            if chunks:
                return bytes(chunks)
            continue
        if not chunk:
            return bytes(chunks)
        chunks.extend(chunk)
        if len(chunks) > max_bytes:
            raise FlashForgeResponseTooLargeError("FlashForge TCP response exceeded the configured size limit")


async def _async_release_and_close(writer: asyncio.StreamWriter, timeout: float) -> None:
    try:
        writer.write(b"~M602\n")
        await asyncio.wait_for(writer.drain(), timeout=min(timeout, 1.2))
    except (OSError, TimeoutError, RuntimeError):
        pass
    writer.close()
    try:
        await asyncio.wait_for(writer.wait_closed(), timeout=min(timeout, 1.2))
    except (OSError, TimeoutError, RuntimeError):
        pass


def _is_busy_or_failed(response: bytes) -> bool:
    text = response.decode("utf-8", errors="ignore").lower()
    return any(marker in text for marker in ("control failed", "control busy", "have been connected", "busy", "failed", "error", "denied"))


def _control_acquired(response: bytes) -> bool:
    text = response.decode("utf-8", errors="ignore")
    return "control success" in text.lower() or _has_ok_terminator(text)


def _has_ok_terminator(value: str) -> bool:
    return bool(re.search(r"(?:^|\r?\n)ok(?:\r?\n|$)", value, flags=re.IGNORECASE))


def _release_printer_lock(sock: socket.socket, timeout: float) -> None:
    try:
        sock.settimeout(timeout)
        sock.sendall(b"~M602\n")
    except OSError:
        pass
