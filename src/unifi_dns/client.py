from __future__ import annotations

import os
from collections.abc import Iterator
from typing import Any

import httpx
from dotenv import load_dotenv
from pydantic import TypeAdapter

from unifi_dns.exceptions import ConfigurationError, UniFiError
from unifi_dns.filters import combine, eq
from unifi_dns.models import (
    AaaaRecord,
    ApplicationInfo,
    ARecord,
    CnameRecord,
    DnsRecord,
    DnsRecordPage,
    ForwardDomain,
    MxRecord,
    Site,
    SitePage,
    SrvRecord,
    TxtRecord,
)

_RECORD_ADAPTER = TypeAdapter(DnsRecord)

LOCAL_BASE = "https://{host}/proxy/network/integration"
CLOUD_BASE = "https://api.ui.com/v1/connector/consoles/{console_id}/proxy/network/integration"
DEFAULT_PAGE_LIMIT = 25
MAX_PAGE_LIMIT = 200


def _env(*names: str) -> str | None:
    for name in names:
        value = os.environ.get(name)
        if value:
            return value
    return None


def _as_bool(value: str | None, default: bool) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


class Client:
    """UniFi Network client focused on DNS policies."""

    def __init__(
        self,
        base_url: str,
        api_key: str,
        *,
        site_id: str | None = None,
        verify: bool | str = True,
        timeout: float = 30.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        if not api_key:
            raise ConfigurationError("An API key is required. Generate one at unifi.ui.com.")
        self.site_id = site_id
        self._http = httpx.Client(
            base_url=base_url.rstrip("/"),
            headers={
                "X-API-KEY": api_key,
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
            verify=verify,
            timeout=timeout,
            transport=transport,
        )
        self.sites = SitesAPI(self)
        self.dns = DnsAPI(self)

    @classmethod
    def local(
        cls,
        host: str,
        api_key: str,
        *,
        site_id: str | None = None,
        verify: bool | str = False,
        timeout: float = 30.0,
        transport: httpx.BaseTransport | None = None,
    ) -> Client:
        return cls(
            LOCAL_BASE.format(host=host),
            api_key,
            site_id=site_id,
            verify=verify,
            timeout=timeout,
            transport=transport,
        )

    @classmethod
    def cloud(
        cls,
        console_id: str,
        api_key: str,
        *,
        site_id: str | None = None,
        timeout: float = 30.0,
        transport: httpx.BaseTransport | None = None,
    ) -> Client:
        return cls(
            CLOUD_BASE.format(console_id=console_id),
            api_key,
            site_id=site_id,
            verify=True,
            timeout=timeout,
            transport=transport,
        )

    @classmethod
    def from_env(cls, *, dotenv: bool = True, transport: httpx.BaseTransport | None = None) -> Client:
        if dotenv:
            load_dotenv()
        api_key = _env("UNIFI_API_KEY", "ubiquiti_api_key")
        if not api_key:
            raise ConfigurationError(
                "Set UNIFI_API_KEY (or ubiquiti_api_key) in the environment or .env."
            )
        site_id = _env("UNIFI_SITE_ID")
        host = _env("UNIFI_CONSOLE_HOST", "UNIFI_HOST")
        console_id = _env("UNIFI_CONSOLE_ID")
        if host and console_id:
            raise ConfigurationError("Set either UNIFI_CONSOLE_HOST or UNIFI_CONSOLE_ID, not both.")
        if console_id:
            return cls.cloud(console_id, api_key, site_id=site_id, transport=transport)
        if host:
            verify = _as_bool(_env("UNIFI_VERIFY_SSL"), default=False)
            return cls.local(host, api_key, site_id=site_id, verify=verify, transport=transport)
        raise ConfigurationError("Set UNIFI_CONSOLE_HOST for a local console or UNIFI_CONSOLE_ID for cloud.")

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> Client:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def info(self) -> ApplicationInfo:
        return ApplicationInfo.model_validate(self.request("GET", "/v1/info"))

    def request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: Any = None,
    ) -> Any:
        response = self._http.request(method, path, params=params, json=json)
        payload: Any = None
        if response.content:
            try:
                payload = response.json()
            except ValueError:
                payload = {"raw": response.text}
        if response.is_error:
            raise UniFiError.from_response(
                response.status_code,
                payload,
                fallback=f"{method} {path} failed with HTTP {response.status_code}",
            )
        return payload

    def _require_site(self, site_id: str | None) -> str:
        resolved = site_id or self.site_id
        if not resolved:
            raise ConfigurationError(
                "Pass site_id or set Client.site_id / UNIFI_SITE_ID. Use client.sites.list() to find it."
            )
        return resolved


class SitesAPI:
    def __init__(self, client: Client) -> None:
        self._client = client

    def list(
        self,
        *,
        offset: int = 0,
        limit: int = DEFAULT_PAGE_LIMIT,
        filter: str | None = None,
    ) -> SitePage:
        params: dict[str, Any] = {"offset": offset, "limit": min(limit, MAX_PAGE_LIMIT)}
        if filter:
            params["filter"] = filter
        return SitePage.model_validate(self._client.request("GET", "/v1/sites", params=params))

    def list_all(self, *, filter: str | None = None) -> list[Site]:
        return list(self.iter_all(filter=filter))

    def iter_all(self, *, filter: str | None = None) -> Iterator[Site]:
        offset = 0
        while True:
            page = self.list(offset=offset, limit=MAX_PAGE_LIMIT, filter=filter)
            yield from page.data
            offset += page.count
            if offset >= page.total_count or page.count == 0:
                return

    def get_by_name(self, name: str) -> Site:
        page = self.list(filter=eq("name", name), limit=1)
        if not page.data:
            raise UniFiError(f"No site named {name!r}", status_code=404)
        return page.data[0]


class DnsAPI:
    def __init__(self, client: Client) -> None:
        self._client = client

    def list(
        self,
        site_id: str | None = None,
        *,
        offset: int = 0,
        limit: int = DEFAULT_PAGE_LIMIT,
        filter: str | None = None,
        record_type: str | None = None,
        domain: str | None = None,
        enabled: bool | None = None,
    ) -> DnsRecordPage:
        site = self._client._require_site(site_id)
        built = combine(
            filter,
            eq("type", record_type) if record_type else None,
            eq("domain", domain) if domain else None,
            eq("enabled", enabled) if enabled is not None else None,
        )
        params: dict[str, Any] = {"offset": offset, "limit": min(limit, MAX_PAGE_LIMIT)}
        if built:
            params["filter"] = built
        return DnsRecordPage.model_validate(
            self._client.request("GET", f"/v1/sites/{site}/dns/policies", params=params)
        )

    def list_all(
        self,
        site_id: str | None = None,
        *,
        filter: str | None = None,
        record_type: str | None = None,
        domain: str | None = None,
        enabled: bool | None = None,
    ) -> list[DnsRecord]:
        return list(
            self.iter_all(
                site_id,
                filter=filter,
                record_type=record_type,
                domain=domain,
                enabled=enabled,
            )
        )

    def iter_all(
        self,
        site_id: str | None = None,
        *,
        filter: str | None = None,
        record_type: str | None = None,
        domain: str | None = None,
        enabled: bool | None = None,
    ) -> Iterator[DnsRecord]:
        offset = 0
        while True:
            page = self.list(
                site_id,
                offset=offset,
                limit=MAX_PAGE_LIMIT,
                filter=filter,
                record_type=record_type,
                domain=domain,
                enabled=enabled,
            )
            yield from page.data
            offset += page.count
            if offset >= page.total_count or page.count == 0:
                return

    def get(self, policy_id: str, site_id: str | None = None) -> DnsRecord:
        site = self._client._require_site(site_id)
        payload = self._client.request("GET", f"/v1/sites/{site}/dns/policies/{policy_id}")
        return _RECORD_ADAPTER.validate_python(payload)

    def create(self, record: DnsRecord, site_id: str | None = None) -> DnsRecord:
        site = self._client._require_site(site_id)
        payload = self._client.request(
            "POST",
            f"/v1/sites/{site}/dns/policies",
            json=record.to_payload(),
        )
        return _RECORD_ADAPTER.validate_python(payload)

    def update(self, policy_id: str, record: DnsRecord, site_id: str | None = None) -> DnsRecord:
        site = self._client._require_site(site_id)
        payload = self._client.request(
            "PUT",
            f"/v1/sites/{site}/dns/policies/{policy_id}",
            json=record.to_payload(),
        )
        return _RECORD_ADAPTER.validate_python(payload)

    def delete(self, policy_id: str, site_id: str | None = None) -> None:
        site = self._client._require_site(site_id)
        self._client.request("DELETE", f"/v1/sites/{site}/dns/policies/{policy_id}")

    def create_a(
        self,
        domain: str,
        ipv4_address: str,
        *,
        site_id: str | None = None,
        ttl_seconds: int = 14400,
        enabled: bool = True,
    ) -> ARecord:
        created = self.create(
            ARecord(domain=domain, ipv4_address=ipv4_address, ttl_seconds=ttl_seconds, enabled=enabled),
            site_id,
        )
        assert isinstance(created, ARecord)
        return created

    def create_aaaa(
        self,
        domain: str,
        ipv6_address: str,
        *,
        site_id: str | None = None,
        ttl_seconds: int = 14400,
        enabled: bool = True,
    ) -> AaaaRecord:
        created = self.create(
            AaaaRecord(domain=domain, ipv6_address=ipv6_address, ttl_seconds=ttl_seconds, enabled=enabled),
            site_id,
        )
        assert isinstance(created, AaaaRecord)
        return created

    def create_cname(
        self,
        domain: str,
        target_domain: str,
        *,
        site_id: str | None = None,
        ttl_seconds: int = 14400,
        enabled: bool = True,
    ) -> CnameRecord:
        created = self.create(
            CnameRecord(
                domain=domain,
                target_domain=target_domain,
                ttl_seconds=ttl_seconds,
                enabled=enabled,
            ),
            site_id,
        )
        assert isinstance(created, CnameRecord)
        return created

    def create_mx(
        self,
        domain: str,
        mail_server_domain: str,
        priority: int,
        *,
        site_id: str | None = None,
        enabled: bool = True,
    ) -> MxRecord:
        created = self.create(
            MxRecord(
                domain=domain,
                mail_server_domain=mail_server_domain,
                priority=priority,
                enabled=enabled,
            ),
            site_id,
        )
        assert isinstance(created, MxRecord)
        return created

    def create_srv(
        self,
        domain: str,
        *,
        service: str,
        protocol: str,
        server_domain: str,
        port: int,
        priority: int,
        weight: int,
        site_id: str | None = None,
        enabled: bool = True,
    ) -> SrvRecord:
        created = self.create(
            SrvRecord(
                domain=domain,
                service=service,
                protocol=protocol,
                server_domain=server_domain,
                port=port,
                priority=priority,
                weight=weight,
                enabled=enabled,
            ),
            site_id,
        )
        assert isinstance(created, SrvRecord)
        return created

    def create_txt(
        self,
        domain: str,
        text: str,
        *,
        site_id: str | None = None,
        enabled: bool = True,
    ) -> TxtRecord:
        created = self.create(TxtRecord(domain=domain, text=text, enabled=enabled), site_id)
        assert isinstance(created, TxtRecord)
        return created

    def create_forward(
        self,
        domain: str,
        ip_address: str,
        *,
        site_id: str | None = None,
        enabled: bool = True,
    ) -> ForwardDomain:
        created = self.create(
            ForwardDomain(domain=domain, ip_address=ip_address, enabled=enabled),
            site_id,
        )
        assert isinstance(created, ForwardDomain)
        return created

    def upsert_a(
        self,
        domain: str,
        ipv4_address: str,
        *,
        site_id: str | None = None,
        ttl_seconds: int = 14400,
        enabled: bool = True,
    ) -> ARecord:
        existing = self._find(domain, "A_RECORD", site_id)
        record = ARecord(domain=domain, ipv4_address=ipv4_address, ttl_seconds=ttl_seconds, enabled=enabled)
        if existing:
            updated = self.update(existing.id, record, site_id)  # type: ignore[arg-type]
            assert isinstance(updated, ARecord)
            return updated
        return self.create_a(
            domain,
            ipv4_address,
            site_id=site_id,
            ttl_seconds=ttl_seconds,
            enabled=enabled,
        )

    def upsert_aaaa(
        self,
        domain: str,
        ipv6_address: str,
        *,
        site_id: str | None = None,
        ttl_seconds: int = 14400,
        enabled: bool = True,
    ) -> AaaaRecord:
        existing = self._find(domain, "AAAA_RECORD", site_id)
        record = AaaaRecord(domain=domain, ipv6_address=ipv6_address, ttl_seconds=ttl_seconds, enabled=enabled)
        if existing:
            updated = self.update(existing.id, record, site_id)  # type: ignore[arg-type]
            assert isinstance(updated, AaaaRecord)
            return updated
        return self.create_aaaa(
            domain,
            ipv6_address,
            site_id=site_id,
            ttl_seconds=ttl_seconds,
            enabled=enabled,
        )

    def upsert_cname(
        self,
        domain: str,
        target_domain: str,
        *,
        site_id: str | None = None,
        ttl_seconds: int = 14400,
        enabled: bool = True,
    ) -> CnameRecord:
        existing = self._find(domain, "CNAME_RECORD", site_id)
        record = CnameRecord(
            domain=domain,
            target_domain=target_domain,
            ttl_seconds=ttl_seconds,
            enabled=enabled,
        )
        if existing:
            updated = self.update(existing.id, record, site_id)  # type: ignore[arg-type]
            assert isinstance(updated, CnameRecord)
            return updated
        return self.create_cname(
            domain,
            target_domain,
            site_id=site_id,
            ttl_seconds=ttl_seconds,
            enabled=enabled,
        )

    def upsert_txt(
        self,
        domain: str,
        text: str,
        *,
        site_id: str | None = None,
        enabled: bool = True,
    ) -> TxtRecord:
        existing = self._find(domain, "TXT_RECORD", site_id)
        record = TxtRecord(domain=domain, text=text, enabled=enabled)
        if existing:
            updated = self.update(existing.id, record, site_id)  # type: ignore[arg-type]
            assert isinstance(updated, TxtRecord)
            return updated
        return self.create_txt(domain, text, site_id=site_id, enabled=enabled)

    def _find(self, domain: str, record_type: str, site_id: str | None) -> DnsRecord | None:
        page = self.list(site_id, limit=1, record_type=record_type, domain=domain)
        if not page.data:
            return None
        return page.data[0]
