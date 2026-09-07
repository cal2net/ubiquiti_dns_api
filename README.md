# unifi-dns

Python client for [UniFi Network](https://developer.ui.com/network/v10.4.57) DNS policies. A DNS policy is a local resolver entry: A, AAAA, CNAME, MX, SRV, TXT, or a domain-forward.

Generate an API key at [unifi.ui.com](https://unifi.ui.com).

## Install

```bash
python -m pip install -e ".[dev]"
```

## Configure

Copy `.env.example` and set either a local console host or a cloud console id:

```bash
UNIFI_API_KEY=...
UNIFI_CONSOLE_HOST=192.168.0.1
UNIFI_VERIFY_SSL=false
```

`ubiquiti_api_key` is also accepted.

## Command line

After install, run the interactive menu. It reads `UNIFI_CONSOLE_HOST` and `UNIFI_API_KEY` (or `ubiquiti_api_key`) from the environment or `.env`.

```bash
unifi-dns
# or
python -m unifi_dns
```

From the menu you can show application info, list and select sites, list or inspect DNS records, then create A, AAAA, CNAME, MX, SRV, TXT, or domain-forward entries.

## Usage

```python
from unifi_dns import Client

with Client.from_env() as client:
    print(client.info().application_version)

    site = client.sites.get_by_name("Default")  # or client.sites.list()
    client.site_id = site.id

    records = client.dns.list_all(record_type="A_RECORD")
    client.dns.upsert_a("nas.home", "192.168.1.10", ttl_seconds=300)
    client.dns.upsert_cname("printer.home", "nas.home")
```

Create helpers also exist for AAAA, MX, SRV, TXT, and `FORWARD_DOMAIN`. Use `client.dns.get`, `update`, and `delete` for id-based changes.

## First authenticated call

```bash
curl -k -X GET 'https://192.168.0.1/proxy/network/integration/v1/info' \
  -H 'X-API-KEY: YOUR_API_KEY'
```
