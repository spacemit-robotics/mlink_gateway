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

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any

from mlink.gateway.protocol.jsonrpc_mcp_client import MlinkMcpJsonRpcClient
from mlink.gateway.transport.base import TransportBase


@dataclass
class DeviceSession:
    device_id: str
    transport: TransportBase
    rpc_client: MlinkMcpJsonRpcClient
    tools: List[Dict[str, Any]] = field(default_factory=list)


class DeviceRegistry:
    """
    管理所有连接上的设备（每个 mlink 连接一个 DeviceSession）。
    """

    def __init__(self) -> None:
        self._devices: Dict[str, DeviceSession] = {}
        self._counter = 0

    def add_device(self, session: DeviceSession) -> None:
        """
        简单添加一个已构造好的 DeviceSession。
        新代码推荐使用 register_or_replace 以便处理重连场景。
        """
        self._devices[session.device_id] = session

    def register_or_replace(
        self,
        device_id: str,
        transport: TransportBase,
        rpc_client: MlinkMcpJsonRpcClient,
    ) -> DeviceSession:
        """
        使用指定的 device_id 注册设备：
          - 如果该 ID 已存在，则关闭旧连接并用新连接替换（用于断线重连）。
          - 返回新的 DeviceSession。
        """
        sess = self._devices.pop(device_id, None)
        if sess is not None:
            sess.transport.close()

        session = DeviceSession(device_id=device_id, transport=transport, rpc_client=rpc_client)
        self._devices[device_id] = session
        return session

    def remove_device(self, device_id: str) -> None:
        sess = self._devices.pop(device_id, None)
        if sess:
            sess.transport.close()

    def list_devices(self) -> List[str]:
        return list(self._devices.keys())

    def get(self, device_id: str) -> Optional[DeviceSession]:
        return self._devices.get(device_id)

    def next_device_id(self) -> str:
        self._counter += 1
        return f"device{self._counter}"


__all__ = ["DeviceRegistry", "DeviceSession"]


