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

import abc
import threading
from typing import Callable, Optional


BytesCallback = Callable[[bytes], None]
ErrorCallback = Callable[[Exception], None]


class TransportBase(abc.ABC):
    """
    Abstract base class for a single device transport connection.

    One instance corresponds to one logical device connection (e.g. one TCP
    socket). Higher layers do not care whether it is TCP/UART/UDP/WS.
    """

    def __init__(
        self,
        on_bytes: BytesCallback,
        on_error: Optional[ErrorCallback] = None,
    ) -> None:
        self._on_bytes = on_bytes
        self._on_error = on_error
        self._closed = threading.Event()

    @abc.abstractmethod
    def send_bytes(self, data: bytes) -> None:
        """Send raw bytes."""

    @abc.abstractmethod
    def close(self) -> None:
        """Close the connection and release resources."""

    def _handle_bytes(self, data: bytes) -> None:
        if not data:
            return
        try:
            self._on_bytes(data)
        except Exception as exc:  # pragma: no cover
            if self._on_error:
                self._on_error(exc)

    def _handle_error(self, exc: Exception) -> None:
        if self._on_error:
            self._on_error(exc)


__all__ = ["TransportBase", "BytesCallback", "ErrorCallback"]


