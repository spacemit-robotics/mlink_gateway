"""CLI for managing the mlink gateway daemon and foreground runner."""

from __future__ import annotations

import sys
from pathlib import Path

# Running `python .../cli.py` puts this directory first on sys.path; the local `mcp/`
# package tree then shadows PyPI `mcp`. Drop script dir so `mcp.client` resolves.
_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) in sys.path:
    sys.path.remove(str(_SCRIPT_DIR))

import argparse  # noqa: E402
import asyncio  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402
import subprocess  # noqa: E402
import time  # noqa: E402

from mcp.client.session import ClientSession  # noqa: E402
from mcp.client.streamable_http import streamable_http_client  # noqa: E402

from mlink.gateway.main import GatewayRunConfig, run_gateway  # noqa: E402
from mlink.gateway.runtime import (  # noqa: E402
    LOG_PATH_ENV,
    STATE_DIR_ENV,
    cleanup_stale_socket,
    cleanup_stale_state,
    clear_runtime_state,
    get_log_path,
    get_state_dir,
    is_process_running,
    load_gateway_device_paths,
    read_pid,
    read_runtime_state,
    tcp_port_listening,
    terminate_process,
    write_runtime_state,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="SpacemiT mlink CLI")
    subparsers = parser.add_subparsers(dest="command")

    gateway_parser = subparsers.add_parser("gateway", help="Manage the mlink gateway")
    gateway_sub = gateway_parser.add_subparsers(dest="gateway_command")

    run_parser = gateway_sub.add_parser("run", help="Run gateway in foreground")
    run_parser.add_argument("--mcp-transport", choices=("stdio", "http"), default="http")
    run_parser.add_argument("--mcp-host", default="127.0.0.1")
    run_parser.add_argument("--mcp-port", type=int, default=18765)
    run_parser.add_argument("--mcp-path", default="/mcp")

    start_parser = gateway_sub.add_parser("start", help="Start HTTP gateway in background")
    _add_http_args(start_parser)
    _add_runtime_args(start_parser)

    stop_parser = gateway_sub.add_parser("stop", help="Stop the background HTTP gateway")
    _add_runtime_args(stop_parser, include_log=False)
    stop_parser.add_argument("--timeout", type=float, default=10.0, help="Seconds to wait before SIGKILL")

    restart_parser = gateway_sub.add_parser("restart", help="Restart the background HTTP gateway")
    _add_http_args(restart_parser)
    _add_runtime_args(restart_parser)
    restart_parser.add_argument("--timeout", type=float, default=10.0, help="Seconds to wait before SIGKILL")

    status_parser = gateway_sub.add_parser("status", help="Show HTTP gateway runtime status")
    _add_runtime_args(status_parser, include_log=False)

    tools_parser = gateway_sub.add_parser(
        "tools",
        aliases=["list_tools", "list-tools", "ls"],
        help="List tools from the HTTP MCP endpoint",
    )
    _add_http_args(tools_parser)
    _add_runtime_args(tools_parser, include_log=False)
    tools_parser.add_argument(
        "tool_name",
        nargs="?",
        default=None,
        help="Optional full MCP tool name to inspect, for example robot.base_move",
    )
    tools_parser.add_argument(
        "--names-only",
        action="store_true",
        help="Only print tool names, matching the old compact output",
    )
    tools_parser.add_argument(
        "--json",
        action="store_true",
        help="Print tool metadata as JSON",
    )

    test_parser = gateway_sub.add_parser("test", help="Test the HTTP MCP endpoint")
    _add_http_args(test_parser)
    _add_runtime_args(test_parser, include_log=False)

    call_parser = gateway_sub.add_parser("call", help="Call a tool through the HTTP MCP endpoint")
    _add_http_args(call_parser)
    _add_runtime_args(call_parser, include_log=False)
    call_parser.add_argument("tool_name", help="Full MCP tool name, for example robot.base_move")
    call_parser.add_argument(
        "arguments",
        nargs="?",
        default="{}",
        help='Tool arguments as a JSON object, for example \'{"direction":"forward"}\'',
    )

    return parser


def _add_http_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--mcp-host", default="127.0.0.1", help="HTTP bind host / test host")
    parser.add_argument("--mcp-port", type=int, default=18765, help="HTTP bind port / test port")
    parser.add_argument("--mcp-path", default="/mcp", help="HTTP MCP path")


def _add_runtime_args(parser: argparse.ArgumentParser, *, include_log: bool = True) -> None:
    parser.add_argument("--state-dir", default=None, help="Directory for pid/runtime state files")
    if include_log:
        parser.add_argument("--log-file", default=None, help="Log file path for background gateway")


def _runtime_summary(args: argparse.Namespace) -> dict:
    cleanup_stale_state(args.state_dir)
    runtime = read_runtime_state(args.state_dir)
    pid = read_pid(args.state_dir)
    running = is_process_running(pid)
    paths = load_gateway_device_paths()
    return {
        "runtime": runtime,
        "pid": pid,
        "running": running,
        "host": runtime.get("host") or getattr(args, "mcp_host", "127.0.0.1"),
        "port": runtime.get("port") or getattr(args, "mcp_port", 18765),
        "path": runtime.get("path") or getattr(args, "mcp_path", "/mcp"),
        "transport": runtime.get("transport") or "http",
        "log_path": runtime.get("log_path") or str(get_log_path(args.state_dir, getattr(args, "log_file", None))),
        "unix_socket": paths["unix_socket"],
        "tools_snapshot": paths["tools_snapshot"],
    }


def _format_uptime(start_time: float | int | None) -> str:
    if not start_time:
        return "unknown"
    elapsed = max(0, int(time.time() - float(start_time)))
    minutes, seconds = divmod(elapsed, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}h{minutes:02d}m{seconds:02d}s"
    if minutes:
        return f"{minutes}m{seconds:02d}s"
    return f"{seconds}s"


def cmd_gateway_run(args: argparse.Namespace) -> int:
    config = GatewayRunConfig(
        mcp_transport=args.mcp_transport,
        mcp_host=args.mcp_host,
        mcp_port=args.mcp_port,
        mcp_path=args.mcp_path,
    )
    if config.mcp_transport == "http":
        write_runtime_state(
            pid=os.getpid(),
            host=config.mcp_host,
            port=config.mcp_port,
            path=config.mcp_path,
            transport=config.mcp_transport,
            state_dir=os.environ.get(STATE_DIR_ENV),
            log_path=os.environ.get(LOG_PATH_ENV),
        )
    try:
        asyncio.run(run_gateway(config))
    except KeyboardInterrupt:
        # Normal stop for foreground run; avoid asyncio traceback.
        return 130
    finally:
        if config.mcp_transport == "http":
            clear_runtime_state(os.environ.get(STATE_DIR_ENV), only_if_pid=os.getpid())
    return 0


def cmd_gateway_start(args: argparse.Namespace) -> int:
    summary = _runtime_summary(args)
    if summary["running"]:
        print(f"mlink gateway already running (pid={summary['pid']})")
        return 0

    cleanup_stale_state(args.state_dir)
    if summary["unix_socket"]:
        cleanup_stale_socket(summary["unix_socket"])

    state_dir = str(get_state_dir(args.state_dir))
    log_path = get_log_path(args.state_dir, args.log_file)
    log_path.parent.mkdir(parents=True, exist_ok=True)

    cmd = [
        sys.executable,
        "-m",
        "mlink.gateway.cli",
        "gateway",
        "run",
        "--mcp-transport",
        "http",
        "--mcp-host",
        args.mcp_host,
        "--mcp-port",
        str(args.mcp_port),
        "--mcp-path",
        args.mcp_path,
    ]
    env = os.environ.copy()
    env[STATE_DIR_ENV] = state_dir
    env[LOG_PATH_ENV] = str(log_path)

    with open(log_path, "a", encoding="utf-8") as log_file:
        proc = subprocess.Popen(
            cmd,
            stdout=log_file,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            cwd=str(_SCRIPT_DIR),
            env=env,
            start_new_session=True,
        )

    deadline = time.time() + 8.0
    while time.time() < deadline:
        if proc.poll() is not None:
            print(f"mlink gateway failed to start, see log: {log_path}")
            return 1
        if tcp_port_listening(args.mcp_host, args.mcp_port):
            print(f"mlink gateway started (pid={proc.pid})")
            print(f"HTTP endpoint: http://{args.mcp_host}:{args.mcp_port}{args.mcp_path}")
            print(f"Log file: {log_path}")
            return 0
        time.sleep(0.2)

    print(f"mlink gateway start timed out, see log: {log_path}")
    return 1


def cmd_gateway_stop(args: argparse.Namespace) -> int:
    summary = _runtime_summary(args)
    pid = summary["pid"]
    if not summary["running"]:
        if summary["unix_socket"]:
            cleanup_stale_socket(summary["unix_socket"])
        clear_runtime_state(args.state_dir)
        print("mlink gateway is not running")
        return 0

    stopped = terminate_process(pid, timeout_s=args.timeout)
    if summary["unix_socket"]:
        cleanup_stale_socket(summary["unix_socket"])
    if stopped:
        clear_runtime_state(args.state_dir)
        print(f"mlink gateway stopped (pid={pid})")
        return 0

    print(f"failed to stop mlink gateway cleanly (pid={pid})")
    return 1


def cmd_gateway_restart(args: argparse.Namespace) -> int:
    stop_code = cmd_gateway_stop(args)
    if stop_code != 0:
        return stop_code
    return cmd_gateway_start(args)


def cmd_gateway_status(args: argparse.Namespace) -> int:
    summary = _runtime_summary(args)
    status = "running" if summary["running"] else "stopped"
    print(f"Status: {status}")
    print(f"PID: {summary['pid'] or '-'}")
    print(f"Transport: {summary['transport']}")
    print(f"HTTP endpoint: http://{summary['host']}:{summary['port']}{summary['path']}")
    print(f"Log file: {summary['log_path']}")
    print(f"UNIX socket: {summary['unix_socket'] or '-'}")
    print(f"Tools snapshot: {summary['tools_snapshot'] or '-'}")
    start_time = summary["runtime"].get("start_time")
    if start_time:
        print(f"Uptime: {_format_uptime(start_time)}")
    if summary["running"]:
        listening = tcp_port_listening(summary["host"], int(summary["port"]))
        print(f"HTTP listener: {'ready' if listening else 'not ready'}")
    return 0 if summary["running"] else 1


def _mcp_obj_to_jsonable(value: object) -> object:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")  # type: ignore[attr-defined]
    if hasattr(value, "dict"):
        return value.dict()  # type: ignore[attr-defined]
    return value


def _json_dumps(value: object, *, indent: int | None = None) -> str:
    return json.dumps(value, ensure_ascii=False, indent=indent, default=str)


def _normalize_tool_metadata(value: object) -> dict[str, object]:
    raw = _mcp_obj_to_jsonable(value)
    if not isinstance(raw, dict):
        return {
            "name": str(raw),
            "description": "",
            "inputSchema": {"type": "object", "properties": {}},
        }

    tool = dict(raw)
    name = tool.get("name") or tool.get("full_name") or tool.get("fullName") or "<unknown>"
    description = tool.get("description") or ""
    input_schema = (
        tool.get("inputSchema")
        or tool.get("input_schema")
        or tool.get("parameters")
        or {"type": "object", "properties": {}}
    )

    tool["name"] = name
    tool["description"] = description
    tool["inputSchema"] = input_schema
    return tool


async def _probe_http_gateway(host: str, port: int, path: str) -> tuple[int, list[dict]]:
    url = f"http://{host}:{port}{path}"
    async with streamable_http_client(url) as (read_stream, write_stream, _):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            tools = await session.list_tools()
            tool_items = [_normalize_tool_metadata(tool) for tool in tools.tools]
            tool_items.sort(key=lambda item: str(item.get("name", "")))
            return len(tool_items), tool_items


async def _call_http_gateway(host: str, port: int, path: str, tool_name: str, arguments: dict) -> object:
    url = f"http://{host}:{port}{path}"
    async with streamable_http_client(url) as (read_stream, write_stream, _):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            return await session.call_tool(tool_name, arguments)


def _resolve_probe_target(args: argparse.Namespace) -> tuple[str, int, str]:
    summary = _runtime_summary(args)
    return summary["host"], int(summary["port"]), summary["path"]


def cmd_gateway_list_tools(args: argparse.Namespace) -> int:
    host, port, path = _resolve_probe_target(args)
    try:
        discovered_count, tool_items = asyncio.run(
            _probe_http_gateway(host, port, path)
        )
    except Exception as exc:
        print(f"mlink gateway tools failed: {exc}")
        return 1

    if args.tool_name:
        selected_tools = [
            tool for tool in tool_items
            if str(tool.get("name", "")) == args.tool_name
        ]
    else:
        selected_tools = tool_items

    if args.json:
        payload = {
            "endpoint": f"http://{host}:{port}{path}",
            "discovered_tool_count": discovered_count,
            "tool_count": len(selected_tools),
            "tools": selected_tools,
        }
        if args.tool_name:
            payload["queried_tool"] = args.tool_name
        print(_json_dumps(payload, indent=2))
        return 0 if selected_tools or not args.tool_name else 1

    print(f"HTTP MCP endpoint reachable: http://{host}:{port}{path}")
    print(f"Tools discovered: {discovered_count}")
    if not tool_items:
        print("No tools registered yet.")
        return 0

    if args.tool_name and not selected_tools:
        print(f"Tool not found: {args.tool_name}")
        print("Use `mlink gateway tools --names-only` to list available tool names.")
        return 1

    if args.names_only:
        print("Tool names:")
        for tool in selected_tools:
            print(f"  - {tool.get('name', '<unknown>')}")
        return 0

    print("Tools:" if not args.tool_name else "Tool:")
    for tool in selected_tools:
        name = tool.get("name", "<unknown>")
        description = tool.get("description") or ""
        input_schema = tool.get("inputSchema") or {"type": "object", "properties": {}}
        print(f"- {name}")
        if description:
            print(f"  description: {description}")
        print("  inputSchema:")
        print(_indent_json(input_schema, prefix="    "))
    return 0


def cmd_gateway_test(args: argparse.Namespace) -> int:
    host, port, path = _resolve_probe_target(args)
    try:
        tool_count, tool_items = asyncio.run(
            _probe_http_gateway(host, port, path)
        )
    except Exception as exc:
        print(f"mlink gateway test failed: {exc}")
        return 1

    tool_names = [tool.get("name") for tool in tool_items]
    print(f"HTTP MCP endpoint reachable: http://{host}:{port}{path}")
    print(f"Tools discovered: {tool_count}")
    if "robot.base_move" in tool_names:
        print("Health: ready (robot.base_move available)")
    elif tool_names:
        print("Health: partial (MCP reachable, but robot.base_move not found)")
    else:
        print("Health: partial (MCP reachable, but no tools registered yet)")
    return 0


def _indent_json(value: object, *, prefix: str) -> str:
    text = _json_dumps(value, indent=2)
    return "\n".join(prefix + line for line in text.splitlines())


def cmd_gateway_call(args: argparse.Namespace) -> int:
    host, port, path = _resolve_probe_target(args)
    try:
        parsed_args = json.loads(args.arguments)
    except json.JSONDecodeError as exc:
        print(f"invalid arguments JSON: {exc}")
        return 1

    if not isinstance(parsed_args, dict):
        print("invalid arguments JSON: expected an object")
        return 1

    try:
        result = asyncio.run(
            _call_http_gateway(host, port, path, args.tool_name, parsed_args)
        )
    except Exception as exc:
        print(f"mlink gateway call failed: {exc}")
        return 1

    print(f"HTTP MCP endpoint reachable: http://{host}:{port}{path}")
    print(f"Tool called: {args.tool_name}")
    print("Result:")
    print(_json_dumps(_mcp_obj_to_jsonable(result), indent=2))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command != "gateway":
        parser.print_help()
        return 1

    if args.gateway_command == "run":
        return cmd_gateway_run(args)
    if args.gateway_command == "start":
        return cmd_gateway_start(args)
    if args.gateway_command == "stop":
        return cmd_gateway_stop(args)
    if args.gateway_command == "restart":
        return cmd_gateway_restart(args)
    if args.gateway_command == "status":
        return cmd_gateway_status(args)
    if args.gateway_command in ("tools", "list_tools", "list-tools", "ls"):
        return cmd_gateway_list_tools(args)
    if args.gateway_command == "test":
        return cmd_gateway_test(args)
    if args.gateway_command == "call":
        return cmd_gateway_call(args)

    print("Usage: mlink gateway <run|start|stop|restart|status|tools|test|call> [options]")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
