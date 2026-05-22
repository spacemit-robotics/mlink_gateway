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

import threading
from typing import Any, Dict, Optional, Callable

from mlink.gateway.utils import json_tools


class PendingCall:
    def __init__(self, timeout: float = 10.0) -> None:
        self.event = threading.Event()
        self.response: Optional[Dict[str, Any]] = None
        self.timeout = timeout

    def wait(self) -> Dict[str, Any]:
        if not self.event.wait(self.timeout):
            raise TimeoutError("MCP JSON-RPC call timed out")
        assert self.response is not None
        return self.response


class MlinkMcpJsonRpcClient:
    """
    Minimal JSON-RPC client for talking to mlink's MCP server over a line-based
    text stream.

    mlink 侧期望收到标准 MCP JSON-RPC 请求：
      - initialize
      - tools/list
      - tools/call

    这里我们只关心这几种方法。
    """

    def __init__(self, send_text: Callable[[str], None]) -> None:
        self._send_text = send_text
        self._next_id = 1
        self._pending: Dict[int, PendingCall] = {}
        self._lock = threading.Lock()

    def handle_text(self, text: str) -> None:
        """
        Called by upper layers whenever a full JSON line is received from mlink.
        """
        if not text:
            return
        obj = json_tools.loads(text)
        if "id" not in obj:
            # ignore notifications for now
            return
        try:
            req_id = int(obj["id"])
        except (TypeError, ValueError):
            return
        pending = None
        with self._lock:
            pending = self._pending.pop(req_id, None)
        if pending is not None:
            pending.response = obj
            pending.event.set()

    def _call(self, method: str, params: Optional[Dict[str, Any]] = None, timeout: float = 10.0) -> Dict[str, Any]:
        with self._lock:
            req_id = self._next_id
            self._next_id += 1
            pending = PendingCall(timeout=timeout)
            self._pending[req_id] = pending
        request = {
            "jsonrpc": "2.0",
            "id": req_id,
            "method": method,
            "params": params or {},
        }
        self._send_text(json_tools.dumps(request))
        try:
            return pending.wait()
        except Exception:
            with self._lock:
                self._pending.pop(req_id, None)
            raise

    # High-level MCP helpers

    def initialize(self) -> Dict[str, Any]:
        params = {
            "protocolVersion": "2024-11-05",
            "clientName": "mcp_gateway",
            "clientVersion": "0.1.0",
        }
        return self._call("initialize", params)

    def tools_list(self, cursor: Optional[str] = None, with_user_tools: bool = False) -> Dict[str, Any]:
        params: Dict[str, Any] = {}
        if cursor is not None:
            params["cursor"] = cursor
        params["withUserTools"] = with_user_tools
        return self._call("tools/list", params)

    def tools_call(self, name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        params: Dict[str, Any] = {
            "name": name,
            "arguments": arguments,
        }
        return self._call("tools/call", params, timeout=30.0)


__all__ = ["MlinkMcpJsonRpcClient"]

