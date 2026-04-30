# Copyright (C) 2026 SpacemiT (Hangzhou) Technology Co. Ltd.
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#
# Author: laumy <mingyuan.liu@spacemit.com>

"""
Gateway 集成测试脚本（Integration Test）。

目标：
  - 把 DeviceRegistry / ToolRegistry / ToolRouter / GatewayMcpServer / ToolsSnapshotExporter
    串在一起跑一遍，验证：
      * tools/list 结果经由 MlinkSessionHandler._build_service_descriptors 转为 ServiceDescriptor；
      * GatewayMcpServer.register_service 能正确注册到 ToolRegistry；
      * ToolsSnapshotExporter 能基于 ToolRegistry 构建快照；
      * ToolRouter.call_tool 能通过 DeviceRegistry 找到设备并调用其 rpc_client.tools_call。

用法（需先在 SDK 根目录执行 ``pip install -e components/agent_tools/mlink_gateway``）：

    cd <sdk-root>
    python components/agent_tools/mlink_gateway/tests/gateway_integration_test.py

所有断言通过时，会打印 “INTEGRATION TESTS PASSED.”。
"""

from __future__ import annotations

import asyncio

from mlink.gateway.gateway.device_registry import DeviceRegistry
from mlink.gateway.gateway.tool_registry import ToolRegistry
from mlink.gateway.gateway.tool_router import ToolRouter
from mlink.gateway.gateway.service_descriptor import ServiceDescriptor
from mlink.gateway.gateway.tools_snapshot import ToolsSnapshotExporter
from mlink.gateway.transport.manager import TransportManager, build_transport_configs
from mlink.gateway.mcp.mcp_server import GatewayMcpServer
from mlink.gateway.protocol.mlink_session import MlinkSessionHandler


class DummyTransport:
    def __init__(self) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True


class DummyRpcClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    def tools_call(self, name: str, args: dict) -> dict:
        self.calls.append((name, args))
        if name == "echo":
            return {"result": {"value": args.get("text")}}
        if name == "add":
            return {"result": args.get("a", 0) + args.get("b", 0)}
        return {"error": f"unknown tool {name}"}


async def main() -> None:
    print("Running gateway integration tests...")

    loop = asyncio.get_running_loop()

    # 1. 组合核心组件
    devices = DeviceRegistry()
    tools = ToolRegistry()
    router = ToolRouter(devices=devices, tools=tools)
    snapshot_exporter = ToolsSnapshotExporter(
        devices=devices,
        tools=tools,
        loop=loop,
        config={"enabled": False, "path": None},
    )
    mcp_server = GatewayMcpServer(
        devices=devices,
        tool_registry=tools,
        tool_router=router,
        loop=loop,
        snapshot_exporter=snapshot_exporter,
    )

    # 2. 模拟 mlink 的 tools/list 返回结果，通过 MlinkSessionHandler 生成 ServiceDescriptor
    tools_result = {
        "tools": [
            {
                "name": "echo",
                "description": "Echo text",
                "inputSchema": {
                    "type": "object",
                    "properties": {"text": {"type": "string"}},
                    "required": ["text"],
                },
            },
            {
                "name": "add",
                "description": "Add two integers",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "a": {"type": "integer"},
                        "b": {"type": "integer"},
                    },
                    "required": ["a", "b"],
                },
            },
        ],
        "nextCursor": None,
    }

    services = MlinkSessionHandler._build_service_descriptors("dev-integ", tools_result)
    assert len(services) == 2

    # 3. 通过 GatewayMcpServer 注册工具（内部会更新 ToolRegistry、FastMCP、ToolsSnapshotExporter）
    for sd in services:
        assert isinstance(sd, ServiceDescriptor)
        mcp_server.register_service(sd)

    all_services = tools.all_services()
    assert len(all_services) == 2

    # 4. 使用 ToolsSnapshotExporter 构建一次快照，检查内容
    snapshot = snapshot_exporter._build_snapshot()  # type: ignore[attr-defined]
    assert snapshot.get("tool_count") == 2
    names = {t["full_name"] for t in snapshot.get("tools", [])}
    assert "dev-integ.echo" in names
    assert "dev-integ.add" in names

    print(" - tool registry & snapshot integration: OK")

    # 4.1 测试 ToolsSnapshotExporter 的 mark_dirty + 写文件逻辑（使用临时文件）
    import tempfile
    import json
    import os

    with tempfile.TemporaryDirectory() as tmpdir:
        path = os.path.join(tmpdir, "tools_snapshot.json")
        snapshot_exporter_file = ToolsSnapshotExporter(
            devices=devices,
            tools=tools,
            loop=loop,
            config={"enabled": True, "path": path, "debounce_ms": 50},
        )
        snapshot_exporter_file.mark_dirty(reason="integration_test")
        # 等待抖动窗口执行完成
        await asyncio.sleep(0.2)
        assert os.path.exists(path)
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        assert data.get("tool_count") == 5
        names = {tool["full_name"] for tool in data.get("tools", [])}
        assert "gateway.ping" in names
        assert "gateway.status" in names
        assert "gateway.list_devices" in names

    print(" - tools snapshot exporter debounce & file write: OK")

    # 5. 在 DeviceRegistry 中注册一个假设备会话，让 ToolRouter 能真正调用到 DummyRpcClient
    transport = DummyTransport()
    rpc_client = DummyRpcClient()
    devices.register_or_replace("dev-integ", transport, rpc_client)

    # 找到 echo / add 对应的 ServiceDescriptor
    echo_sd = next(sd for sd in all_services if sd.tool_name == "echo")
    add_sd = next(sd for sd in all_services if sd.tool_name == "add")

    # 6. 通过 ToolRouter.call_tool 走完整调用链
    echo_result = router.call_tool(echo_sd.full_name, {"text": "hello", "unused": None})
    assert echo_result == {"value": "hello"}

    add_result = router.call_tool(add_sd.full_name, {"a": 1, "b": 2, "extra": None})
    assert add_result == 3

    # DummyRpcClient 至少被调用两次
    assert len(rpc_client.calls) >= 2

    print(" - tool routing via DeviceRegistry & GatewayMcpServer: OK")

    # 7. 测试 TransportManager + build_transport_configs 基本行为
    devices_cfg = {
        "transports": [
            {"kind": "tcp", "host": "127.0.0.1", "port": 0},
            {"kind": "unix", "path": "/tmp/mlink_test.sock"},
            {"kind": "unknown"},
        ]
    }
    configs = build_transport_configs(devices_cfg)
    kinds = {c.kind for c in configs}
    assert "tcp" in kinds and "unix" in kinds

    # 使用这些配置启动 TransportManager，然后关闭，确认不会抛异常
    def on_conn(_conn):
        # 本测试不需要实际数据，只验证启动/关闭是否正常。
        pass

    tm = TransportManager(configs=configs, on_connection=on_conn)
    tm.start()
    tm.close()
    print(" - transport manager build/config/start/close: OK")

    print("INTEGRATION TESTS PASSED.")


if __name__ == "__main__":
    asyncio.run(main())


