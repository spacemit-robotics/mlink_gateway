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

from dataclasses import dataclass
from typing import Callable, List, Optional

from .base import TransportBase
from .tcp_server import TcpServer
from .unix_server import UnixServer
from mlink.gateway.utils.logger import get_logger


logger = get_logger("gateway.transport.manager")

NewConnCallback = Callable[[TransportBase], None]


@dataclass
class TransportConfig:
    kind: str  # "tcp" / "unix" / 以后 "mqtt" 等
    host: Optional[str] = None
    port: Optional[int] = None
    path: Optional[str] = None


class TransportManager:
    """
    统一管理多个传输 Server（TCP / Unix / ...）。

    通过配置传入要监听的端点，每种端点接受到连接后都会回调同一个
    on_connection(TransportBase)，由上层协议层统一处理。
    """

    def __init__(self, configs: List[TransportConfig], on_connection: NewConnCallback) -> None:
        self._configs = configs
        self._on_connection = on_connection
        self._servers: List[object] = []

    def start(self) -> None:
        for cfg in self._configs:
            if cfg.kind == "tcp":
                host = cfg.host or "0.0.0.0"
                port = cfg.port or 8080
                server = TcpServer(
                    host=host,
                    port=port,
                    on_connection=lambda conn, _host=host, _port=port: self._on_connection(conn),
                )
                server.start()
                self._servers.append(server)
                logger.info("TCP transport listening on %s:%d", host, port)
            elif cfg.kind == "unix":
                path = cfg.path or "/tmp/mlink.sock"
                server = UnixServer(
                    path=path,
                    on_connection=lambda conn, _path=path: self._on_connection(conn),
                )
                server.start()
                self._servers.append(server)
                logger.info("UNIX transport listening on %s", path)
            else:
                logger.warning("Unknown transport kind '%s', ignored", cfg.kind)

    def close(self) -> None:
        for s in self._servers:
            close = getattr(s, "close", None)
            if callable(close):
                try:
                    close()
                except Exception:  # pragma: no cover
                    pass


def build_transport_configs(devices_cfg: dict) -> List[TransportConfig]:
    """
    从配置构造 TransportConfig 列表。

    - 如果 devices.transports 存在，则优先使用：
        devices:
          transports:
            - kind: tcp
              host: "0.0.0.0"
              port: 8080
            - kind: unix
              path: "/tmp/mlink.sock"

    - 否则保留向后兼容行为：从 tcp_listen_host / tcp_listen_port / unix_listen_path
      构造一组 TCP + Unix 配置。
    """
    configs: List[TransportConfig] = []

    transports = devices_cfg.get("transports")
    if isinstance(transports, list) and transports:
        for t in transports:
            if not isinstance(t, dict):
                continue
            kind = t.get("kind")
            if not isinstance(kind, str):
                continue
            cfg = TransportConfig(
                kind=kind,
                host=t.get("host"),
                port=int(t["port"]) if "port" in t else None,
                path=t.get("path"),
            )
            configs.append(cfg)
        return configs

    # 兼容旧配置：单个 TCP + 单个 Unix
    host = devices_cfg.get("tcp_listen_host", "0.0.0.0")
    port = int(devices_cfg.get("tcp_listen_port", 8080))
    unix_path = devices_cfg.get("unix_listen_path", "/tmp/mlink.sock")

    configs.append(TransportConfig(kind="tcp", host=host, port=port))
    configs.append(TransportConfig(kind="unix", path=unix_path))
    return configs


__all__ = ["TransportConfig", "TransportManager", "build_transport_configs"]



