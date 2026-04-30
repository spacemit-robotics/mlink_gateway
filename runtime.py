"""Runtime state helpers for the mlink gateway CLI."""

from __future__ import annotations

import json
import os
import signal
import socket
import time
from pathlib import Path
from typing import Any

from mlink.gateway.config.loader import load_gateway_config

STATE_DIR_ENV = "MLINK_GATEWAY_STATE_DIR"
LOG_PATH_ENV = "MLINK_GATEWAY_LOG_PATH"


def get_state_dir(state_dir: str | None = None) -> Path:
    raw = state_dir or os.environ.get(STATE_DIR_ENV) or "/tmp/mlink-gateway"
    path = Path(raw).expanduser()
    path.mkdir(parents=True, exist_ok=True)
    return path


def get_pid_path(state_dir: str | None = None) -> Path:
    return get_state_dir(state_dir) / "gateway.pid"


def get_runtime_path(state_dir: str | None = None) -> Path:
    return get_state_dir(state_dir) / "runtime.json"


def get_log_path(state_dir: str | None = None, log_path: str | None = None) -> Path:
    raw = log_path or os.environ.get(LOG_PATH_ENV)
    if raw:
        return Path(raw).expanduser()
    return get_state_dir(state_dir) / "gateway.log"


def read_pid(state_dir: str | None = None) -> int | None:
    path = get_pid_path(state_dir)
    if not path.exists():
        return None
    try:
        return int(path.read_text(encoding="utf-8").strip())
    except (TypeError, ValueError):
        return None


def is_process_running(pid: int | None) -> bool:
    if not pid or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def write_runtime_state(
    *,
    pid: int,
    host: str,
    port: int,
    path: str,
    transport: str,
    state_dir: str | None = None,
    log_path: str | None = None,
) -> None:
    pid_path = get_pid_path(state_dir)
    runtime_path = get_runtime_path(state_dir)
    pid_path.write_text(f"{pid}\n", encoding="utf-8")
    payload = {
        "pid": pid,
        "host": host,
        "port": port,
        "path": path,
        "transport": transport,
        "start_time": time.time(),
        "log_path": str(get_log_path(state_dir, log_path)),
    }
    runtime_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def read_runtime_state(state_dir: str | None = None) -> dict[str, Any]:
    path = get_runtime_path(state_dir)
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    return data if isinstance(data, dict) else {}


def clear_runtime_state(state_dir: str | None = None, *, only_if_pid: int | None = None) -> None:
    pid_path = get_pid_path(state_dir)
    runtime_path = get_runtime_path(state_dir)
    if only_if_pid is not None:
        current = read_pid(state_dir)
        if current != only_if_pid:
            return
    for path in (pid_path, runtime_path):
        try:
            path.unlink()
        except FileNotFoundError:
            pass


def cleanup_stale_state(state_dir: str | None = None) -> None:
    pid = read_pid(state_dir)
    if pid is not None and not is_process_running(pid):
        clear_runtime_state(state_dir)


def terminate_process(pid: int, timeout_s: float = 10.0) -> bool:
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        return True
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        if not is_process_running(pid):
            return True
        time.sleep(0.2)
    try:
        os.kill(pid, signal.SIGKILL)
    except ProcessLookupError:
        return True
    return not is_process_running(pid)


def load_gateway_device_paths() -> dict[str, str]:
    config_path = Path(__file__).resolve().parent / "config" / "gateway.yaml"
    cfg = load_gateway_config(config_path)
    devices_cfg = cfg.get("devices", {})
    snapshot_cfg = devices_cfg.get("tools_snapshot") or {}
    return {
        "unix_socket": str(devices_cfg.get("unix_listen_path") or ""),
        "tools_snapshot": str(snapshot_cfg.get("path") or ""),
    }


def cleanup_stale_socket(socket_path: str) -> bool:
    if not socket_path:
        return False
    path = Path(socket_path)
    if not path.exists():
        return False
    try:
        path.unlink()
    except OSError:
        return False
    return True


def tcp_port_listening(host: str, port: int, timeout_s: float = 0.5) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout_s):
            return True
    except OSError:
        return False


__all__ = [
    "LOG_PATH_ENV",
    "STATE_DIR_ENV",
    "cleanup_stale_socket",
    "cleanup_stale_state",
    "clear_runtime_state",
    "get_log_path",
    "get_pid_path",
    "get_runtime_path",
    "get_state_dir",
    "is_process_running",
    "load_gateway_device_paths",
    "read_pid",
    "read_runtime_state",
    "tcp_port_listening",
    "terminate_process",
    "write_runtime_state",
]
