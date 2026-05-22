# Copyright (C) 2026 SpacemiT (Hangzhou) Technology Co. Ltd.
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import types

from mlink.gateway.gateway.device_registry import DeviceRegistry, DeviceSession
from mlink.gateway.gateway.tool_router import ToolRouter


class DummyRpcClient:
    def __init__(self) -> None:
        self.called_with: tuple[str, dict] | None = None

    def tools_call(self, tool_name, args):
        self.called_with = (tool_name, args)
        return {"result": {"tool": tool_name, "args": args}}


class DummyDeviceRegistry:
    def __init__(self, device_id: str, rpc_client: DummyRpcClient) -> None:
        self._device_id = device_id
        self._rpc_client = rpc_client

    def get(self, device_id: str):
        if device_id == self._device_id:
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
    device_id = "device-1"
    full_tool_name = "ns.echo"
    tool_name = "echo"
    rpc_client = DummyRpcClient()
    devices = DummyDeviceRegistry(device_id, rpc_client)
    tools = DummyToolRegistry(full_tool_name, device_id, tool_name)
    return ToolRouter(devices=devices, tools=tools), rpc_client, full_tool_name


def test_normalize_arguments() -> None:
    router, _, _ = make_router()

    assert router._normalize_arguments({"arguments": {"volume": 50}}) == {"volume": 50}  # type: ignore[attr-defined]
    assert router._normalize_arguments(  # type: ignore[attr-defined]
        {"arguments": {"arguments": {"volume": 50, "episode_time_sec": None}}}
    ) == {"volume": 50}
    assert router._normalize_arguments({"volume": 30, "episode_time_sec": None}) == {"volume": 30}  # type: ignore[attr-defined]
    assert router._normalize_arguments({}) == {}  # type: ignore[attr-defined]
    assert router._normalize_arguments(None) == {}  # type: ignore[arg-type, attr-defined]


def test_call_tool_normalizes_arguments() -> None:
    router, rpc_client, full_tool_name = make_router()

    result = router.call_tool(full_tool_name, {"arguments": {"volume": 50, "episode_time_sec": None}})

    assert rpc_client.called_with == ("echo", {"volume": 50})
    assert result == {"tool": "echo", "args": {"volume": 50}}


def test_call_tool_unknown_tool_raises() -> None:
    router, _, _ = make_router()

    try:
        router.call_tool("ns.unknown", {})
    except RuntimeError as exc:
        assert "Unknown tool" in str(exc)
    else:
        raise AssertionError("calling unknown tool should raise RuntimeError")


def test_call_tool_device_error_raises() -> None:
    class ErrorRpcClient(DummyRpcClient):
        def tools_call(self, tool_name, args):
            self.called_with = (tool_name, args)
            return {"error": "something went wrong"}

    device_id = "device-error"
    full_tool_name = "ns.err_tool"
    tool_name = "err_tool"
    rpc_client = ErrorRpcClient()
    router = ToolRouter(
        devices=DummyDeviceRegistry(device_id, rpc_client),
        tools=DummyToolRegistry(full_tool_name, device_id, tool_name),
    )

    try:
        router.call_tool(full_tool_name, {"foo": "bar"})
    except RuntimeError as exc:
        assert "Device tool error" in str(exc)
    else:
        raise AssertionError("device error should cause RuntimeError")


def test_device_registry_replace_and_remove() -> None:
    class DummyTransport:
        def __init__(self) -> None:
            self.closed = False

        def close(self) -> None:
            self.closed = True

    registry = DeviceRegistry()
    transport1 = DummyTransport()
    rpc1 = DummyRpcClient()

    assert registry.next_device_id().startswith("device")

    sess1 = registry.register_or_replace("dev1", transport1, rpc1)
    assert registry.get("dev1") is sess1

    transport2 = DummyTransport()
    rpc2 = DummyRpcClient()
    sess2 = registry.register_or_replace("dev1", transport2, rpc2)

    assert transport1.closed is True
    assert registry.get("dev1") is sess2
    assert isinstance(sess2, DeviceSession)
    assert sess2.transport is transport2

    registry.remove_device("dev1")
    assert transport2.closed is True
    assert registry.get("dev1") is None


def main() -> None:
    test_normalize_arguments()
    test_call_tool_normalizes_arguments()
    test_call_tool_unknown_tool_raises()
    test_call_tool_device_error_raises()
    test_device_registry_replace_and_remove()
    print("ROUTER REGISTRY TESTS PASSED.")


if __name__ == "__main__":
    main()
