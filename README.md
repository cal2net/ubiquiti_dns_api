# unifi-dns

Python client for [UniFi Network](https://developer.ui.com/network/v10.4.57) DNS policies. A DNS policy is a local resolver entry: A, AAAA, CNAME, MX, SRV, TXT, or a domain-forward.

Generate an API key at [unifi.ui.com](https://unifi.ui.com).

## Install

```bash
python -m pip install -e ".[dev]"
```

From another project:

```bash
pip install "unifi-dns @ git+https://github.com/cal2net/ubiquiti_dns_api.git"
```

## Configure

Copy `.env.example` and set either a local console host or a cloud console id:

```bash
UNIFI_API_KEY=...
UNIFI_CONSOLE_HOST=192.168.0.1
UNIFI_VERIFY_SSL=false
```

`ubiquiti_api_key` is also accepted. Optional: `UNIFI_SITE_ID`, or `UNIFI_CONSOLE_ID` instead of a local host.

## Python API

### Connect

`Client.from_env()` reads the variables above (and `.env` if present). You can also pass host and key explicitly.

```python
from unifi_dns import Client

# From UNIFI_API_KEY + UNIFI_CONSOLE_HOST (or UNIFI_CONSOLE_ID)
with Client.from_env() as client:
    print(client.info().application_version)

# Local console
client = Client.local("192.168.0.1", api_key="...", verify=False)

# Site Manager cloud connector
client = Client.cloud("your-console-id", api_key="...")
```

Most DNS calls need a site id. Resolve it once and reuse it:

```python
with Client.from_env() as client:
    site = client.sites.get_by_name("Default")
    client.site_id = site.id
    # or pass site_id=site.id on each dns call
```

`client.sites.list()` returns one page; `client.sites.list_all()` walks every page.

### List and filter records

```python
from unifi_dns import Client, ARecord, and_, eq, like

with Client.from_env() as client:
    site = client.sites.get_by_name("Default")
    client.site_id = site.id

    for record in client.dns.list_all(record_type="A_RECORD"):
        assert isinstance(record, ARecord)
        print(record.domain, record.ipv4_address)

    page = client.dns.list(limit=25, domain="nas.home")
    print(page.total_count, page.data)

    matches = client.dns.list_all(
        filter=and_(eq("type", "CNAME_RECORD"), like("domain", "*home"))
    )
```

`record_type`, `domain`, and `enabled` are convenience filters. For anything else, pass a UniFi filter string (`type.eq('A_RECORD')`) or build one with `eq`, `ne`, `like`, `in_`, `not_in`, `and_`, and `or_`.

### Create records

Typed helpers POST a new policy and return the created record:

```python
from unifi_dns import Client

with Client.from_env() as client:
    client.site_id = client.sites.get_by_name("Default").id

    a = client.dns.create_a("nas.home", "192.168.1.10", ttl_seconds=300)
    aaaa = client.dns.create_aaaa("nas.home", "fd00::10")
    cname = client.dns.create_cname("printer.home", "nas.home")
    mx = client.dns.create_mx("home.lan", "mail.home.lan", priority=10)
    txt = client.dns.create_txt("home.lan", "v=spf1 -all")
    srv = client.dns.create_srv(
        "home.lan",
        service="_ldap",
        protocol="_tcp",
        server_domain="nas.home",
        port=389,
        priority=0,
        weight=0,
    )
    forward = client.dns.create_forward("corp.example", "8.8.4.4")
    print(a.id, cname.target_domain)
```

You can also build a model and call `create`:

```python
from unifi_dns import ARecord, Client

with Client.from_env() as client:
    client.site_id = client.sites.get_by_name("Default").id
    record = client.dns.create(
        ARecord(domain="cam.home", ipv4_address="192.168.1.40", ttl_seconds=14400)
    )
```

### Upsert by domain

`upsert_*` looks up the same type and domain, then creates or replaces:

```python
with Client.from_env() as client:
    client.site_id = client.sites.get_by_name("Default").id
    client.dns.upsert_a("nas.home", "192.168.1.11", ttl_seconds=300)
    client.dns.upsert_cname("printer.home", "nas.home")
    client.dns.upsert_aaaa("nas.home", "fd00::11")
    client.dns.upsert_txt("home.lan", "v=spf1 -all")
```

### Get, update, and delete

```python
from unifi_dns import ARecord, Client

with Client.from_env() as client:
    client.site_id = client.sites.get_by_name("Default").id

    record = client.dns.get("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")
    updated = client.dns.update(
        record.id,
        ARecord(domain="nas.home", ipv4_address="192.168.1.12", ttl_seconds=300),
    )
    client.dns.delete(updated.id)
```

`update` is a full replace. Send every field the record type requires.

### Errors

```python
from unifi_dns import Client, ConfigurationError, UniFiError

try:
    with Client.from_env() as client:
        client.dns.list_all()
except ConfigurationError as exc:
    print("Missing host, key, or site:", exc)
except UniFiError as exc:
    print(exc.status_code, exc.code, exc)
```

## Command line

After install, run the interactive menu. It uses the same environment variables as `Client.from_env()`.

```bash
unifi-dns
# or
python -m unifi_dns
```

From the menu you can show application info, list and select sites, list or inspect DNS records, then create A, AAAA, CNAME, MX, SRV, TXT, or domain-forward entries.

## First authenticated call

```bash
curl -k -X GET 'https://192.168.0.1/proxy/network/integration/v1/info' \
  -H 'X-API-KEY: YOUR_API_KEY'
```
