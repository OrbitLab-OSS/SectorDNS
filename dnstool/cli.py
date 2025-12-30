#!/usr/bin/env python3

import argparse
import ipaddress
import json
import subprocess
from pathlib import Path
from typing import NamedTuple


class CoreDNS:
    """Handles CoreDNS service operations such as reloading the service."""

    ZONE_FILE = Path("/etc/coredns/zone.db")

    @classmethod
    def reload_coredns(cls) -> None:
        """Restart the CoreDNS service using systemctl."""
        subprocess.run(args=["/usr/bin/systemctl", "restart", "coredns"], check=False)


class Init(CoreDNS):
    """Handles initialization of the Corefile with ACL for the sector CIDR."""
    CORE_FILE = Path("/etc/coredns/Corefile")

    @classmethod
    def __get_cidr_from_interface__(cls) -> ipaddress.IPv4Network:
        """Retrieve the CIDR network from the eth0 interface."""
        result = subprocess.run(  # noqa: S603
            ["/usr/sbin/ip", "-j", "addr", "show", "eth0"],
            check=True,
            capture_output=True,
            text=True,
        )
        data: list[dict] = json.loads(result.stdout)
        addr = next(iter(addr for addr in data[0].get("addr_info", []) if addr["label"] == "eth0"))
        return ipaddress.IPv4Network(address=f"{addr['local']}/{addr['prefixlen']}", strict=False)

    @classmethod
    def __get_zone_from_hostname__(cls) -> str:
        """Retrieve the DNS zone from the system hostname."""
        result = subprocess.run(  # noqa: S603
            ["/usr/bin/hostname"],
            check=True,
            capture_output=True,
            text=True,
        )
        zone, _ = result.stdout.split("-")
        return f"{zone}.orbitlab.internal"

    @classmethod
    def __create_zone_file__(cls, zone_name: str) -> None:
        """Create a new DNS zone file if it does not already exist."""
        if cls.ZONE_FILE.exists():
            return

        origin = f"$ORIGIN {zone_name}.\n"
        soa = (
            f"@   3600 IN SOA ns1.{zone_name}. admin.{zone_name}. (\n"
            "        1 3600 600 86400 3600\n)\n"
        )

        ns = f"    IN NS ns1.{zone_name}.\n"
        ns_a = "ns1 IN A 127.0.0.1\n"
        with cls.ZONE_FILE.open(mode="+wt") as zone_file:
            zone_file.writelines([origin, soa, ns, ns_a])

    @classmethod
    def run(cls, _: argparse.Namespace) -> None:
        """Initialize the Corefile with ACL for the sector CIDR."""
        sector_cidr = cls.__get_cidr_from_interface__()
        zone_name = cls.__get_zone_from_hostname__()
        acl_prefix = "# ACL"
        zone_prefix = "# ZONE"
        # ACL ensures only the hosts inside the sector are allowed to query
        acl = (
            "acl {\n"
            f"        allow net {sector_cidr}\n"
            "        drop\n"
            "    }"
        )
        # The Zone file provides authoritative responses for all hosts registered to the sector
        # The "fallthrough" allows for recursive queries if it does not match a record in the zone file.
        zone = (
            f"file /etc/coredns/zone.db {zone_name} {{\n"
            "        fallthrough\n"
            "    }"
        )

        with cls.CORE_FILE.open("rt") as core_file:
            data = core_file.read()

        if acl_prefix not in data:
            print("Already initialized.")
            return

        with cls.CORE_FILE.open("wt") as core_file:
            core_file.write(
                data.replace(acl_prefix, acl).replace(zone_prefix, zone),
            )
        cls.__create_zone_file__(zone_name=zone_name)


class AddRecordArgs(NamedTuple):
    """Arguments required to create a DNS A Record."""

    hostname: str
    ttl: int
    ip: str


class DeleteRecordArgs(NamedTuple):
    """Arguments required to delete a DNS A Record."""

    hostname: str


class RecordManagement(CoreDNS):
    """Handles DNS record management operations for the zone file."""

    @classmethod
    def add_record(cls, args: AddRecordArgs) -> None:
        """Add an A record to the DNS zone file."""
        record = f"{args.hostname} {args.ttl} IN A {args.ip}\n"
        with cls.ZONE_FILE.open(mode="a") as zone_file:
            zone_file.write(record)
        print(f"Added A Record: {args.hostname} -> {args.ip}")
        cls.reload_coredns()

    @classmethod
    def delete_record(cls, args: DeleteRecordArgs) -> None:
        """Delete an A record from the DNS zone file."""
        hostname = args.hostname.strip()
        if not hostname:
            print("No hostname provided")
            return
        if any(hostname == forbidden for forbidden in ("$ORIGIN", "@", "ns1", " ")):
            print(f"Hostname is forbidden: {hostname}")
            return
        with cls.ZONE_FILE.open(mode="rt") as zone_file:
            lines = zone_file.readlines()
        new_lines = [line for line in lines if not line.startswith(f"{hostname} ")]
        if len(new_lines) == len(lines):
            print(f"Record not found: {hostname}")
            return
        with cls.ZONE_FILE.open(mode="wt") as zone_file:
            zone_file.writelines(new_lines)
        print(f"Deleted A Record: {hostname}")
        cls.reload_coredns()


def main() -> None:
    """Parse command-line arguments and dispatch to the appropriate CoreDNS management operation."""
    parser = argparse.ArgumentParser(
        prog="dnstool",
        description="OrbitLab CoreDNS management utility",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    # init coredns
    init_parser = subparsers.add_parser("init")
    init_parser.set_defaults(func=Init.run)

    # record add/delete
    record_parser = subparsers.add_parser("record")
    record_sub = record_parser.add_subparsers(dest="record_cmd", required=True)

    record_add = record_sub.add_parser("add")
    record_add.add_argument("hostname")
    record_add.add_argument("ip")
    record_add.add_argument("--ttl", type=int, default=300)
    record_add.set_defaults(func=RecordManagement.add_record)

    record_del = record_sub.add_parser("delete")
    record_del.add_argument("hostname")
    record_del.set_defaults(func=RecordManagement.delete_record)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
