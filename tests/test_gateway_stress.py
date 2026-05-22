# Copyright (C) 2026 SpacemiT (Hangzhou) Technology Co. Ltd.
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import asyncio
import logging
import time

from mlink.gateway.gateway.device_registry import DeviceRegistry
from mlink.gateway.gateway.service_descriptor import ServiceDescriptor
from mlink.gateway.gateway.tool_registry import ToolRegistry
from mlink.gateway.gateway.tool_router import ToolRouter


class DummyTransport:
    def close(self) -> None:
        pass


class StressRpcClient:
    def __init__(self) -> None:
        self.call_count = 0

    def tools_call(self, name: str, args: dict) -> dict:
        self.call_count += 1
        if name == "stress.echo":
            return {"result": {"value": args.get("value"), "worker": args.get("worker")}}
        if name == "stress.add1":
            return {"result": int(args.get("value", 0)) + 1}
        return {"error": f"unknown tool {name}"}


async def main() -> None:
    logging.getLogger("gateway.tool_router").setLevel(logging.WARNING)

    devices = DeviceRegistry()
    tools = ToolRegistry()
    router = ToolRouter(devices=devices, tools=tools)

    rpc_client = StressRpcClient()
    devices.register_or_replace("dev-stress", DummyTransport(), rpc_client)

    echo_sd = ServiceDescriptor(
        full_name="dev-stress.stress.echo",
        device_id="dev-stress",
        tool_name="stress.echo",
        description="Echo value for stress test",
        input_schema={"type": "object", "properties": {"value": {"type": "integer"}, "worker": {"type": "integer"}}},
    )
    add1_sd = ServiceDescriptor(
        full_name="dev-stress.stress.add1",
        device_id="dev-stress",
        tool_name="stress.add1",
        description="Add 1 for stress test",
        input_schema={"type": "object", "properties": {"value": {"type": "integer"}}},
    )
    tools.register_service(echo_sd)
    tools.register_service(add1_sd)

    concurrency = 20
    calls_per_worker = 200
    total_calls_expected = concurrency * calls_per_worker * 2

    async def worker(worker_id: int) -> None:
        for i in range(calls_per_worker):
            echo_res = router.call_tool(echo_sd.full_name, {"value": i, "worker": worker_id, "unused": None})
            assert echo_res["value"] == i
            assert echo_res["worker"] == worker_id

            add_res = router.call_tool(add1_sd.full_name, {"value": i, "maybe_none": None})
            assert add_res == i + 1

    start = time.perf_counter()
    await asyncio.gather(*(worker(w) for w in range(concurrency)))
    elapsed = time.perf_counter() - start

    assert rpc_client.call_count == total_calls_expected, (
        f"expected {total_calls_expected} calls, got {rpc_client.call_count}"
    )
    print(f"STRESS TEST PASSED. total_calls={rpc_client.call_count} elapsed={elapsed:.3f}s")


if __name__ == "__main__":
    asyncio.run(main())
