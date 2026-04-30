# mlink gateway

设备侧 MCP 工具（`tools/list` / `tools/call`）汇总成一个 **MCP Server**，供上层 Agent（`voice_chat`、Hermes、Cursor 等）调用。

**默认对外暴露方式为 HTTP**（`streamable-http`，便于常驻与多客户端）。内置诊断工具：`gateway.ping`、`gateway.status`、`gateway.list_devices`。

---

## 环境与安装

在 SDK 根目录：

```bash
m_env_build components/agent_tools/mlink_gateway/
source output/envs/mlink-gateway/bin/activate
pip install -e components/agent_tools/mlink_gateway
```

每个虚拟环境只需执行一次 `pip install -e`，之后 `import mlink.gateway` 即可。

---

## 常用命令（HTTP）

后台常驻（推荐日常使用）：

```bash
mlink gateway start          # 默认 http://127.0.0.1:18765/mcp，日志 /tmp/mlink-gateway/gateway.log
mlink gateway status | tools | test
mlink gateway stop           # 或 restart
```

前台调试（默认同样是 HTTP，日志在终端）：

```bash
mlink gateway run            # 等价于 --mcp-transport http --mcp-host 127.0.0.1 --mcp-port 18765
```

自定义监听：

```bash
mlink gateway start --mcp-host 127.0.0.1 --mcp-port 18765 --mcp-path /mcp
```

直接用模块入口（需已 `pip install -e`）：

```bash
python -m mlink.gateway.main
```

---

## 最小联调

1. 启动 gateway：`mlink gateway start`
2. 设备示例：`mlink_device_test`（另开终端）
3. MCP 客户端使用 HTTP 配置，例如：`components/agent_tools/mcp/examples/configs/mlink_http.json`（`http://127.0.0.1:18765/mcp`）

联调 **`voice_chat` / omni_agent**：先 **`mlink gateway start`**，再使用该 MCP 配置（可按需修改 JSON 里的 `url` / `model` 或与命令行 `--llm-url` 保持一致）：

```bash
voice_chat --llm-url http://127.0.0.1:8080 \
  --mcp-config components/agent_tools/mcp/examples/configs/mlink_http.json
```

---

## 常见问题

- **`tools` 只有 `gateway.*`**：先起 `mlink_device_test`，再看 gateway 日志里是否有设备连接与 `Registered tool ...`。
- **HTTP 测不通**：`mlink gateway status`、查 `/tmp/mlink-gateway/gateway.log`；残留 `/tmp/mlink.sock` 时可 `mlink gateway restart`。
