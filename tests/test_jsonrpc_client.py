# Copyright (C) 2026 SpacemiT (Hangzhou) Technology Co. Ltd.
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import json

from mlink.gateway.protocol.jsonrpc_mcp_client import MlinkMcpJsonRpcClient


def test_successful_call_and_ignored_messages() -> None:
    sent: list[dict] = []
    client: MlinkMcpJsonRpcClient

    def send_text(text: str) -> None:
        req = json.loads(text)
        sent.append(req)
        client.handle_text(json.dumps({"jsonrpc": "2.0", "method": "notify"}))
        client.handle_text(json.dumps({"jsonrpc": "2.0", "id": 999, "result": {"ignored": True}}))
        client.handle_text(json.dumps({"jsonrpc": "2.0", "id": req["id"], "result": {"ok": True}}))

    client = MlinkMcpJsonRpcClient(send_text)
    response = client.initialize()

    assert response["result"] == {"ok": True}
    assert sent[0]["id"] == 1
    assert sent[0]["method"] == "initialize"


def test_timeout_cleans_pending_call() -> None:
    client = MlinkMcpJsonRpcClient(lambda text: None)

    try:
        client._call("never-responds", timeout=0.01)  # type: ignore[attr-defined]
    except TimeoutError:
        pass
    else:
        raise AssertionError("timeout should raise TimeoutError")

    assert client._pending == {}  # type: ignore[attr-defined]


def test_tools_list_and_call_request_shapes() -> None:
    sent: list[dict] = []
    client: MlinkMcpJsonRpcClient

    def send_text(text: str) -> None:
        req = json.loads(text)
        sent.append(req)
        client.handle_text(json.dumps({"jsonrpc": "2.0", "id": req["id"], "result": {}}))

    client = MlinkMcpJsonRpcClient(send_text)
    client.tools_list(cursor="next", with_user_tools=True)
    client.tools_call("robot.stop_motion", {"force": True})

    assert sent[0]["method"] == "tools/list"
    assert sent[0]["params"] == {"cursor": "next", "withUserTools": True}
    assert sent[1]["method"] == "tools/call"
    assert sent[1]["params"] == {"name": "robot.stop_motion", "arguments": {"force": True}}


def main() -> None:
    test_successful_call_and_ignored_messages()
    test_timeout_cleans_pending_call()
    test_tools_list_and_call_request_shapes()
    print("JSONRPC CLIENT TESTS PASSED.")


if __name__ == "__main__":
    main()
