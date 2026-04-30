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
Gateway 组件级手工测试脚本（Component Test）。

用法（组件测试；需先在 SDK 根目录执行 ``pip install -e components/agent_tools/mlink_gateway``）：

    cd <sdk-root>
    python components/agent_tools/mlink_gateway/tests/gateway_manual_test.py

如果所有断言都通过，会打印 “ALL MANUAL TESTS PASSED.”。
一旦有断言失败，Python 会抛出 AssertionError，你就能看到是哪一行出错。
"""

from __future__ import annotations

import types

from mlink.gateway.gateway.tool_router import ToolRouter
from mlink.gateway.gateway.device_registry import DeviceRegistry, DeviceSession


class DummyRpcClient:
    def __init__(self) -> None:
        self.called_with: tuple[str, dict] | None = None

    def tools_call(self, tool_name, args):
        # 记录调用参数，便于后面检查
        self.called_with = (tool_name, args)
        return {"result": {"tool": tool_name, "args": args}}


class DummyDeviceRegistry:
    def __init__(self, device_id: str, rpc_client: DummyRpcClient) -> None:
        self._device_id = device_id
        self._rpc_client = rpc_client

    def get(self, device_id: str):
        if device_id == self._device_id:
            # 模拟真实的 DeviceSession：只需要有一个 rpc_client 字段即可
            return types.SimpleNamespace(rpc_client=self._rpc_client)
        return None


class DummyToolRegistry:
    def __init__(self, full_tool_name: str, device_id: str, tool_name: str) -> None:
        self._full_tool_name = full_tool_name
        self._sd = types.SimpleNamespace(device_id=device_id, tool_name=tool_name)

    def get(self, full_tool_name: str):
        if full_tool_name == self._full_tool_name:
            return self._sd
        return None


def make_router():
    """
    构造一个带假设备、假注册表的 ToolRouter，方便下面的测试复用。
    """
    device_id = "device-1"
    full_tool_name = "ns.echo"
    tool_name = "echo"

    rpc_client = DummyRpcClient()
    devices = DummyDeviceRegistry(device_id, rpc_client)
    tools = DummyToolRegistry(full_tool_name, device_id, tool_name)

    router = ToolRouter(devices=devices, tools=tools)
    return router, rpc_client, full_tool_name


def test_normalize_arguments():
    router, _, _ = make_router()

    # 1) 单层 arguments 外壳
    raw = {"arguments": {"volume": 50}}
    norm = router._normalize_arguments(raw)  # type: ignore[attr-defined]
    assert norm == {"volume": 50}

    # 2) 多层 arguments 外壳 + None
    raw2 = {"arguments": {"arguments": {"volume": 50, "episode_time_sec": None}}}
    norm2 = router._normalize_arguments(raw2)  # type: ignore[attr-defined]
    # None 应该被过滤掉
    assert norm2 == {"volume": 50}

    # 3) 原始参数已经是“扁平”的 dict，应该保持不变（除了去掉 None）
    raw3 = {"volume": 30, "episode_time_sec": None}
    norm3 = router._normalize_arguments(raw3)  # type: ignore[attr-defined]
    assert norm3 == {"volume": 30}

    # 4) 空参数 / None
    assert router._normalize_arguments({}) == {}  # type: ignore[attr-defined]
    assert router._normalize_arguments(None) == {}  # type: ignore[arg-type, attr-defined]


def test_call_tool():
    router, rpc_client, full_tool_name = make_router()

    # 带有 arguments 外壳和 None 值的参数
    args = {"arguments": {"volume": 50, "episode_time_sec": None}}
    result = router.call_tool(full_tool_name, args)

    # 设备端实际收到的参数中不应包含 None 值
    assert rpc_client.called_with == ("echo", {"volume": 50})
    assert result == {"tool": "echo", "args": {"volume": 50}}


def test_call_tool_unknown_tool_raises():
    router, _, _ = make_router()

    try:
        router.call_tool("ns.unknown", {})
    except RuntimeError as e:
        assert "Unknown tool" in str(e)
    else:
        raise AssertionError("calling unknown tool should raise RuntimeError")


def test_device_registry_basic():
    # 使用真实的 DeviceRegistry，配合简单的 DummyTransport / DummyRpcClient
    class DummyTransport:
        def __init__(self) -> None:
            self.closed = False

        def close(self) -> None:
            self.closed = True

    registry = DeviceRegistry()
    transport1 = DummyTransport()
    rpc1 = DummyRpcClient()

    # next_device_id
    new_id = registry.next_device_id()
    assert new_id.startswith("device")

    # register_or_replace 注册第一台设备
    sess1 = registry.register_or_replace("dev1", transport1, rpc1)
    assert registry.get("dev1") is sess1

    # 再注册一次同一 device_id，需要关闭旧 transport 并替换
    transport2 = DummyTransport()
    rpc2 = DummyRpcClient()
    sess2 = registry.register_or_replace("dev1", transport2, rpc2)

    assert transport1.closed is True
    assert registry.get("dev1") is sess2
    assert isinstance(sess2, DeviceSession)
    assert sess2.transport is transport2

    # remove_device 需要关闭 transport 并从 registry 中删除
    registry.remove_device("dev1")
    assert transport2.closed is True
    assert registry.get("dev1") is None


def test_call_tool_device_error_raises():
    """
    当设备返回 {"error": "..."} 时，ToolRouter.call_tool 应抛出 RuntimeError。
    """

    class ErrorRpcClient(DummyRpcClient):
        def tools_call(self, tool_name, args):
            self.called_with = (tool_name, args)
            return {"error": "something went wrong"}

    device_id = "device-error"
    full_tool_name = "ns.err_tool"
    tool_name = "err_tool"

    rpc_client = ErrorRpcClient()
    devices = DummyDeviceRegistry(device_id, rpc_client)
    tools = DummyToolRegistry(full_tool_name, device_id, tool_name)
    router = ToolRouter(devices=devices, tools=tools)

    try:
        router.call_tool(full_tool_name, {"foo": "bar"})
    except RuntimeError as e:
        assert "Device tool error" in str(e)
    else:
        raise AssertionError("device error should cause ToolRouter.call_tool to raise RuntimeError")


def main():
    print("Running manual gateway tests...")

    test_normalize_arguments()
    print(" - test_normalize_arguments: OK")

    test_call_tool()
    print(" - test_call_tool: OK")

    test_call_tool_unknown_tool_raises()
    print(" - test_call_tool_unknown_tool_raises: OK")

    test_device_registry_basic()
    print(" - test_device_registry_basic: OK")

    test_call_tool_device_error_raises()
    print(" - test_call_tool_device_error_raises: OK")

    print("ALL MANUAL TESTS PASSED.")


if __name__ == "__main__":
    main()


