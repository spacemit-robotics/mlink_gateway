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

from typing import Any, Dict

import asyncio
from contextlib import AsyncExitStack
from inspect import Parameter, Signature
from types import MethodType

import anyio
from mcp.server import FastMCP
from mcp.server.lowlevel import NotificationOptions
from mcp.server.session import ServerSession
from mcp.server.stdio import stdio_server

from mlink.gateway.gateway.device_registry import DeviceRegistry
from mlink.gateway.gateway.service_descriptor import ServiceDescriptor
from mlink.gateway.gateway.tool_registry import ToolRegistry
from mlink.gateway.gateway.tool_router import ToolRouter
from mlink.gateway.gateway.tools_snapshot import ToolsSnapshotExporter
from mlink.gateway.mcp.builtin_tools import register_builtin_gateway_tools


class GatewayMcpServer:
    """
    MCP Server 实现：
      - 使用官方 python-sdk 提供的 FastMCP 封装，
        参考: https://github.com/modelcontextprotocol/python-sdk
      - 动态从 ToolRegistry 加载工具，将调用转发到 ToolRouter。
    """

    def __init__(
        self,
        devices: DeviceRegistry,
        tool_registry: ToolRegistry,
        tool_router: ToolRouter,
        loop: asyncio.AbstractEventLoop,
        snapshot_exporter: ToolsSnapshotExporter | None = None,
    ) -> None:
        self._server = FastMCP("mcp-gateway")
        self._tool_registry = tool_registry
        self._tool_router = tool_router
        # 保存事件循环与活跃 ServerSession，供工具列表变更时发送通知。
        self._loop = loop
        self._live_sessions: set[ServerSession] = set()
        # 可选：在工具变更时导出调试快照。
        self._snapshot_exporter = snapshot_exporter
        self._builtin_tool_names = register_builtin_gateway_tools(
            server=self._server,
            devices=devices,
            tool_registry=self._tool_registry,
            live_sessions=self._live_sessions,
        )
        if self._snapshot_exporter is not None:
            self._snapshot_exporter.mark_dirty(reason="register_builtin_tools")

    def _build_init_options(self) -> Any:
        """Create initialization options with tools.listChanged enabled."""
        lowlevel_server = self._server._mcp_server  # type: ignore[attr-defined]
        return lowlevel_server.create_initialization_options(
            notification_options=NotificationOptions(
                prompts_changed=False,
                resources_changed=False,
                tools_changed=True,
            ),
            experimental_capabilities={},
        )

    def _patch_http_init_options(self) -> None:
        """
        Ensure FastMCP's HTTP transport declares tools.listChanged.

        FastMCP's built-in StreamableHTTP transport calls the low-level server's
        create_initialization_options() internally, so we wrap that method to
        inject the same notification capabilities used by stdio mode.
        """
        lowlevel_server = self._server._mcp_server  # type: ignore[attr-defined]
        original = lowlevel_server.create_initialization_options

        if getattr(lowlevel_server, "_mlink_http_init_patched", False):
            return

        def _wrapped_create_initialization_options(
            this: Any,
            notification_options: NotificationOptions | None = None,
            experimental_capabilities: dict[str, dict[str, Any]] | None = None,
        ) -> Any:
            options = notification_options or NotificationOptions()
            merged = NotificationOptions(
                prompts_changed=options.prompts_changed,
                resources_changed=options.resources_changed,
                tools_changed=True,
            )
            return original(
                notification_options=merged,
                experimental_capabilities=experimental_capabilities or {},
            )

        lowlevel_server.create_initialization_options = MethodType(  # type: ignore[method-assign]
            _wrapped_create_initialization_options,
            lowlevel_server,
        )
        lowlevel_server._mlink_http_init_patched = True  # type: ignore[attr-defined]

    def _patch_lowlevel_run_for_session_tracking(self) -> None:
        """
        Wrap lowlevel Server.run() so HTTP sessions can also receive tool updates.

        FastMCP's StreamableHTTP transport hides ServerSession creation inside the
        SDK, so we mirror the upstream implementation and keep a best-effort set of
        live sessions that can receive tools/list_changed notifications.
        """
        lowlevel_server = self._server._mcp_server  # type: ignore[attr-defined]

        if getattr(lowlevel_server, "_mlink_run_patched", False):
            return

        async def _wrapped_run(
            this: Any,
            read_stream: Any,
            write_stream: Any,
            initialization_options: Any,
            raise_exceptions: bool = False,
            stateless: bool = False,
        ) -> None:
            async with AsyncExitStack() as stack:
                lifespan_context = await stack.enter_async_context(this.lifespan(this))
                session = await stack.enter_async_context(
                    ServerSession(
                        read_stream,
                        write_stream,
                        initialization_options,
                        stateless=stateless,
                    )
                )

                if not stateless:
                    self._live_sessions.add(session)

                try:
                    task_support = this._experimental_handlers.task_support if this._experimental_handlers else None
                    if task_support is not None:
                        task_support.configure_session(session)
                        await stack.enter_async_context(task_support.run())

                    async with anyio.create_task_group() as tg:
                        try:
                            async for message in session.incoming_messages:
                                tg.start_soon(
                                    this._handle_message,
                                    message,
                                    session,
                                    lifespan_context,
                                    raise_exceptions,
                                )
                        finally:
                            tg.cancel_scope.cancel()
                finally:
                    if not stateless:
                        self._live_sessions.discard(session)

        lowlevel_server.run = MethodType(_wrapped_run, lowlevel_server)  # type: ignore[method-assign]
        lowlevel_server._mlink_run_patched = True  # type: ignore[attr-defined]

    def register_service(self, sd: ServiceDescriptor) -> None:
        """
        将一个 ServiceDescriptor 注册到：
          1) 内部 ToolRegistry（供路由层查询）
          2) FastMCP 实例（供 MCP 客户端通过 tools/list & tools/call 使用）
        """
        # 先更新本地注册表
        self._tool_registry.register_service(sd)

        # 根据设备上报的 JSON Schema 动态构造参数签名，
        # 让 FastMCP / Pydantic 按真实字段名（如 direction、pose_name）做校验。
        properties: Dict[str, Any] = sd.input_schema.get("properties", {}) if sd.input_schema else {}
        required = set(sd.input_schema.get("required", []) if sd.input_schema else [])

        async def impl(**tool_args: Any) -> Any:
            """
            统一的工具入口：
              - `tool_args` 中包含展开后的业务参数（如 direction='left'）；
              - 直接转发给 ToolRouter，由其负责进一步规范化（包括剥掉多余的 "arguments" 包装）
                并下发到 mlink 设备。
            """
            return self._tool_router.call_tool(sd.full_name, dict(tool_args))

        # 为 impl 注入动态签名，使 FastMCP 能从中生成正确的参数模型：
        #   - 每个 JSON Schema 的 property 生成一个 KEYWORD_ONLY 形参；
        #   - 在 required 列表中的参数为必填，其他参数带默认值 None（可选）。
        parameters = []
        for name in properties.keys():
            prop_schema = properties[name]
            if name in required:
                parameters.append(Parameter(name, kind=Parameter.KEYWORD_ONLY))
            else:
                # 尝试从 Schema 中获取默认值，如果存在则使用它，否则使用 None
                default_val = prop_schema.get("default", None)
                parameters.append(Parameter(name, kind=Parameter.KEYWORD_ONLY, default=default_val))
        impl.__signature__ = Signature(parameters=parameters)  # type: ignore[attr-defined]

        # 使用 FastMCP 注册工具；inputSchema 将自动从 impl 的签名推导。
        self._server._tool_manager.add_tool(  # type: ignore[attr-defined]
            impl,
            name=sd.full_name,
            description=sd.description,
        )

        # 工具注册完成后，通过通知告知所有已连接的 MCP 客户端：
        # tools.list 已发生变化。
        self._schedule_tools_changed_notification()

        # 标记工具集合已变更，供调试快照使用（如已启用）。
        if self._snapshot_exporter is not None:
            self._snapshot_exporter.mark_dirty(reason="register_service")

    def unregister_device(self, device_id: str) -> None:
        """
        删除指定设备的所有工具映射。
        注意：FastMCP 目前没有公开的移除工具 API，这里只从 ToolRegistry 中删除；
        实际调用时 ToolRouter 会因找不到 ServiceDescriptor 而报 Unknown tool。
        """
        self._tool_registry.remove_by_device(device_id)

        # 设备下线后，相关工具被移除，同样发送 tools.listChanged 通知。
        self._schedule_tools_changed_notification()

        if self._snapshot_exporter is not None:
            self._snapshot_exporter.mark_dirty(reason="unregister_device")

    def _schedule_tools_changed_notification(self) -> None:
        """
        在线程安全的方式下调度一次 tools/list_changed 通知。
        该方法可从非事件循环线程调用（例如 mlink 后台同步线程）。
        """

        async def _notify() -> None:
            for session in tuple(self._live_sessions):
                try:
                    await session.send_tool_list_changed()
                except Exception:
                    # 避免因为通知失败导致整个 gateway 崩溃，仅记录日志。
                    import logging

                    logging.exception("Failed to send tools/list_changed notification to MCP client")

        # 将协程安全地调度到主事件循环中执行。
        try:
            self._loop.call_soon_threadsafe(lambda: asyncio.create_task(_notify()))
        except RuntimeError:
            # 事件循环可能已经关闭或尚未就绪，忽略这次通知。
            pass

    async def run_stdio(self) -> None:
        """
        通过 stdio 启动 MCP Server，供 LLM / Pipecat 作为 MCP client 连接。
        与 FastMCP.run_stdio_async 不同，这里直接调用底层 lowlevel Server，
        以便：
          - 在 initialize 阶段声明支持 tools.listChanged 通知；
          - 持有 ServerSession 引用，后续在工具列表变更时发送
            notifications/tools/list_changed。
        """
        # FastMCP 内部持有低层 Server 实例，供我们直接使用。
        lowlevel_server = self._server._mcp_server  # type: ignore[attr-defined]
        self._patch_lowlevel_run_for_session_tracking()

        # 声明支持 tools.listChanged，便于客户端订阅工具变更通知。
        init_options = self._build_init_options()

        async with stdio_server() as (read_stream, write_stream):
            await lowlevel_server.run(
                read_stream,
                write_stream,
                init_options,
                False,  # raise_exceptions
            )

    async def run_http(
        self,
        host: str = "127.0.0.1",
        port: int = 18765,
        mount_path: str = "/mcp",
    ) -> None:
        """
        通过 Streamable HTTP 启动 MCP Server，适合常驻进程模式。

        复用 FastMCP 官方 HTTP transport，并在初始化阶段声明
        tools.listChanged 能力，确保 HTTP 客户端重连时能拿到最新工具集。
        """
        self._server.settings.host = host
        self._server.settings.port = port
        self._server.settings.streamable_http_path = mount_path

        self._patch_lowlevel_run_for_session_tracking()
        self._patch_http_init_options()
        await self._server.run_streamable_http_async()


__all__ = ["GatewayMcpServer"]

