from __future__ import annotations

from typing import Annotated, Any, Literal, Union

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

DnsRecordType = Literal[
    "A_RECORD",
    "AAAA_RECORD",
    "CNAME_RECORD",
    "MX_RECORD",
    "SRV_RECORD",
    "TXT_RECORD",
    "FORWARD_DOMAIN",
]


class CamelModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        extra="allow",
    )


class EntityMetadata(CamelModel):
    origin: str


class ApplicationInfo(CamelModel):
    application_version: str


class Site(CamelModel):
    id: str
    name: str
    internal_reference: str


class Page(CamelModel):
    count: int
    limit: int
    offset: int
    total_count: int
    data: list[Any]


class DnsRecordBase(CamelModel):
    enabled: bool = True
    domain: str = Field(min_length=1, max_length=127)
    id: str | None = None
    metadata: EntityMetadata | None = None

    def to_payload(self) -> dict[str, Any]:
        return self.model_dump(
            by_alias=True,
            exclude_none=True,
            exclude={"id", "metadata"},
        )


class ARecord(DnsRecordBase):
    type: Literal["A_RECORD"] = "A_RECORD"
    ipv4_address: str
    ttl_seconds: int = Field(default=14400, ge=0, le=86400)


class AaaaRecord(DnsRecordBase):
    type: Literal["AAAA_RECORD"] = "AAAA_RECORD"
    ipv6_address: str
    ttl_seconds: int = Field(default=14400, ge=0, le=86400)


class CnameRecord(DnsRecordBase):
    type: Literal["CNAME_RECORD"] = "CNAME_RECORD"
    target_domain: str = Field(min_length=1, max_length=127)
    ttl_seconds: int = Field(default=14400, ge=0, le=604800)


class MxRecord(DnsRecordBase):
    type: Literal["MX_RECORD"] = "MX_RECORD"
    mail_server_domain: str = Field(min_length=1, max_length=127)
    priority: int = Field(ge=0, le=65535)


class SrvRecord(DnsRecordBase):
    type: Literal["SRV_RECORD"] = "SRV_RECORD"
    service: str
    protocol: str
    server_domain: str = Field(min_length=1, max_length=127)
    port: int = Field(ge=0, le=65535)
    priority: int = Field(ge=0, le=65535)
    weight: int = Field(ge=0, le=65535)


class TxtRecord(DnsRecordBase):
    type: Literal["TXT_RECORD"] = "TXT_RECORD"
    text: str = Field(min_length=1, max_length=1024)


class ForwardDomain(DnsRecordBase):
    type: Literal["FORWARD_DOMAIN"] = "FORWARD_DOMAIN"
    ip_address: str


DnsRecord = Annotated[
    Union[ARecord, AaaaRecord, CnameRecord, MxRecord, SrvRecord, TxtRecord, ForwardDomain],
    Field(discriminator="type"),
]


class DnsRecordPage(CamelModel):
    count: int
    limit: int
    offset: int
    total_count: int
    data: list[DnsRecord]


class SitePage(CamelModel):
    count: int
    limit: int
    offset: int
    total_count: int
    data: list[Site]
