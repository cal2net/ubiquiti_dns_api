from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from unifi_dns import ARecord, Client, ConfigurationError, UniFiError

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


def _page(data: list[dict[str, Any]], *, total: int | None = None) -> dict[str, Any]:
    return {
        "count": len(data),
        "limit": 25,
        "offset": 0,
        "totalCount": total if total is not None else len(data),
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


def _client(router: Router, **kwargs: Any) -> Client:
    return Client.local(
        "192.168.0.1",
        "test-key",
        site_id=SITE_ID,
        transport=httpx.MockTransport(router),
        **kwargs,
    )


def test_local_and_cloud_base_urls() -> None:
    local = Client.local("192.168.0.1", "key")
    assert "192.168.0.1/proxy/network/integration" in str(local._http.base_url)
    cloud = Client.cloud("console-1", "key")
    assert "consoles/console-1/proxy/network/integration" in str(cloud._http.base_url)
    local.close()
    cloud.close()


def test_info_and_list_sites() -> None:
    router = Router()
    router.add("GET", "/v1/info", {"applicationVersion": "10.4.57"})
    router.add(
        "GET",
        "/v1/sites",
        _page([{"id": SITE_ID, "name": "Default", "internalReference": "default"}]),
    )
    with _client(router) as client:
        assert client.info().application_version == "10.4.57"
        sites = client.sites.list()
        assert sites.data[0].name == "Default"
    assert router.calls[0].headers["X-API-KEY"] == "test-key"


def test_create_a_sends_camel_case_body() -> None:
    router = Router()
    router.add("POST", f"/v1/sites/{SITE_ID}/dns/policies", _a_record_body(), status=201)
    with _client(router) as client:
        record = client.dns.create_a("nas.home", "192.168.1.10", ttl_seconds=300)
    assert isinstance(record, ARecord)
    assert record.id == POLICY_ID
    body = json.loads(router.calls[0].content)
    assert body["ipv4Address"] == "192.168.1.10"
    assert body["ttlSeconds"] == 300
    assert "id" not in body


def test_upsert_a_updates_when_domain_exists() -> None:
    router = Router()
    router.add("GET", f"/v1/sites/{SITE_ID}/dns/policies", _page([_a_record_body()]))
    router.add(
        "PUT",
        f"/v1/sites/{SITE_ID}/dns/policies/{POLICY_ID}",
        _a_record_body(ipv4Address="192.168.1.11"),
    )
    with _client(router) as client:
        record = client.dns.upsert_a("nas.home", "192.168.1.11")
    assert record.ipv4_address == "192.168.1.11"
    assert router.calls[0].url.params["filter"] == "and(type.eq('A_RECORD'),domain.eq('nas.home'))"
    assert router.calls[1].method == "PUT"


def test_upsert_a_creates_when_missing() -> None:
    router = Router()
    router.add("GET", f"/v1/sites/{SITE_ID}/dns/policies", _page([]))
    router.add("POST", f"/v1/sites/{SITE_ID}/dns/policies", _a_record_body(), status=201)
    with _client(router) as client:
        record = client.dns.upsert_a("nas.home", "192.168.1.10")
    assert record.domain == "nas.home"
    assert router.calls[1].method == "POST"


def test_get_delete_and_error_payload() -> None:
    router = Router()
    router.add("GET", f"/v1/sites/{SITE_ID}/dns/policies/{POLICY_ID}", _a_record_body())
    router.add("DELETE", f"/v1/sites/{SITE_ID}/dns/policies/{POLICY_ID}", None)
    router.add(
        "GET",
        "/v1/info",
        {
            "code": "api.authentication.missing-credentials",
            "message": "Missing credentials",
            "statusCode": 401,
            "statusName": "UNAUTHORIZED",
        },
        status=401,
    )
    with _client(router) as client:
        assert client.dns.get(POLICY_ID).domain == "nas.home"
        client.dns.delete(POLICY_ID)
        with pytest.raises(UniFiError) as exc:
            client.info()
    assert exc.value.code == "api.authentication.missing-credentials"
    assert exc.value.status_code == 401


def test_from_env_local(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("UNIFI_API_KEY", "env-key")
    monkeypatch.setenv("UNIFI_CONSOLE_HOST", "10.0.0.1")
    monkeypatch.setenv("UNIFI_SITE_ID", SITE_ID)
    monkeypatch.delenv("ubiquiti_api_key", raising=False)
    monkeypatch.delenv("UNIFI_CONSOLE_ID", raising=False)
    client = Client.from_env(dotenv=False)
    assert str(client._http.base_url).startswith("https://10.0.0.1/")
    assert client.site_id == SITE_ID
    client.close()


def test_from_env_requires_target(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("UNIFI_API_KEY", "env-key")
    monkeypatch.delenv("UNIFI_CONSOLE_HOST", raising=False)
    monkeypatch.delenv("UNIFI_HOST", raising=False)
    monkeypatch.delenv("UNIFI_CONSOLE_ID", raising=False)
    monkeypatch.delenv("ubiquiti_api_key", raising=False)
    with pytest.raises(ConfigurationError):
        Client.from_env(dotenv=False)
