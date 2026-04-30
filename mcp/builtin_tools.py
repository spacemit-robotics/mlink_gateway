from __future__ import annotations

from datetime import datetime, timezone
from inspect import Signature
from typing import Any
from mlink.gateway.gateway.device_registry import DeviceRegistry
from mlink.gateway.gateway.tool_registry import ToolRegistry


BUILTIN_GATEWAY_TOOLS: tuple[dict[str, Any], ...] = (
    {
        "full_name": "gateway.ping",
        "device_id": "gateway",
        "tool_name": "ping",
        "description": "Lightweight connectivity check for the gateway itself.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "full_name": "gateway.status",
        "device_id": "gateway",
        "tool_name": "status",
        "description": "Report gateway status, connected devices, and registered tools.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "full_name": "gateway.list_devices",
        "device_id": "gateway",
        "tool_name": "list_devices",
        "description": "List currently connected devices and the tools each device exposes.",
        "input_schema": {"type": "object", "properties": {}},
    },
)

BUILTIN_GATEWAY_TOOL_NAMES: tuple[str, ...] = tuple(
    tool["full_name"] for tool in BUILTIN_GATEWAY_TOOLS
)


def get_builtin_gateway_tools_snapshot() -> list[dict[str, Any]]:
    """Return serializable metadata for builtin gateway tools."""
    return [dict(tool, source="builtin") for tool in BUILTIN_GATEWAY_TOOLS]


def register_builtin_gateway_tools(
    *,
    server: Any,
    devices: DeviceRegistry,
    tool_registry: ToolRegistry,
    live_sessions: set[Any],
) -> tuple[str, ...]:
    """Register builtin, read-only gateway diagnostics tools."""

    async def gateway_ping() -> dict[str, Any]:
        return {
            "ok": True,
            "server": server.name,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "live_session_count": len(live_sessions),
        }

    async def gateway_status() -> dict[str, Any]:
        dynamic_tools = sorted(sd.full_name for sd in tool_registry.all_services())
        device_ids = sorted(devices.list_devices())
        return {
            "server": server.name,
            "ok": True,
            "connected_device_count": len(device_ids),
            "connected_devices": device_ids,
            "dynamic_tool_count": len(dynamic_tools),
            "dynamic_tools": dynamic_tools,
            "builtin_tool_count": len(BUILTIN_GATEWAY_TOOL_NAMES),
            "builtin_tools": list(BUILTIN_GATEWAY_TOOL_NAMES),
            "registered_tool_count": len(dynamic_tools) + len(BUILTIN_GATEWAY_TOOL_NAMES),
            "registered_tools": list(BUILTIN_GATEWAY_TOOL_NAMES) + dynamic_tools,
            "live_session_count": len(live_sessions),
        }

    async def gateway_list_devices() -> dict[str, Any]:
        discovered_devices = []
        for device_id in sorted(devices.list_devices()):
            session = devices.get(device_id)
            tool_names = []
            if session is not None:
                tool_names = sorted(
                    tool.get("name", "")
                    for tool in session.tools
                    if isinstance(tool, dict) and tool.get("name")
                )
            discovered_devices.append(
                {
                    "device_id": device_id,
                    "tool_count": len(tool_names),
                    "tools": tool_names,
                }
            )
        return {
            "device_count": len(discovered_devices),
            "devices": discovered_devices,
        }

    _register_builtin_tool(server, descriptor=BUILTIN_GATEWAY_TOOLS[0], handler=gateway_ping)
    _register_builtin_tool(server, descriptor=BUILTIN_GATEWAY_TOOLS[1], handler=gateway_status)
    _register_builtin_tool(server, descriptor=BUILTIN_GATEWAY_TOOLS[2], handler=gateway_list_devices)
    return BUILTIN_GATEWAY_TOOL_NAMES


def _register_builtin_tool(
    server: Any,
    *,
    descriptor: dict[str, Any],
    handler: Any,
) -> None:
    """Register an internal gateway tool that does not route to a device."""
    handler.__signature__ = Signature(parameters=[])  # type: ignore[attr-defined]
    server._tool_manager.add_tool(  # type: ignore[attr-defined]
        handler,
        name=descriptor["full_name"],
        description=descriptor["description"],
    )
