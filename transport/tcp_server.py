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

import socket
import threading
from typing import Callable, Tuple

from .base import TransportBase
from mlink.gateway.utils.logger import get_logger


logger = get_logger("gateway.transport.tcp")


class TcpConnection(TransportBase):
    """
    Wrap a single accepted TCP connection as a TransportBase.
    """

    def __init__(self, conn: socket.socket, addr: Tuple[str, int], *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._conn = conn
        self._addr = addr
        self._thread = threading.Thread(target=self._reader_loop, daemon=True)
        self._thread.start()
        logger.info("TCP connection from %s:%d established", addr[0], addr[1])

    def _reader_loop(self) -> None:
        try:
            while not self._closed.is_set():
                data = self._conn.recv(4096)
                if not data:
                    break
                self._handle_bytes(data)
        except Exception as exc:  # pragma: no cover
            self._handle_error(exc)
        finally:
            self.close()
            logger.info("TCP connection from %s:%d closed", self._addr[0], self._addr[1])

    def send_bytes(self, data: bytes) -> None:
        try:
            self._conn.sendall(data)
        except Exception as exc:
            self._handle_error(exc)

    def close(self) -> None:
        if self._closed.is_set():
            return
        self._closed.set()
        try:
            self._conn.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        self._conn.close()


NewConnectionCallback = Callable[[TcpConnection], None]


class TcpServer:
    """
    Simple multi-connection TCP server used for mlink devices.

    mlink 的 C 端是 TCP 客户端，会根据环境变量 MLINK_TCP_HOST/PORT 主动连上来，
    这里我们只需要监听并接受连接，每个连接对应一个设备会话。
    """

    def __init__(
        self,
        host: str,
        port: int,
        on_connection: NewConnectionCallback,
    ) -> None:
        self._host = host
        self._port = port
        self._on_connection = on_connection
        self._sock: socket.socket | None = None
        self._accept_thread: threading.Thread | None = None
        self._stopped = threading.Event()

    def start(self) -> None:
        if self._sock is not None:
            return
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind((self._host, self._port))
        sock.listen()
        self._sock = sock
        logger.info("TCP server listening on %s:%d", self._host, self._port)

        self._accept_thread = threading.Thread(target=self._accept_loop, daemon=True)
        self._accept_thread.start()

    def _accept_loop(self) -> None:
        assert self._sock is not None
        while not self._stopped.is_set():
            try:
                conn, addr = self._sock.accept()
            except OSError:
                break
            # on_bytes/error will be provided by gateway_layer when wrapping connection
            # so here we use temporary lambdas; real handlers will be set in DeviceManager.
            dummy = TcpConnection(conn, addr, on_bytes=lambda b: None)
            self._on_connection(dummy)

    def close(self) -> None:
        self._stopped.set()
        if self._sock is not None:
            try:
                self._sock.close()
            finally:
                self._sock = None
        logger.info("TCP server stopped")


__all__ = ["TcpServer", "TcpConnection"]


