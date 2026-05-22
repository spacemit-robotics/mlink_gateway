# Copyright (C) 2026 SpacemiT (Hangzhou) Technology Co. Ltd.
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import asyncio
import json
import tempfile
from pathlib import Path

from mlink.gateway.gateway.device_registry import DeviceRegistry
from mlink.gateway.gateway.service_descriptor import ServiceDescriptor
from mlink.gateway.gateway.tool_registry import ToolRegistry
from mlink.gateway.gateway.tools_snapshot import ToolsSnapshotExporter


def register_test_services(tools: ToolRegistry) -> None:
    tools.register_service(
        ServiceDescriptor(
            full_name="dev-integ.echo",
            device_id="dev-integ",
            tool_name="echo",
            description="Echo text",
            input_schema={"type": "object", "properties": {"text": {"type": "string"}}},
        )
    )
    tools.register_service(
        ServiceDescriptor(
            full_name="dev-integ.add",
            device_id="dev-integ",
            tool_name="add",
            description="Add two integers",
            input_schema={"type": "object", "properties": {"a": {"type": "integer"}, "b": {"type": "integer"}}},
        )
    )


def assert_snapshot_contains_expected_tools(snapshot: dict) -> None:
    names = {tool["full_name"] for tool in snapshot.get("tools", [])}
    assert {"dev-integ.echo", "dev-integ.add", "gateway.ping", "gateway.status", "gateway.list_devices"}.issubset(
        names
    )
    assert snapshot.get("tool_count") == len(snapshot.get("tools", []))


async def main() -> None:
    loop = asyncio.get_running_loop()
    devices = DeviceRegistry()
    tools = ToolRegistry()
    register_test_services(tools)

    exporter = ToolsSnapshotExporter(devices=devices, tools=tools, loop=loop, config={"enabled": False})
    assert_snapshot_contains_expected_tools(exporter._build_snapshot())  # type: ignore[attr-defined]

    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "tools_snapshot.json"
        file_exporter = ToolsSnapshotExporter(
            devices=devices,
            tools=tools,
            loop=loop,
            config={"enabled": True, "path": str(path), "debounce_ms": 20},
        )
        file_exporter.mark_dirty(reason="test")
        await asyncio.sleep(0.1)
        assert path.exists()
        assert_snapshot_contains_expected_tools(json.loads(path.read_text(encoding="utf-8")))

    print("SNAPSHOT EXPORTER TESTS PASSED.")


if __name__ == "__main__":
    asyncio.run(main())
