# Copyright (C) 2026 SpacemiT (Hangzhou) Technology Co. Ltd.
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import tempfile
import socket
from pathlib import Path

from mlink.gateway.transport.manager import TransportManager, build_transport_configs


def test_legacy_config_builds_tcp_and_unix() -> None:
    configs = build_transport_configs(
        {
            "tcp_listen_host": "127.0.0.1",
            "tcp_listen_port": 0,
            "unix_listen_path": "/tmp/mlink-test.sock",
        }
    )
    assert [(cfg.kind, cfg.host, cfg.port, cfg.path) for cfg in configs] == [
        ("tcp", "127.0.0.1", 0, None),
        ("unix", None, None, "/tmp/mlink-test.sock"),
    ]


def test_explicit_config_preserves_supported_and_unknown_entries() -> None:
    configs = build_transport_configs(
        {
            "transports": [
                {"kind": "tcp", "host": "127.0.0.1", "port": 0},
                {"kind": "unix", "path": "/tmp/mlink-explicit.sock"},
                {"kind": "unknown"},
            ]
        }
    )
    assert [cfg.kind for cfg in configs] == ["tcp", "unix", "unknown"]


def test_transport_manager_start_close() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        unix_path = str(Path(tmpdir) / "mlink.sock")
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        configs = build_transport_configs(
            {
                "transports": [
                    {"kind": "tcp", "host": "127.0.0.1", "port": port},
                    {"kind": "unix", "path": unix_path},
                    {"kind": "unknown"},
                ]
            }
        )
        manager = TransportManager(configs=configs, on_connection=lambda conn: None)
        manager.start()
        manager.close()


def main() -> None:
    test_legacy_config_builds_tcp_and_unix()
    test_explicit_config_preserves_supported_and_unknown_entries()
    test_transport_manager_start_close()
    print("TRANSPORT CONFIG TESTS PASSED.")


if __name__ == "__main__":
    main()
