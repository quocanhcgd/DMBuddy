from __future__ import annotations

import asyncio
import json
import socket
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import httpx
import pytest

from backend.app.services.flashforge.errors import (
    FlashForgeAuthenticationError,
    FlashForgeCommandBusyError,
    FlashForgeResponseTooLargeError,
    FlashForgeTransportError,
)
from backend.app.services.flashforge.http import FlashForgeHttpClient
from backend.app.services.flashforge.normalize import parse_m661_file_list
from backend.app.services.flashforge.tcp import FlashForgeTcpClient


def _http_client(handler, *, max_response_bytes: int = 1024) -> FlashForgeHttpClient:
    transport = httpx.MockTransport(handler)
    client = httpx.Client(transport=transport)
    return FlashForgeHttpClient(
        host="127.0.0.1",
        provider="flashforge_ad5m",
        model="Adventurer 5M Pro",
        serial_number="FF-SN",
        check_code="private-check-code",
        client=client,
        max_response_bytes=max_response_bytes,
    )


def test_http_detail_posts_credentials_and_accepts_code_zero():
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"code": 0, "detail": {"state": "idle"}})

    with _http_client(handler) as client:
        result = client.detail()

    assert result["detail"]["state"] == "idle"
    assert requests[0].url.path == "/detail"
    assert json.loads(requests[0].content) == {
        "serialNumber": "FF-SN",
        "checkCode": "private-check-code",
    }


@pytest.mark.parametrize("code", [-2, 1, 200, False, "0"])
def test_http_invalid_code_is_rejected_without_echoing_response(code: int | str | bool):
    client = _http_client(lambda _: httpx.Response(200, json={"code": code, "message": "private-check-code"}))
    with client, pytest.raises(FlashForgeAuthenticationError if code == -2 else FlashForgeTransportError) as error:
        client.detail()
    assert "private-check-code" not in str(error.value)


def test_http_lan_mode_error_is_actionable_but_sanitized():
    client = _http_client(lambda _: httpx.Response(200, json={"code": 4, "message": "LAN mode error"}))
    with client, pytest.raises(FlashForgeAuthenticationError, match="LAN API is disabled"):
        client.detail()


def test_http_timeout_is_mapped_to_sanitized_transport_error():
    def handler(_: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("private-check-code")

    client = _http_client(handler)
    with client, pytest.raises(FlashForgeTransportError, match="timed out") as error:
        client.detail()
    assert "private-check-code" not in str(error.value)


def test_http_payload_cannot_override_credentials():
    client = _http_client(lambda _: httpx.Response(200, json={"code": 0}))
    with client, pytest.raises(ValueError, match="cannot override"):
        client.post_json("/detail", {"checkCode": "attacker-value"})


def test_http_requests_to_one_printer_are_serialized():
    state = {"active": 0, "maximum": 0}
    guard = threading.Lock()

    def handler(_: httpx.Request) -> httpx.Response:
        with guard:
            state["active"] += 1
            state["maximum"] = max(state["maximum"], state["active"])
        time.sleep(0.03)
        with guard:
            state["active"] -= 1
        return httpx.Response(200, json={"code": 0})

    client = _http_client(handler)
    with client, ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: client.detail(), range(2)))
    assert results == [{"code": 0}, {"code": 0}]
    assert state["maximum"] == 1


def test_print_gcode_does_not_allow_filename_override():
    client = _http_client(lambda _: httpx.Response(200, json={"code": 0}))
    with client, pytest.raises(ValueError, match="cannot override"):
        client.print_gcode("validated.gcode", fileName="../unchecked.gcode")


@pytest.mark.parametrize(
    ("response", "error"),
    [
        (httpx.Response(302, headers={"Location": "http://elsewhere.invalid/"}), FlashForgeTransportError),
        (httpx.Response(200, content=b"not-json"), FlashForgeTransportError),
        (httpx.Response(200, content=b"[]"), FlashForgeTransportError),
        (httpx.Response(200, content=b"x" * 64), FlashForgeResponseTooLargeError),
    ],
)
def test_http_rejects_redirect_malformed_shape_and_oversized_body(response: httpx.Response, error: type[Exception]):
    client = _http_client(lambda _: response, max_response_bytes=32)
    with client, pytest.raises(error):
        client.detail()


def test_upload_is_multipart_stream_with_print_now_disabled(tmp_path: Path):
    source = tmp_path / "cube.gcode"
    source.write_bytes(b"G28\n")
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["headers"] = dict(request.headers)
        captured["body"] = request.read()
        captured["url"] = str(request.url)
        return httpx.Response(200, json={"code": 0})

    client = _http_client(handler)
    with client:
        assert client.upload_gcode(source) == {"code": 0}
    headers = captured["headers"]
    assert captured["url"].endswith("/uploadGcode")
    assert headers["serialnumber"] == "FF-SN"
    assert headers["checkcode"] == "private-check-code"
    assert headers["filesize"] == "4"
    assert headers["printnow"] == "false"
    assert b'name="gcodeFile"; filename="cube.gcode"' in captured["body"]
    assert b"G28\n" in captured["body"]


def test_upload_accepts_creator5_material_station_headers(tmp_path: Path):
    source = tmp_path / "multi.gcode"
    source.write_bytes(b"G28\n")
    captured: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(request.headers)
        return httpx.Response(200, json={"code": 0})

    client = _http_client(handler)
    with client:
        client.upload_gcode(
            source,
            extra_headers={
                "useMatlStation": "true",
                "gcodeToolCnt": "3",
                "flowCalibration": "false",
                "timeLapseVideo": "false",
            },
        )

    assert captured["printnow"] == "false"
    assert captured["usematlstation"] == "true"
    assert captured["gcodetoolcnt"] == "3"
    assert captured["flowcalibration"] == "false"
    assert captured["timelapsevideo"] == "false"


def test_http_wire_roundtrip_to_loopback_server_for_json_and_multipart(tmp_path: Path):
    captured: list[tuple[str, dict[str, str], bytes]] = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            body = self.rfile.read(int(self.headers.get("Content-Length", "0")))
            captured.append((self.path, dict(self.headers.items()), body))
            response = b'{"code":0,"detail":{}}'
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(response)))
            self.end_headers()
            self.wfile.write(response)

        def log_message(self, *_args: Any) -> None:
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    source = tmp_path / "loopback.gcode"
    source.write_bytes(b"G28\n")
    client = FlashForgeHttpClient(
        host="127.0.0.1",
        http_port=server.server_port,
        provider="flashforge_ad5m",
        model="Adventurer 5M Pro",
        serial_number="FF-SN",
        check_code="local-check-code",
    )
    try:
        with client:
            assert client.detail()["code"] == 0
            assert client.upload_gcode(source)["code"] == 0
    finally:
        server.shutdown()
        server.server_close()
        server_thread.join(timeout=2.0)

    assert [request[0] for request in captured] == ["/detail", "/uploadGcode"]
    assert json.loads(captured[0][2]) == {"serialNumber": "FF-SN", "checkCode": "local-check-code"}
    upload_headers = {name.lower(): value for name, value in captured[1][1].items()}
    assert upload_headers["filesize"] == "4"
    assert upload_headers["printnow"] == "false"
    assert b'name="gcodeFile"; filename="loopback.gcode"' in captured[1][2]
    assert b"G28\n" in captured[1][2]


class _FakeSocket:
    def __init__(self, replies_by_command: dict[bytes, list[bytes | BaseException]]):
        self.replies_by_command = replies_by_command
        self.replies: list[bytes | BaseException] = []
        self.commands: list[bytes] = []
        self.options: list[tuple[int, int, int]] = []
        self.timeout: float | None = None
        self.closed = False

    def setsockopt(self, level: int, option: int, value: int) -> None:
        self.options.append((level, option, value))

    def settimeout(self, value: float) -> None:
        self.timeout = value

    def sendall(self, data: bytes) -> None:
        self.commands.append(data)
        self.replies = list(self.replies_by_command.get(data, []))

    def recv(self, _: int) -> bytes:
        if not self.replies:
            raise TimeoutError()
        reply = self.replies.pop(0)
        if isinstance(reply, BaseException):
            raise reply
        return reply

    def close(self) -> None:
        self.closed = True


def _tcp_client(fake_socket: _FakeSocket) -> FlashForgeTcpClient:
    return FlashForgeTcpClient(
        host="127.0.0.1",
        provider="flashforge_ad5m",
        model="Adventurer 5M Pro",
        settle_seconds=0.01,
        command_timeout=0.1,
        socket_factory=lambda *_args, **_kwargs: fake_socket,  # noqa: ARG005
    )


def test_tcp_file_listing_reads_chunks_and_releases_control_lock():
    fake_socket = _FakeSocket(
        {
            b"~M601 S1\n": [b"ok\n", TimeoutError()],
            b"~M661\n": [
                b"/data/cube one.gcode::1024\n",
                b"/data/cube-two.gx::2048\n",
                TimeoutError(),
            ],
        }
    )
    raw = _tcp_client(fake_socket).list_files_raw()

    assert "cube one.gcode" in raw
    assert "cube-two.gx" in raw
    assert fake_socket.commands == [b"~M601 S1\n", b"~M661\n", b"~M602\n"]
    assert fake_socket.options == [(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)]
    assert fake_socket.closed


def test_tcp_busy_response_still_releases_control_lock():
    fake_socket = _FakeSocket({b"~M601 S1\n": [b"Control busy\n"]})
    with pytest.raises(FlashForgeCommandBusyError):
        _tcp_client(fake_socket).list_files_raw()
    assert fake_socket.commands == [b"~M601 S1\n", b"~M602\n"]
    assert fake_socket.closed


def test_tcp_rejects_unconfirmed_acquire_and_releases_control_lock():
    fake_socket = _FakeSocket({b"~M601 S1\n": [b"Error: have been connected\n"]})
    with pytest.raises(FlashForgeCommandBusyError):
        _tcp_client(fake_socket).list_files_raw()
    assert fake_socket.commands == [b"~M601 S1\n", b"~M602\n"]


def test_tcp_rejects_unrecognized_acquire_response():
    fake_socket = _FakeSocket({b"~M601 S1\n": [b"printer says hello\n"]})
    with pytest.raises(FlashForgeTransportError, match="did not accept"):
        _tcp_client(fake_socket).list_files_raw()
    assert fake_socket.commands[-1] == b"~M602\n"


def test_tcp_rejects_creator5_before_opening_socket():
    opened = False

    def socket_factory(*_args, **_kwargs):
        nonlocal opened
        opened = True
        raise AssertionError("socket should not be opened")

    with pytest.raises(ValueError, match="does not support"):
        FlashForgeTcpClient(
            host="creator.local",
            provider="flashforge_creator5",
            model="Creator 5 Pro",
            socket_factory=socket_factory,
        )
    assert not opened


def test_tcp_releases_lock_after_transport_error():
    first = _FakeSocket({b"~M601 S1\n": [TimeoutError()]})
    first_client = _tcp_client(first)
    with pytest.raises(FlashForgeTransportError):
        first_client.list_files_raw()

    second = _FakeSocket(
        {
            b"~M601 S1\n": [b"ok\n", TimeoutError()],
            b"~M661\n": [b"files\n", TimeoutError()],
        }
    )
    assert _tcp_client(second).list_files_raw() == "files\n"
    assert second.commands[-1] == b"~M602\n"


def test_tcp_response_size_limit_releases_printer_control_lock():
    fake_socket = _FakeSocket(
        {
            b"~M601 S1\n": [b"ok\n", TimeoutError()],
            b"~M661\n": [b"x" * 32],
        }
    )
    client = _tcp_client(fake_socket)
    client.max_response_bytes = 16
    with pytest.raises(FlashForgeResponseTooLargeError):
        client.list_files_raw()
    assert fake_socket.commands[-1] == b"~M602\n"
    assert fake_socket.closed


def test_tcp_lock_contention_fails_without_opening_second_socket():
    first = _FakeSocket({})
    client = _tcp_client(first)
    client.lock_timeout = 0.01
    assert client._lock.acquire(blocking=False)
    try:
        with pytest.raises(FlashForgeCommandBusyError):
            client.list_files_raw()
        assert first.commands == []
    finally:
        client._lock.release()


@pytest.mark.asyncio
async def test_async_tcp_cancellation_releases_control_lock_and_closes_socket():
    m661_received = asyncio.Event()
    m602_received = asyncio.Event()
    commands: list[bytes] = []

    async def handle_client(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            while line := await asyncio.wait_for(reader.readline(), timeout=2.0):
                commands.append(line)
                if line == b"~M601 S1\n":
                    writer.write(b"Control Success\nok\n")
                    await writer.drain()
                elif line == b"~M661\n":
                    writer.write(b"/data/cancel.gcode::10\n")
                    await writer.drain()
                    m661_received.set()
                elif line == b"~M602\n":
                    m602_received.set()
                    return
        except (asyncio.TimeoutError, ConnectionError):
            return
        finally:
            writer.close()
            await writer.wait_closed()

    server = await asyncio.start_server(handle_client, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    client = FlashForgeTcpClient(
        host="127.0.0.1",
        provider="flashforge_ad5m",
        model="Adventurer 5M Pro",
        port=port,
        settle_seconds=0.5,
        command_timeout=2.0,
    )
    server_task = asyncio.create_task(client.list_files_raw_async())
    try:
        await asyncio.wait_for(m661_received.wait(), timeout=1.0)
        server_task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await server_task
        await asyncio.wait_for(m602_received.wait(), timeout=1.0)
        assert commands == [b"~M601 S1\n", b"~M661\n", b"~M602\n"]
    finally:
        server.close()
        await server.wait_closed()
        if not server_task.done():
            server_task.cancel()


@pytest.mark.asyncio
async def test_async_tcp_requests_for_one_endpoint_do_not_overlap():
    state = {"active": 0, "maximum": 0}
    guard = asyncio.Lock()

    async def handle_client(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            assert await reader.readline() == b"~M601 S1\n"
            async with guard:
                state["active"] += 1
                state["maximum"] = max(state["maximum"], state["active"])
            writer.write(b"Control Success\nok\n")
            await writer.drain()
            assert await reader.readline() == b"~M661\n"
            writer.write(b"/data/serial.gcode::10\n")
            await writer.drain()
            await reader.readline()
            async with guard:
                state["active"] -= 1
        finally:
            writer.close()
            await writer.wait_closed()

    server = await asyncio.start_server(handle_client, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    client = FlashForgeTcpClient(
        host="127.0.0.1",
        provider="flashforge_ad5m",
        model="Adventurer 5M Pro",
        port=port,
        settle_seconds=0.01,
        command_timeout=1.0,
    )
    try:
        results = await asyncio.gather(client.list_files_raw_async(), client.list_files_raw_async())
        assert results == ["/data/serial.gcode::10\n", "/data/serial.gcode::10\n"]
        assert state["maximum"] == 1
    finally:
        server.close()
        await server.wait_closed()


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (
            "ACK::/data/cube one.gcode::10\n::/data/模型.gx::20\nok\n",
            ["cube one.gcode", "模型.gx"],
        ),
        (
            "info_list.size: 2\n0:/user/legacy.gcode\n/data/legacy.gcode\nignored.txt\n",
            ["legacy.gcode"],
        ),
        (b"CMD M661 Received.\r\nok\r\n/data/part.3mf\0", ["part.3mf"]),
    ],
)
def test_parse_m661_file_list_handles_modern_legacy_unicode_and_duplicates(raw, expected):
    assert parse_m661_file_list(raw) == expected
