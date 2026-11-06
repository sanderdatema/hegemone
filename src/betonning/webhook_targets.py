"""Bind een goedgekeurd webhookdoel aan een gecontroleerd IP-adres.

HTTPX ondersteunt expliciete IP-connecties met de oorspronkelijke Host/SNI.
Zo vindt na de DNS-controle geen tweede ongecontroleerde resolutie plaats.
"""

from __future__ import annotations

import asyncio
import ipaddress
import socket
from urllib.parse import urlsplit
import httpx


def forbidden(address: str) -> bool:
    ip = ipaddress.ip_address(address)
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    return ip.is_loopback or ip.is_link_local or ip.is_unspecified or ip.is_multicast or ip.is_reserved


def canonical_ip(host: str):
    try:
        return ipaddress.ip_address(host)
    except ValueError:
        try:
            return ipaddress.ip_address(socket.inet_aton(host))
        except OSError:
            return None


async def pinned_target(url: str, *, allow_loopback: bool = False):
    parsed = urlsplit(url)
    host = httpx.URL(url).host.rstrip('.')
    port = parsed.port or (443 if parsed.scheme == 'https' else 80)
    if allow_loopback:
        # Expliciete test/dev-escape; nooit nodig in productie.
        return url, {}, {}
    ip = canonical_ip(host)
    if ip is not None:
        addresses = [str(ip)]
    else:
        rows = await asyncio.wait_for(asyncio.to_thread(
            socket.getaddrinfo, host, port, 0, socket.SOCK_STREAM,
        ), timeout=5)
        addresses = list(dict.fromkeys(str(row[4][0]) for row in rows))
    if not addresses or any(forbidden(address) for address in addresses):
        raise ValueError('Webhookdoel resolveert naar een verboden adres')
    target = httpx.URL(url).copy_with(host=addresses[0])
    # De gecontroleerde URL wordt ook voor virtual hosting en TLS gebruikt.
    authority = httpx.URL(url).netloc.decode('ascii')
    return target, {'Host': authority, 'Connection': 'close'}, {'sni_hostname': host}
