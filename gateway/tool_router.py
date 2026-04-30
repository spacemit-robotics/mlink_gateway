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

from typing import Any, Dict

from mlink.gateway.utils.logger import get_logger
from .device_registry import DeviceRegistry
from .tool_registry import ToolRegistry


logger = get_logger("gateway.tool_router")


class ToolRouter:
    """
    工具调用路由：
      - 根据 MCP 工具名找到 ServiceDescriptor
      - 选择设备（目前使用 ServiceDescriptor.device_id）
      - 通过对应设备的 MlinkMcpJsonRpcClient 调用 tools/call
    """

    def __init__(self, devices: DeviceRegistry, tools: ToolRegistry) -> None:
        self._devices = devices
        self._tools = tools

    def _normalize_arguments(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """
        规范化从 FastMCP 收到的工具参数：
          - FastMCP/客户端会将 JSON-RPC params.arguments 作为一个 dict 传入；
          - 某些调用栈可能会在其中再套一层 "arguments" 字段；
          - mlink 侧的 tools/call 期望拿到的是真正的业务参数：
                {"volume": 50}
            而不是：
                {"arguments": {"volume": 50}} 或更深层嵌套。
        """
        value = arguments or {}
        # 反复剥掉只有一个键且名为 "arguments" 的外层包装，直到不是这种结构为止。
        while (
            isinstance(value, dict)
            and len(value) == 1
            and "arguments" in value
            and isinstance(value["arguments"], dict)
        ):
            value = value["arguments"]

        if isinstance(value, dict):
            value = {k: v for k, v in value.items() if v is not None}
        return value

    def call_tool(self, full_tool_name: str, arguments: Dict[str, Any]) -> Any:
        sd = self._tools.get(full_tool_name)
        if not sd:
            raise RuntimeError(f"Unknown tool: {full_tool_name}")

        device = self._devices.get(sd.device_id)
        if not device:
            raise RuntimeError(f"Device '{sd.device_id}' is not connected")

        # 统一规范化参数，确保传给 mlink 的是展开后的业务参数。
        norm_args = self._normalize_arguments(arguments)

        logger.info(
            "Calling tool %s on device %s with args=%s",
            sd.tool_name,
            sd.device_id,
            norm_args,
        )
        resp = device.rpc_client.tools_call(sd.tool_name, norm_args)
        if "error" in resp:
            raise RuntimeError(f"Device tool error: {resp['error']}")
        return resp.get("result")


__all__ = ["ToolRouter"]


