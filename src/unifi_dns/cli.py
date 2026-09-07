from __future__ import annotations

import argparse
import sys
from collections.abc import Callable, Mapping, Sequence
from typing import TextIO

from unifi_dns.client import Client
from unifi_dns.exceptions import ConfigurationError, UniFiError
from unifi_dns.models import (
    AaaaRecord,
    ARecord,
    CnameRecord,
    DnsRecord,
    ForwardDomain,
    MxRecord,
    Site,
    SrvRecord,
    TxtRecord,
)

RECORD_TYPE_CHOICES: Sequence[tuple[str, str]] = (
    ("1", "A_RECORD"),
    ("2", "AAAA_RECORD"),
    ("3", "CNAME_RECORD"),
    ("4", "MX_RECORD"),
    ("5", "SRV_RECORD"),
    ("6", "TXT_RECORD"),
    ("7", "FORWARD_DOMAIN"),
)

TYPE_ALIASES = {
    "a": "A_RECORD",
    "aaaa": "AAAA_RECORD",
    "cname": "CNAME_RECORD",
    "mx": "MX_RECORD",
    "srv": "SRV_RECORD",
    "txt": "TXT_RECORD",
    "forward": "FORWARD_DOMAIN",
    "forward_domain": "FORWARD_DOMAIN",
    **{key: name for key, name in RECORD_TYPE_CHOICES},
    **{name.lower(): name for _, name in RECORD_TYPE_CHOICES},
}


def record_value(record: DnsRecord) -> str:
    if isinstance(record, ARecord):
        return record.ipv4_address
    if isinstance(record, AaaaRecord):
        return record.ipv6_address
    if isinstance(record, CnameRecord):
        return record.target_domain
    if isinstance(record, MxRecord):
        return f"{record.priority} {record.mail_server_domain}"
    if isinstance(record, SrvRecord):
        return f"{record.service}.{record.protocol} -> {record.server_domain}:{record.port}"
    if isinstance(record, TxtRecord):
        return record.text
    if isinstance(record, ForwardDomain):
        return record.ip_address
    return ""


def format_record(record: DnsRecord) -> str:
    ttl = getattr(record, "ttl_seconds", None)
    ttl_text = str(ttl) if ttl is not None else "-"
    enabled = "yes" if record.enabled else "no"
    record_id = record.id or "-"
    return (
        f"{record.type:<15} {record.domain:<28} {record_value(record):<36} "
        f"ttl={ttl_text:<6} enabled={enabled:<3} {record_id}"
    )


def format_site(site: Site, *, selected: bool = False) -> str:
    marker = " *" if selected else ""
    return f"{site.name}  ({site.id})  ref={site.internal_reference}{marker}"


class App:
    def __init__(
        self,
        client: Client,
        *,
        stdin: TextIO | None = None,
        stdout: TextIO | None = None,
    ) -> None:
        self.client = client
        self.stdin = stdin or sys.stdin
        self.stdout = stdout or sys.stdout
        self.site: Site | None = None
        self._listed_records: list[DnsRecord] = []

    def run(self) -> int:
        try:
            info = self.client.info()
            self._write(f"Connected to UniFi Network {info.application_version}")
            self._load_initial_site()
        except UniFiError as exc:
            self._write(f"Could not connect: {exc}")
            return 1
        except ConfigurationError as exc:
            self._write(str(exc))
            return 2

        while True:
            try:
                choice = self._menu()
            except (EOFError, KeyboardInterrupt):
                self._write("\nGoodbye.")
                return 0
            if choice in {"q", "quit", "exit"}:
                self._write("Goodbye.")
                return 0
            action = self._actions().get(choice)
            if action is None:
                self._write("Unknown option. Choose 1-6 or q.")
                continue
            try:
                action()
            except (EOFError, KeyboardInterrupt):
                self._write("\nCancelled.")
            except (UniFiError, ConfigurationError) as exc:
                self._write(f"Error: {exc}")

    def _actions(self) -> Mapping[str, Callable[[], None]]:
        return {
            "1": self.show_info,
            "2": self.list_sites,
            "3": self.select_site,
            "4": self.list_records,
            "5": self.show_record,
            "6": self.create_record,
        }

    def _menu(self) -> str:
        self._write("")
        self._write("UniFi DNS")
        self._write(f"Current site: {self._site_label()}")
        self._write("1) Application info")
        self._write("2) List sites")
        self._write("3) Select site")
        self._write("4) List DNS records")
        self._write("5) Show DNS record details")
        self._write("6) Create DNS entry")
        self._write("q) Quit")
        return self._ask("Choice").strip().lower()

    def show_info(self) -> None:
        info = self.client.info()
        self._write(f"Application version: {info.application_version}")
        self._write(f"Current site: {self._site_label()}")

    def list_sites(self) -> None:
        sites = self.client.sites.list_all()
        if not sites:
            self._write("No sites found.")
            return
        for index, site in enumerate(sites, start=1):
            selected = self.site is not None and site.id == self.site.id
            self._write(f"  {index}) {format_site(site, selected=selected)}")

    def select_site(self) -> None:
        sites = self.client.sites.list_all()
        if not sites:
            self._write("No sites found.")
            return
        for index, site in enumerate(sites, start=1):
            selected = self.site is not None and site.id == self.site.id
            self._write(f"  {index}) {format_site(site, selected=selected)}")
        chosen = self._pick_index("Site number", len(sites))
        if chosen is None:
            return
        self.site = sites[chosen]
        self.client.site_id = self.site.id
        self._write(f"Selected {self.site.name}.")

    def list_records(self) -> None:
        site_id = self._require_site()
        type_filter = self._optional_record_type()
        records = self.client.dns.list_all(site_id, record_type=type_filter)
        self._listed_records = records
        if not records:
            self._write("No DNS records found.")
            return
        self._write(f"{len(records)} record(s):")
        for index, record in enumerate(records, start=1):
            self._write(f"  {index}) {format_record(record)}")

    def show_record(self) -> None:
        site_id = self._require_site()
        record = self._choose_existing_record(site_id)
        if record is None:
            return
        payload = record.model_dump(by_alias=False)
        self._write("Record details:")
        for key, value in payload.items():
            self._write(f"  {key}: {value}")

    def create_record(self) -> None:
        site_id = self._require_site()
        self._write("Record type:")
        for key, name in RECORD_TYPE_CHOICES:
            self._write(f"  {key}) {name}")
        raw = self._ask("Type").strip().lower()
        record_type = TYPE_ALIASES.get(raw)
        if record_type is None:
            self._write("Unknown record type.")
            return

        creators = {
            "A_RECORD": self._create_a,
            "AAAA_RECORD": self._create_aaaa,
            "CNAME_RECORD": self._create_cname,
            "MX_RECORD": self._create_mx,
            "SRV_RECORD": self._create_srv,
            "TXT_RECORD": self._create_txt,
            "FORWARD_DOMAIN": self._create_forward,
        }
        created = creators[record_type](site_id)
        if created is None:
            self._write("Create cancelled.")
            return
        self._write(f"Created {format_record(created)}")

    def _create_a(self, site_id: str) -> DnsRecord | None:
        domain = self._ask("Domain")
        ipv4_address = self._ask("IPv4 address")
        ttl_seconds = self._ask_int("TTL seconds", default=14400)
        enabled = self._ask_bool("Enabled", default=True)
        if not self._confirm(f"Create A {domain} -> {ipv4_address} (ttl {ttl_seconds})"):
            return None
        return self.client.dns.create_a(
            domain,
            ipv4_address,
            site_id=site_id,
            ttl_seconds=ttl_seconds,
            enabled=enabled,
        )

    def _create_aaaa(self, site_id: str) -> DnsRecord | None:
        domain = self._ask("Domain")
        ipv6_address = self._ask("IPv6 address")
        ttl_seconds = self._ask_int("TTL seconds", default=14400)
        enabled = self._ask_bool("Enabled", default=True)
        if not self._confirm(f"Create AAAA {domain} -> {ipv6_address} (ttl {ttl_seconds})"):
            return None
        return self.client.dns.create_aaaa(
            domain,
            ipv6_address,
            site_id=site_id,
            ttl_seconds=ttl_seconds,
            enabled=enabled,
        )

    def _create_cname(self, site_id: str) -> DnsRecord | None:
        domain = self._ask("Domain")
        target_domain = self._ask("Target domain")
        ttl_seconds = self._ask_int("TTL seconds", default=14400)
        enabled = self._ask_bool("Enabled", default=True)
        if not self._confirm(f"Create CNAME {domain} -> {target_domain}"):
            return None
        return self.client.dns.create_cname(
            domain,
            target_domain,
            site_id=site_id,
            ttl_seconds=ttl_seconds,
            enabled=enabled,
        )

    def _create_mx(self, site_id: str) -> DnsRecord | None:
        domain = self._ask("Domain")
        mail_server_domain = self._ask("Mail server domain")
        priority = self._ask_int("Priority", default=10)
        enabled = self._ask_bool("Enabled", default=True)
        if not self._confirm(f"Create MX {domain} -> {priority} {mail_server_domain}"):
            return None
        return self.client.dns.create_mx(
            domain,
            mail_server_domain,
            priority,
            site_id=site_id,
            enabled=enabled,
        )

    def _create_srv(self, site_id: str) -> DnsRecord | None:
        domain = self._ask("Domain")
        service = self._ask("Service", default="_ldap")
        protocol = self._ask("Protocol", default="_tcp")
        server_domain = self._ask("Server domain")
        port = self._ask_int("Port")
        priority = self._ask_int("Priority", default=0)
        weight = self._ask_int("Weight", default=0)
        enabled = self._ask_bool("Enabled", default=True)
        if not self._confirm(f"Create SRV {service}.{protocol}.{domain} -> {server_domain}:{port}"):
            return None
        return self.client.dns.create_srv(
            domain,
            service=service,
            protocol=protocol,
            server_domain=server_domain,
            port=port,
            priority=priority,
            weight=weight,
            site_id=site_id,
            enabled=enabled,
        )

    def _create_txt(self, site_id: str) -> DnsRecord | None:
        domain = self._ask("Domain")
        text = self._ask("Text")
        enabled = self._ask_bool("Enabled", default=True)
        if not self._confirm(f"Create TXT {domain}"):
            return None
        return self.client.dns.create_txt(domain, text, site_id=site_id, enabled=enabled)

    def _create_forward(self, site_id: str) -> DnsRecord | None:
        domain = self._ask("Domain")
        ip_address = self._ask("DNS server IP")
        enabled = self._ask_bool("Enabled", default=True)
        if not self._confirm(f"Forward {domain} to {ip_address}"):
            return None
        return self.client.dns.create_forward(domain, ip_address, site_id=site_id, enabled=enabled)

    def _load_initial_site(self) -> None:
        sites = self.client.sites.list_all()
        if self.client.site_id:
            match = next((site for site in sites if site.id == self.client.site_id), None)
            if match:
                self.site = match
                return
        if len(sites) == 1:
            self.site = sites[0]
            self.client.site_id = sites[0].id
            self._write(f"Using site {sites[0].name}.")

    def _require_site(self) -> str:
        if self.site is not None:
            return self.site.id
        if self.client.site_id:
            return self.client.site_id
        self._write("Select a site first.")
        self.select_site()
        if self.site is None:
            raise ConfigurationError("A site is required.")
        return self.site.id

    def _site_label(self) -> str:
        if self.site is not None:
            return f"{self.site.name} ({self.site.id})"
        if self.client.site_id:
            return self.client.site_id
        return "none selected"

    def _optional_record_type(self) -> str | None:
        raw = self._ask(
            "Filter by type (A, AAAA, CNAME, MX, SRV, TXT, FORWARD, or blank for all)",
            required=False,
        ).strip().lower()
        if not raw:
            return None
        record_type = TYPE_ALIASES.get(raw)
        if record_type is None:
            self._write("Unknown type filter; showing all records.")
        return record_type

    def _choose_existing_record(self, site_id: str) -> DnsRecord | None:
        if self._listed_records:
            raw = self._ask("Record number from last list (or paste a record id)")
            if raw.isdigit():
                index = int(raw)
                if 1 <= index <= len(self._listed_records):
                    return self._listed_records[index - 1]
                self._write("That number is not in the last list.")
                return None
            return self.client.dns.get(raw, site_id)
        policy_id = self._ask("Record id")
        return self.client.dns.get(policy_id, site_id)

    def _ask(self, label: str, *, default: str | None = None, required: bool = True) -> str:
        suffix = f" [{default}]" if default is not None else ""
        while True:
            raw = self._readline(f"{label}{suffix}: ")
            if raw:
                return raw
            if default is not None:
                return default
            if not required:
                return ""
            self._write("A value is required.")

    def _ask_int(self, label: str, *, default: int | None = None) -> int:
        while True:
            raw = self._ask(label, default=None if default is None else str(default))
            try:
                return int(raw)
            except ValueError:
                self._write("Enter a whole number.")

    def _ask_bool(self, label: str, *, default: bool = True) -> bool:
        hint = "Y/n" if default else "y/N"
        raw = self._ask(f"{label} ({hint})", required=False).strip().lower()
        if not raw:
            return default
        return raw in {"y", "yes", "true", "1"}

    def _confirm(self, message: str) -> bool:
        return self._ask_bool(message, default=True)

    def _pick_index(self, label: str, count: int) -> int | None:
        raw = self._ask(label)
        if not raw.isdigit():
            self._write("Enter a number from the list.")
            return None
        index = int(raw)
        if index < 1 or index > count:
            self._write("That number is not in the list.")
            return None
        return index - 1

    def _readline(self, prompt: str) -> str:
        self.stdout.write(prompt)
        self.stdout.flush()
        line = self.stdin.readline()
        if line == "":
            raise EOFError
        return line.strip()

    def _write(self, message: str) -> None:
        self.stdout.write(message + "\n")
        self.stdout.flush()


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Interactive UniFi Network DNS manager. Uses UNIFI_CONSOLE_HOST and UNIFI_API_KEY."
    )
    parser.parse_args(argv)
    try:
        with Client.from_env() as client:
            return App(client).run()
    except ConfigurationError as exc:
        print(exc, file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
