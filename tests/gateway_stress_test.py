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
Gateway 压力/并发测试脚本（Stress Test）。

目标：
  - 在单进程内模拟 20 个“并发调用者”，持续高频调用 ToolRouter.call_tool；
  - 验证在并发场景下：
      * 参数归一化 + None 过滤逻辑不会出错；
      * DeviceRegistry / ToolRegistry / ToolRouter 协同工作正常；
      * 设备端（DummyRpcClient）不会抛异常或卡死。

用法（需先在 SDK 根目录执行 ``pip install -e components/agent_tools/mlink_gateway``）：

    cd <sdk-root>
    python components/agent_tools/mlink_gateway/tests/gateway_stress_test.py

所有断言通过时，会打印总调用次数与耗时，并输出 “STRESS TEST PASSED.”。
"""

from __future__ import annotations

import asyncio
import time

from mlink.gateway.gateway.device_registry import DeviceRegistry
from mlink.gateway.gateway.tool_registry import ToolRegistry
from mlink.gateway.gateway.tool_router import ToolRouter
from mlink.gateway.gateway.service_descriptor import ServiceDescriptor


class DummyTransport:
    def close(self) -> None:
        # 压测中不关心底层连接资源，提供空实现即可
        pass


class StressRpcClient:
    """
    简单的假设备 RPC 客户端：
      - 记录调用次数和最后一次收到的参数；
      - 模拟一个回显/加一的工具实现。
    """

    def __init__(self) -> None:
        self.call_count = 0
        self.last_args: dict | None = None

    def tools_call(self, name: str, args: dict) -> dict:
        self.call_count += 1
        self.last_args = args
        # 模拟一个简单工具逻辑：返回输入 value + 1
        if name == "stress.echo":
            return {"result": {"value": args.get("value"), "worker": args.get("worker")}}
        if name == "stress.add1":
            v = int(args.get("value", 0))
            return {"result": v + 1}
        return {"error": f"unknown tool {name}"}


async def main() -> None:
    print("Running gateway stress test with 20 concurrent workers...")

    devices = DeviceRegistry()
    tools = ToolRegistry()
    router = ToolRouter(devices=devices, tools=tools)

    # 注册一个假设备
    rpc_client = StressRpcClient()
    devices.register_or_replace("dev-stress", DummyTransport(), rpc_client)

    # 注册两个简单工具：stress.echo / stress.add1
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

    CONCURRENCY = 20
    CALLS_PER_WORKER = 200
    total_calls_expected = CONCURRENCY * CALLS_PER_WORKER * 2  # 每次循环调用两个工具

    async def worker(worker_id: int) -> None:
        for i in range(CALLS_PER_WORKER):
            # 包含一个 None 参数，验证在高并发场景下 None 过滤逻辑也稳定
            echo_res = router.call_tool(
                echo_sd.full_name,
                {"value": i, "worker": worker_id, "unused": None},
            )
            assert echo_res["value"] == i
            assert echo_res["worker"] == worker_id

            add_res = router.call_tool(
                add1_sd.full_name,
                {"value": i, "maybe_none": None},
            )
            assert add_res == i + 1

    start = time.perf_counter()
    tasks = [asyncio.create_task(worker(w)) for w in range(CONCURRENCY)]
    await asyncio.gather(*tasks)
    elapsed = time.perf_counter() - start

    # 所有调用都应该成功，且总调用次数达到预期
    assert rpc_client.call_count == total_calls_expected, (
        f"expected {total_calls_expected} calls, got {rpc_client.call_count}"
    )

    print(f" - total calls: {rpc_client.call_count}, elapsed: {elapsed:.3f}s")
    print("STRESS TEST PASSED.")


if __name__ == "__main__":
    asyncio.run(main())


