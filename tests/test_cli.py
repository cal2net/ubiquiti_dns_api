from __future__ import annotations

import io
from typing import Any

import httpx

import pytest

from unifi_dns.cli import App, format_record, main
from unifi_dns.client import Client
from unifi_dns.models import ARecord

SITE_ID = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
POLICY_ID = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"


def _a_record_body(**overrides: Any) -> dict[str, Any]:
    body = {
        "id": POLICY_ID,
        "type": "A_RECORD",
        "enabled": True,
        "domain": "nas.home",
        "ipv4Address": "192.168.1.10",
        "ttlSeconds": 14400,
        "metadata": {"origin": "USER_DEFINED"},
    }
    body.update(overrides)
    return body


def _page(data: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "count": len(data),
        "limit": 200,
        "offset": 0,
        "totalCount": len(data),
        "data": data,
    }


class Router:
    def __init__(self) -> None:
        self.calls: list[httpx.Request] = []
        self.routes: dict[tuple[str, str], Any] = {}

    def add(self, method: str, path: str, body: Any, status: int = 200) -> None:
        self.routes[(method.upper(), path)] = (status, body)

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(request)
        path = request.url.path
        if "/integration" in path:
            path = path.split("/integration", 1)[1] or "/"
        key = (request.method, path)
        if key not in self.routes:
            return httpx.Response(404, json={"message": f"unmocked {key}", "statusCode": 404})
        status, body = self.routes[key]
        if body is None:
            return httpx.Response(status)
        return httpx.Response(status, json=body)


def _client(router: Router) -> Client:
    return Client.local(
        "192.168.0.1",
        "test-key",
        transport=httpx.MockTransport(router),
    )


def _run(router: Router, lines: list[str]) -> tuple[int, str]:
    stdin = io.StringIO("\n".join(lines) + "\n")
    stdout = io.StringIO()
    with _client(router) as client:
        code = App(client, stdin=stdin, stdout=stdout).run()
    return code, stdout.getvalue()


def _connected_router() -> Router:
    router = Router()
    router.add("GET", "/v1/info", {"applicationVersion": "10.4.57"})
    router.add(
        "GET",
        "/v1/sites",
        _page([{"id": SITE_ID, "name": "Default", "internalReference": "default"}]),
    )
    return router


def test_format_record() -> None:
    record = ARecord.model_validate(_a_record_body())
    text = format_record(record)
    assert "A_RECORD" in text
    assert "nas.home" in text
    assert "192.168.1.10" in text


def test_quit_from_menu() -> None:
    code, output = _run(_connected_router(), ["q"])
    assert code == 0
    assert "UniFi Network 10.4.57" in output
    assert "Using site Default" in output
    assert "Goodbye." in output


def test_show_info_and_list_records() -> None:
    router = _connected_router()
    router.add("GET", f"/v1/sites/{SITE_ID}/dns/policies", _page([_a_record_body()]))
    code, output = _run(router, ["1", "4", "", "q"])
    assert code == 0
    assert "Application version: 10.4.57" in output
    assert "nas.home" in output
    assert "192.168.1.10" in output


def test_select_site_then_show_record_details() -> None:
    router = Router()
    router.add("GET", "/v1/info", {"applicationVersion": "10.4.57"})
    router.add(
        "GET",
        "/v1/sites",
        _page(
            [
                {"id": SITE_ID, "name": "Default", "internalReference": "default"},
                {"id": "cccccccc-cccc-cccc-cccc-cccccccccccc", "name": "Lab", "internalReference": "lab"},
            ]
        ),
    )
    router.add("GET", f"/v1/sites/{SITE_ID}/dns/policies/{POLICY_ID}", _a_record_body())
    code, output = _run(router, ["3", "1", "5", POLICY_ID, "q"])
    assert code == 0
    assert "Selected Default." in output
    assert "ipv4_address: 192.168.1.10" in output


def test_create_a_record() -> None:
    router = _connected_router()
    router.add(
        "POST",
        f"/v1/sites/{SITE_ID}/dns/policies",
        _a_record_body(domain="printer.home", ipv4Address="192.168.1.20"),
        status=201,
    )
    code, output = _run(
        router,
        ["6", "1", "printer.home", "192.168.1.20", "", "", "y", "q"],
    )
    assert code == 0
    assert "Created" in output
    assert "printer.home" in output
    post = next(call for call in router.calls if call.method == "POST")
    assert b"printer.home" in post.content
    assert b"192.168.1.20" in post.content


def test_main_help() -> None:
    with pytest.raises(SystemExit) as exc:
        main(["--help"])
    assert exc.value.code == 0
