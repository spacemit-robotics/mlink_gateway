# Copyright (C) 2026 SpacemiT (Hangzhou) Technology Co. Ltd.
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import asyncio
import json
import time

from mlink.gateway.gateway.device_registry import DeviceRegistry
from mlink.gateway.gateway.tool_registry import ToolRegistry
from mlink.gateway.gateway.tool_router import ToolRouter
from mlink.gateway.gateway.tools_snapshot import ToolsSnapshotExporter
from mlink.gateway.mcp.mcp_server import GatewayMcpServer
from mlink.gateway.protocol.mlink_session import MlinkSessionHandler
from mlink.gateway.transport.base import TransportBase


class FakeMlinkTransport(TransportBase):
    def __init__(self, device_name: str = "e2e-device-1") -> None:
        super().__init__(on_bytes=lambda b: None)
        self.closed = False
        self.device_name = device_name

    def send_bytes(self, data: bytes) -> None:
        if self.closed:
            return
        req = json.loads(data.decode("utf-8", errors="ignore").strip())
        method = req.get("method")
        req_id = req.get("id")

        if method == "initialize":
            result = {
                "serverInfo": {
                    "name": self.device_name,
                    "version": "1.0.0",
                    "description": "Fake mlink device for gateway tests",
                }
            }
            resp = {"jsonrpc": "2.0", "id": req_id, "result": result}
        elif method == "tools/list":
            params = req.get("params") or {}
            cursor = params.get("cursor")
            if cursor is None:
                tools = [
                    {
                        "name": "echo",
                        "description": "Echo text from fake device",
                        "inputSchema": {
                            "type": "object",
                            "properties": {"text": {"type": "string"}},
                            "required": ["text"],
                        },
                    }
                ]
                resp = {"jsonrpc": "2.0", "id": req_id, "result": {"tools": tools, "nextCursor": "page-2"}}
            elif cursor == "page-2":
                tools = [
                    {
                        "name": "add",
                        "description": "Add two integers",
                        "inputSchema": {
                            "type": "object",
                            "properties": {"a": {"type": "integer"}, "b": {"type": "integer"}},
                            "required": ["a", "b"],
                        },
                    }
                ]
                resp = {"jsonrpc": "2.0", "id": req_id, "result": {"tools": tools, "nextCursor": None}}
            else:
                resp = {"jsonrpc": "2.0", "id": req_id, "result": {"tools": [], "nextCursor": None}}
        elif method == "tools/call":
            params = req.get("params") or {}
            name = params.get("name")
            args = params.get("arguments") or {}
            if name == "echo":
                resp = {"jsonrpc": "2.0", "id": req_id, "result": {"output": args.get("text")}}
            elif name == "add":
                resp = {"jsonrpc": "2.0", "id": req_id, "result": int(args.get("a", 0)) + int(args.get("b", 0))}
            else:
                resp = {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "error": {"code": -1, "message": f"unknown tool {name}"},
                }
        else:
            return

        self._handle_bytes((json.dumps(resp, ensure_ascii=False) + "\n").encode("utf-8"))

    def close(self) -> None:
        self.closed = True


def wait_for_services(tools: ToolRegistry, expected: set[str], timeout_s: float = 5.0) -> None:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        names = {sd.tool_name for sd in tools.all_services()}
        if expected.issubset(names):
            return
        time.sleep(0.1)
    raise AssertionError(f"Timed out waiting for services {sorted(expected)}")


async def main() -> None:
    loop = asyncio.get_running_loop()
    devices = DeviceRegistry()
    tools = ToolRegistry()
    router = ToolRouter(devices=devices, tools=tools)
    snapshot_exporter = ToolsSnapshotExporter(devices=devices, tools=tools, loop=loop, config={"enabled": False})
    mcp_server = GatewayMcpServer(
        devices=devices,
        tool_registry=tools,
        tool_router=router,
        loop=loop,
        snapshot_exporter=snapshot_exporter,
    )
    session_handler = MlinkSessionHandler(devices=devices, mcp_server=mcp_server)

    conn = FakeMlinkTransport()
    session_handler.handle_new_connection(conn)
    wait_for_services(tools, {"echo", "add"})

    services = {sd.tool_name: sd for sd in tools.all_services()}
    assert services["echo"].device_id == "e2e-device-1"
    assert services["add"].device_id == "e2e-device-1"

    assert router.call_tool(services["echo"].full_name, {"text": "hello world", "unused": None}) == {
        "output": "hello world"
    }
    assert router.call_tool(services["add"].full_name, {"a": 1, "b": 2, "unused": None}) == 3

    conn._on_error(Exception("simulated device error"))  # type: ignore[attr-defined]
    time.sleep(0.1)

    assert devices.get("e2e-device-1") is None
    assert not [sd for sd in tools.all_services() if sd.device_id == "e2e-device-1"]
    print("SESSION FAKE DEVICE TESTS PASSED.")


if __name__ == "__main__":
    asyncio.run(main())
