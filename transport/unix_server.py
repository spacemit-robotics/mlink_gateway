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

import os
import socket
import threading
from typing import Callable

from .base import TransportBase
from mlink.gateway.utils.logger import get_logger


logger = get_logger("gateway.transport.unix")


class UnixConnection(TransportBase):
    """
    Wrap a single accepted Unix domain socket connection as a TransportBase.
    """

    def __init__(self, conn: socket.socket, path: str, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._conn = conn
        self._path = path
        self._thread = threading.Thread(target=self._reader_loop, daemon=True)
        self._thread.start()
        logger.info("UNIX connection on %s established", path)

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
            logger.info("UNIX connection on %s closed", self._path)

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


NewConnectionCallback = Callable[[UnixConnection], None]


class UnixServer:
    """
    Simple Unix domain socket server used for local mlink devices.

    mlink 的 C 端在使用 Unix 域传输时会主动连接到固定路径（默认 /tmp/mlink.sock），
    这里我们监听该路径并为每个连接创建一个 UnixConnection。
    """

    def __init__(self, path: str, on_connection: NewConnectionCallback) -> None:
        self._path = path
        self._on_connection = on_connection
        self._sock: socket.socket | None = None
        self._accept_thread: threading.Thread | None = None
        self._stopped = threading.Event()

    def start(self) -> None:
        if self._sock is not None:
            return

        # 如果之前遗留了同名 socket 文件，先删除
        try:
            if os.path.exists(self._path) and not os.path.isfile(self._path):
                os.unlink(self._path)
        except OSError:
            # 最多只影响绑定失败，在后面日志中会体现
            pass

        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.bind(self._path)
        sock.listen()
        self._sock = sock
        logger.info("UNIX server listening on %s", self._path)

        self._accept_thread = threading.Thread(target=self._accept_loop, daemon=True)
        self._accept_thread.start()

    def _accept_loop(self) -> None:
        assert self._sock is not None
        while not self._stopped.is_set():
            try:
                conn, _ = self._sock.accept()
            except OSError:
                break
            dummy = UnixConnection(conn, self._path, on_bytes=lambda b: None)
            self._on_connection(dummy)

    def close(self) -> None:
        self._stopped.set()
        if self._sock is not None:
            try:
                self._sock.close()
            finally:
                self._sock = None
        logger.info("UNIX server stopped")


__all__ = ["UnixServer", "UnixConnection"]



