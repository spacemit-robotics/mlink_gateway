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

from __future__ import annotations

import asyncio
import json
import os
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from mlink.gateway.gateway.device_registry import DeviceRegistry
from mlink.gateway.gateway.tool_registry import ToolRegistry
from mlink.gateway.mcp.builtin_tools import get_builtin_gateway_tools_snapshot
from mlink.gateway.utils.logger import get_logger


logger = get_logger("gateway.tools_snapshot")


@dataclass
class ToolsSnapshotConfig:
    """Configuration for exporting a snapshot of all registered tools to a file."""

    enabled: bool = False
    path: Optional[str] = None
    debounce_ms: int = 500

    @classmethod
    def from_dict(cls, data: Dict[str, Any] | None) -> "ToolsSnapshotConfig":
        data = data or {}
        return cls(
            enabled=bool(data.get("enabled", False)),
            path=data.get("path"),
            debounce_ms=int(data.get("debounce_ms", 500)),
        )


class ToolsSnapshotExporter:
    """
    Export a read-only snapshot of all registered tools to a JSON file.

    设计目标：
      - 仅用于调试与观察当前有哪些工具（设备 + 工具列表）；
      - 不参与任何请求处理逻辑（tools.call 等），避免影响交互性能；
      - 写盘在单独线程中执行，并通过抖动窗口合并高频变更。
    """

    def __init__(
        self,
        devices: DeviceRegistry,
        tools: ToolRegistry,
        loop: asyncio.AbstractEventLoop,
        config: Dict[str, Any] | None,
    ) -> None:
        self._devices = devices
        self._tools = tools
        self._loop = loop
        self._config = ToolsSnapshotConfig.from_dict(config)

        self._dirty = False
        self._lock = threading.Lock()
        self._debounce_handle: Optional[asyncio.Handle] = None

        if self._config.enabled:
            logger.info(
                "Tools snapshot export enabled, path=%s, debounce_ms=%d",
                self._config.path,
                self._config.debounce_ms,
            )

    def _is_enabled(self) -> bool:
        return bool(self._config.enabled and self._config.path)

    def mark_dirty(self, reason: str | None = None) -> None:
        """
        标记“工具集合发生变更”，稍后在事件循环中调度一次异步导出。

        该方法可以从任意线程调用（包括 mlink 同步线程），内部使用
        loop.call_soon_threadsafe 进行调度。
        """
        if not self._is_enabled():
            return

        with self._lock:
            self._dirty = True

        try:
            self._loop.call_soon_threadsafe(self._schedule_debounced_export)
        except RuntimeError:
            # 事件循环可能已结束，忽略本次导出请求。
            return

    def _schedule_debounced_export(self) -> None:
        # 已经有一个定时导出任务在路上了，直接复用即可。
        if self._debounce_handle is not None:
            return

        delay = max(self._config.debounce_ms, 0) / 1000.0

        loop = asyncio.get_running_loop()
        self._debounce_handle = loop.call_later(
            delay,
            lambda: asyncio.create_task(self._export_if_dirty()),
        )

    async def _export_if_dirty(self) -> None:
        self._debounce_handle = None

        with self._lock:
            if not self._dirty:
                return
            self._dirty = False

        snapshot = self._build_snapshot()
        await asyncio.to_thread(self._write_file, snapshot)

    def _build_snapshot(self) -> Dict[str, Any]:
        """
        根据当前的 ToolRegistry（以及可选的 DeviceRegistry 信息）构造快照。

        注意：这里只做只读访问，避免在导出过程中持锁时间过长。
        """
        from mlink.gateway.gateway.service_descriptor import ServiceDescriptor  # local import to avoid cycles

        tools_list: list[Dict[str, Any]] = get_builtin_gateway_tools_snapshot()

        try:
            services = self._tools.all_services()
        except Exception:  # pragma: no cover - 容错
            services = []

        for sd in services:
            # 类型提示友好，但不强依赖具体实现
            if not isinstance(sd, ServiceDescriptor):
                continue

            tools_list.append(
                {
                    "full_name": sd.full_name,
                    "device_id": sd.device_id,
                    "tool_name": sd.tool_name,
                    "description": sd.description,
                    "input_schema": sd.input_schema,
                    "source": "device",
                }
            )

        snapshot: Dict[str, Any] = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "tool_count": len(tools_list),
            "tools": tools_list,
        }

        # 未来如需导出设备信息，可以在此处从 DeviceRegistry 读取并附加。

        return snapshot

    def _write_file(self, snapshot: Dict[str, Any]) -> None:
        path = self._config.path
        if not path:
            return

        tmp_path = f"{path}.tmp"
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
        except Exception:
            # 目录创建失败时，后续 open 会报错，统一处理即可。
            pass

        try:
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(snapshot, f, ensure_ascii=False, indent=2)
            os.replace(tmp_path, path)
            logger.debug(
                "Tools snapshot written to %s (%d tools)",
                path,
                snapshot.get("tool_count", 0),
            )
        except Exception as exc:  # pragma: no cover - 调试设施，出错仅记录日志
            logger.error("Failed to write tools snapshot to %s: %s", path, exc)


__all__ = ["ToolsSnapshotExporter", "ToolsSnapshotConfig"]



