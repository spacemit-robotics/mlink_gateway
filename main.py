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
Gateway entrypoint.

High-level flow:
- Start transport servers (TCP/Unix) and accept incoming mlink device connections.
- For each connection, create a session:
  - Wrap the socket into a TransportBase implementation.
  - Create a JSON-RPC client and call initialize/tools.list/tools.call.
  - Sync tool metadata and register services into the local registries.
- Start an MCP server (FastMCP; HTTP is the default transport, stdio optional) and
  expose all registered tools to upstream clients (LLM / Pipecat / Hermes).
"""

import argparse
import asyncio
from dataclasses import dataclass
from pathlib import Path

from mlink.gateway.config.loader import load_gateway_config
from mlink.gateway.gateway.device_registry import DeviceRegistry
from mlink.gateway.gateway.tool_registry import ToolRegistry
from mlink.gateway.gateway.tool_router import ToolRouter
from mlink.gateway.gateway.tools_snapshot import ToolsSnapshotExporter
from mlink.gateway.mcp.mcp_server import GatewayMcpServer
from mlink.gateway.protocol.mlink_session import MlinkSessionHandler
from mlink.gateway.transport.manager import TransportManager, build_transport_configs
from mlink.gateway.utils.logger import get_logger


logger = get_logger("gateway.main")


@dataclass(frozen=True)
class GatewayRunConfig:
    mcp_transport: str = "http"
    mcp_host: str = "127.0.0.1"
    mcp_port: int = 18765
    mcp_path: str = "/mcp"


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="SpacemiT mlink MCP gateway")
    parser.add_argument(
        "--mcp-transport",
        choices=("stdio", "http"),
        default="http",
        help="How to expose the MCP server to upstream clients.",
    )
    parser.add_argument(
        "--mcp-host",
        default="127.0.0.1",
        help="Host to bind when --mcp-transport=http.",
    )
    parser.add_argument(
        "--mcp-port",
        type=int,
        default=18765,
        help="Port to bind when --mcp-transport=http.",
    )
    parser.add_argument(
        "--mcp-path",
        default="/mcp",
        help="HTTP path to mount when --mcp-transport=http.",
    )
    return parser


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    return build_arg_parser().parse_args(argv)


async def run_gateway(config: GatewayRunConfig) -> None:
    # Load config.
    config_path = Path(__file__).with_suffix("").parent / "config" / "gateway.yaml"
    cfg = load_gateway_config(config_path)
    devices_cfg = cfg.get("devices", {})
    tools_snapshot_cfg = devices_cfg.get("tools_snapshot") or {}

    devices = DeviceRegistry()
    tools = ToolRegistry()

    # 2. 构建 ToolRouter、ToolsSnapshotExporter 和 MCP Server
    router = ToolRouter(devices=devices, tools=tools)
    loop = asyncio.get_running_loop()
    snapshot_exporter = ToolsSnapshotExporter(
        devices=devices,
        tools=tools,
        loop=loop,
        config=tools_snapshot_cfg,
    )
    mcp_server = GatewayMcpServer(
        devices=devices,
        tool_registry=tools,
        tool_router=router,
        loop=loop,
        snapshot_exporter=snapshot_exporter,
    )

    # 3. 构建 mlink 会话处理器
    session_handler = MlinkSessionHandler(devices=devices, mcp_server=mcp_server)

    # 4. 构建并启动 TransportManager，根据配置监听多个传输端点
    transport_configs = build_transport_configs(devices_cfg)
    transport_manager = TransportManager(
        configs=transport_configs,
        on_connection=session_handler.handle_new_connection,
    )
    transport_manager.start()

    logger.info("Waiting for mlink devices to connect on configured transports ...")

    # 5. 根据参数选择 MCP 传输方式。
    if config.mcp_transport == "http":
        logger.info(
            "Starting MCP server in HTTP mode on http://%s:%d%s",
            config.mcp_host,
            config.mcp_port,
            config.mcp_path,
        )
        await mcp_server.run_http(
            host=config.mcp_host,
            port=config.mcp_port,
            mount_path=config.mcp_path,
        )
    else:
        logger.info("Starting MCP server in stdio mode")
        await mcp_server.run_stdio()


async def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    await run_gateway(
        GatewayRunConfig(
            mcp_transport=args.mcp_transport,
            mcp_host=args.mcp_host,
            mcp_port=args.mcp_port,
            mcp_path=args.mcp_path,
        )
    )


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        raise SystemExit(130) from None


