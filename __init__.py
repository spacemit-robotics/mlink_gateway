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
Gateway package.

This package implements a multi-layer MCP gateway:

- transport_layer:  抽象底层物理连接（目前先实现 TCP 服务端，支持多个 mlink 设备接入）。
- protocol_layer:   MCP JSON-RPC 协议客户端，对接右侧 mlink（C 版 MCP Server）。
- gateway_layer:    设备与工具的注册/路由，将工具调用映射到具体设备和协议。
- mcp_layer:        基于官方 python-sdk 的 MCP Server，对接左侧 LLM / Pipecat。

Entry point:

- ``mlink.gateway.main`` 提供了 ``python -m mlink.gateway.main`` 启动方式（开发环境请先在仓库根目录执行
  ``pip install -e components/agent_tools/mlink_gateway`` 注册本包）。

  Pipecat 应用通过这个入口在子进程中启动 Gateway MCP Server。
"""


