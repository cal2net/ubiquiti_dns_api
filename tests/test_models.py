from unifi_dns import ARecord, eq
from unifi_dns.filters import and_, combine


def test_a_record_payload_uses_api_aliases() -> None:
    record = ARecord(domain="nas.home", ipv4_address="192.168.1.10", ttl_seconds=300)
    assert record.to_payload() == {
        "enabled": True,
        "type": "A_RECORD",
        "domain": "nas.home",
        "ipv4Address": "192.168.1.10",
        "ttlSeconds": 300,
    }


def test_a_record_parses_camel_case_response() -> None:
    record = ARecord.model_validate(
        {
            "id": "11111111-1111-1111-1111-111111111111",
            "type": "A_RECORD",
            "enabled": True,
            "domain": "nas.home",
            "ipv4Address": "192.168.1.10",
            "ttlSeconds": 14400,
            "metadata": {"origin": "USER_DEFINED"},
        }
    )
    assert record.ipv4_address == "192.168.1.10"
    assert record.metadata is not None
    assert record.metadata.origin == "USER_DEFINED"


def test_filter_helpers() -> None:
    assert eq("domain", "nas.home") == "domain.eq('nas.home')"
    assert and_(eq("type", "A_RECORD"), eq("enabled", True)) == (
        "and(type.eq('A_RECORD'),enabled.eq(true))"
    )
    assert combine(None, eq("type", "A_RECORD")) == "type.eq('A_RECORD')"
