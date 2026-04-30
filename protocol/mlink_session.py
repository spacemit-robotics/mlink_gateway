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

from __future__ import annotations

import threading
from typing import Any, Dict, List

from mlink.gateway.gateway.device_registry import DeviceRegistry
from mlink.gateway.gateway.service_descriptor import ServiceDescriptor
from mlink.gateway.mcp.mcp_server import GatewayMcpServer
from mlink.gateway.protocol.jsonrpc_mcp_client import MlinkMcpJsonRpcClient
from mlink.gateway.transport.base import TransportBase
from mlink.gateway.utils.logger import get_logger


logger = get_logger("gateway.protocol.mlink_session")


class MlinkSessionHandler:
    """
    会话层：负责在一条底层 Transport 连接上跑 mlink 的 MCP 协议：
      - initialize
      - tools/list
      - tools/call（通过 GatewayMcpServer 间接转发）

    传输层（TCP/Unix/...）只需把新的 TransportBase 传进来即可。
    """

    def __init__(
        self,
        devices: DeviceRegistry,
        mcp_server: GatewayMcpServer,
    ) -> None:
        self._devices = devices
        self._mcp_server = mcp_server

    @staticmethod
    def _build_service_descriptors(
        device_id: str, tools_result: Dict[str, Any]
    ) -> List[ServiceDescriptor]:
        """
        根据 mlink 的 tools/list 返回结果，构造 ServiceDescriptor 列表。
        mlink 的 JSON 结构大致为：
          {
            "tools": [
              {
                "name": "...",
                "description": "...",
                "inputSchema": {...}
              },
              ...
            ],
            "nextCursor": "..." | null
          }
        """
        services: List[ServiceDescriptor] = []
        for t in tools_result.get("tools") or []:
            name = t.get("name")
            if not isinstance(name, str):
                continue
            description = t.get("description") or ""
            input_schema = t.get("inputSchema") or {"type": "object", "properties": {}}
            full_name = f"{device_id}.{name}"
            sd = ServiceDescriptor(
                full_name=full_name,
                device_id=device_id,
                tool_name=name,
                description=description,
                input_schema=input_schema,
            )
            services.append(sd)
        return services

    def handle_new_connection(self, conn: TransportBase) -> None:
        """
        每当有一个新的 mlink 连接进来时调用，完成：
          - 逻辑设备 ID 解析（来自 initialize.serverInfo.name）
          - 注册 / 替换 DeviceSession
          - tools/list 同步工具并注册到 GatewayMcpServer
        """

        rpc_client = MlinkMcpJsonRpcClient(
            send_text=lambda s: conn.send_bytes((s + "\n").encode("utf-8"))
        )

        # 逻辑设备 ID（来自 mlink initialize.serverInfo.name），在初始化完成后填充
        device_id: str | None = None

        def on_bytes(data: bytes) -> None:
            text = data.decode("utf-8", errors="ignore").strip()
            if text:
                rpc_client.handle_text(text)

        def on_error(exc: Exception) -> None:
            logger.error("Device connection error: %s", exc)
            # 如果已经完成初始化并获得 device_id，则清理设备及其工具映射
            if device_id is not None:
                self._devices.remove_device(device_id)
                self._mcp_server.unregister_device(device_id)

        # 覆盖底层 Transport 的回调
        conn._on_bytes = on_bytes  # type: ignore[attr-defined]
        conn._on_error = on_error  # type: ignore[attr-defined]

        def _sync_device_tools() -> None:
            nonlocal device_id
            try:
                # 1) 初始化 MCP 会话，读取 serverInfo.name 作为逻辑设备 ID
                init_resp = rpc_client.initialize()
                init_result = init_resp.get("result") or {}
                server_info = init_result.get("serverInfo") or {}
                logical_id = server_info.get("name")
                if not isinstance(logical_id, str) or not logical_id:
                    logical_id = self._devices.next_device_id()

                device_id = logical_id
                logger.info("Device %s initialize -> %s", device_id, init_result)

                # 2) 注册/替换 DeviceSession（处理重连场景）
                session = self._devices.register_or_replace(device_id, conn, rpc_client)

                # 3) tools/list 分页拉取所有工具
                cursor: str | None = None
                all_tools: List[Dict[str, Any]] = []
                while True:
                    resp = rpc_client.tools_list(cursor=cursor, with_user_tools=False)
                    result = resp.get("result") or {}
                    all_tools.extend(result.get("tools") or [])
                    cursor = result.get("nextCursor")
                    if not cursor:
                        break

                session.tools = all_tools

                # 4) 将设备工具注册到 GatewayMcpServer（ToolRegistry + FastMCP）
                for sd in self._build_service_descriptors(device_id, {"tools": all_tools}):
                    self._mcp_server.register_service(sd)
                    logger.info("Registered tool %s from device %s", sd.full_name, device_id)
            except Exception as exc:  # pragma: no cover
                # 同步失败视为整个连接初始化失败，清理设备及工具
                did = device_id or "<unknown>"
                logger.error("Failed to sync tools for device %s: %s", did, exc)
                if device_id is not None:
                    self._devices.remove_device(device_id)
                    self._mcp_server.unregister_device(device_id)

        # 同步工具放到后台线程，避免阻塞 accept
        threading.Thread(target=_sync_device_tools, daemon=True).start()


__all__ = ["MlinkSessionHandler"]



