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
Gateway 端到端测试脚本（End-to-End Test）

目标：
  - 模拟一个 mlink 设备通过 MCP JSON-RPC 协议连接到 Gateway：
      * 使用 MlinkSessionHandler + MlinkMcpJsonRpcClient + 自定义 FakeMlinkTransport；
      * 设备侧实现 initialize / tools/list / tools/call 的最小逻辑；
  - 等待设备完成初始化与 tools/list，同步到 DeviceRegistry / ToolRegistry；
  - 最终通过 ToolRouter.call_tool 调用设备工具，验证整条链路是否可用。

用法（需先在 SDK 根目录执行 ``pip install -e components/agent_tools/mlink_gateway``）：

    cd <sdk-root>
    python components/agent_tools/mlink_gateway/tests/gateway_e2e_test.py

所有断言通过时，会打印 “E2E TEST PASSED.”。
"""

from __future__ import annotations

import asyncio
import json
import time

from mlink.gateway.transport.base import TransportBase
from mlink.gateway.gateway.device_registry import DeviceRegistry
from mlink.gateway.gateway.tool_registry import ToolRegistry
from mlink.gateway.gateway.tool_router import ToolRouter
from mlink.gateway.gateway.tools_snapshot import ToolsSnapshotExporter
from mlink.gateway.mcp.mcp_server import GatewayMcpServer
from mlink.gateway.protocol.mlink_session import MlinkSessionHandler


class FakeMlinkTransport(TransportBase):
    """
    简单的内存中“假 mlink 设备”：
      - Gateway 通过 send_bytes 发送 JSON-RPC 请求；
      - 这里解析请求并立即构造响应，再通过 _handle_bytes 回传给 Gateway。
    """

    def __init__(self) -> None:
        super().__init__(on_bytes=lambda b: None)
        self.closed = False

    def send_bytes(self, data: bytes) -> None:
        if self.closed:
            return
        text = data.decode("utf-8", errors="ignore").strip()
        if not text:
            return

        try:
            req = json.loads(text)
        except json.JSONDecodeError:
            return

        method = req.get("method")
        req_id = req.get("id")

        if method == "initialize":
            resp = {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "serverInfo": {
                        "name": "e2e-device-1",
                        "version": "1.0.0",
                        "description": "Fake mlink device for E2E test",
                    }
                },
            }
        elif method == "tools/list":
            # 返回一个简单的 echo 工具
            resp = {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "tools": [
                        {
                            "name": "echo",
                            "description": "Echo text from fake device",
                            "inputSchema": {
                                "type": "object",
                                "properties": {
                                    "text": {"type": "string"},
                                },
                                "required": ["text"],
                            },
                        }
                    ],
                    "nextCursor": None,
                },
            }
        elif method == "tools/call":
            params = req.get("params") or {}
            name = params.get("name")
            args = params.get("arguments") or {}

            if name == "echo":
                resp = {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {"output": args.get("text")},
                }
            else:
                resp = {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "error": {
                        "code": -1,
                        "message": f"unknown tool {name}",
                    },
                }
        else:
            # 未知方法，简单忽略
            return

        # 把响应回给 Gateway 这边的 MlinkMcpJsonRpcClient
        resp_text = json.dumps(resp, ensure_ascii=False)
        self._handle_bytes((resp_text + "\n").encode("utf-8"))

    def close(self) -> None:
        self.closed = True


async def main() -> None:
    print("Running gateway E2E test...")

    loop = asyncio.get_running_loop()

    # 1. 构建 Gateway 侧核心对象
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
    session_handler = MlinkSessionHandler(devices=devices, mcp_server=mcp_server)

    # 2. 使用 FakeMlinkTransport 模拟一个新连接
    conn = FakeMlinkTransport()
    session_handler.handle_new_connection(conn)

    # 3. 等待后台线程完成 initialize + tools/list，同步工具到 Gateway
    for _ in range(50):  # 最长等待约 5 秒
        if tools.all_services():
            break
        time.sleep(0.1)
    else:
        raise AssertionError("Timed out waiting for tools to be registered from fake device")

    all_services = tools.all_services()
    assert len(all_services) >= 1
    sd = next(sd for sd in all_services if sd.tool_name == "echo")
    assert sd.device_id == "e2e-device-1"

    print(f" - tools synchronized from device: {sd.full_name}")

    # 4. 通过 ToolRouter.call_tool 触发一次真正的 tools/call
    result = router.call_tool(sd.full_name, {"text": "hello world", "unused": None})
    assert result == {"output": "hello world"}

    print(" - tool invocation via ToolRouter and fake device: OK")

    # 5. 模拟底层连接出错，触发 MlinkSessionHandler.on_error 清理逻辑
    # 直接调用 conn._on_error，相当于 TransportBase._handle_error 里触发的场景。
    conn._on_error(Exception("simulated device error"))  # type: ignore[attr-defined]

    # 等待清理完成
    time.sleep(0.1)

    # 设备与其工具应被移除：
    assert devices.get("e2e-device-1") is None
    remaining = [s for s in tools.all_services() if s.device_id == "e2e-device-1"]
    assert not remaining

    print(" - device error cleanup (remove_device + unregister_device): OK")

    print("E2E TEST PASSED.")


if __name__ == "__main__":
    asyncio.run(main())


