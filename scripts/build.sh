#!/bin/bash

set -eou pipefail

if [ "${CHROOT:-'unset'}" == "unset" ]; then
    echo "CHROOT was not provided."
    exit 1
fi
version="${VERSION:-dev}"

# Make sure it's installed
sudo apt install -y debootstrap

set -o xtrace

# Create root filesystem build directory
mkdir "$CHROOT/sector_dns_fs"

# Install debian/trixie into build directory
sudo debootstrap --variant=minbase trixie "$CHROOT/sector_dns_fs" http://deb.debian.org/debian

# Add current resolv.conf for network resolution
sudo cp /etc/resolv.conf "$CHROOT/sector_dns_fs/etc/resolv.conf"

# Install the dnstool
sudo install -Dm755 "$CHROOT/scripts/coredns" "$CHROOT/sector_dns_fs/usr/bin/coredns"
sudo install -Dm755 "$CHROOT/dnstool/cli.py" "$CHROOT/sector_dns_fs/usr/bin/dnstool"
sudo mkdir "$CHROOT/sector_dns_fs/etc/coredns"
sudo cp "$CHROOT/resources/Corefile" "$CHROOT/sector_dns_fs/etc/coredns"
sudo cp "$CHROOT/resources/coredns.service" "$CHROOT/sector_dns_fs/usr/lib/systemd/system"

# Mount these for chroot
sudo mount --bind /proc "$CHROOT/sector_dns_fs/proc"
sudo mount --bind /sys  "$CHROOT/sector_dns_fs/sys"
sudo mount --bind /dev  "$CHROOT/sector_dns_fs/dev"

# Run commands to configure the root filesystem
sudo chroot "$CHROOT/sector_dns_fs" apt update -y
sudo chroot "$CHROOT/sector_dns_fs" apt install -y systemd-sysv ifupdown iproute2 netbase procps dnsutils ca-certificates iputils-ping python3
sudo chroot "$CHROOT/sector_dns_fs" systemctl enable coredns

# Unmount 
sudo umount "$CHROOT/sector_dns_fs/proc"
sudo umount "$CHROOT/sector_dns_fs/sys"
sudo umount "$CHROOT/sector_dns_fs/dev"

# Remove resolv.conf from root filesystem
sudo rm -f "$CHROOT/sector_dns_fs/etc/resolv.conf"

# Create tarball for usage as LXC appliance
sudo tar --numeric-owner -czf "sector-dns-${version}.tar.gz" -C "$CHROOT/sector_dns_fs" .
sha256sum sector-dns-${version}.tar.gz > sector-dns-${version}.tar.gz.sha256
