"""
linux-iprojection: Discovery of Epson projectors / EShare receivers on the local network.
Part of the iProjection (Unofficial) project by John Varghese (J0X)
https://github.com/John-Varghese-EH

Two strategies, used together:

1. mDNS/zeroconf browsing. We look for specific service types and also
   filter _http._tcp.local. for projector-related keywords.
2. A LAN sweep on TCP port 3629 (ESC/VP.net control).
"""

from __future__ import annotations

import asyncio
import ipaddress
import logging
import socket
from dataclasses import dataclass, field

from zeroconf import Zeroconf
from zeroconf.asyncio import AsyncServiceBrowser, AsyncServiceInfo, AsyncZeroconf

from .pjlink import PJLINK_PORT
from .protocol import ESCVP_PORT

log = logging.getLogger(__name__)

SERVICE_TYPES = [
    "_epson._tcp.local.",
    "_eshare._tcp.local.",
    "_http._tcp.local.",
    "_pjlink._tcp.local.",
]

HTTP_KEYWORDS = [
    "eshare",
    "screen",
    "cast",
    "display",
    "receiver",
    "epson",
    "projector",
    "pj",
    "eb-",
    "ex-",
    "powerlite",
]

SCAN_TIMEOUT = 0.4
SCAN_CONCURRENCY = 64


@dataclass
class DiscoveredDevice:
    name: str
    address: str
    port: int
    source: str  # "mdns" or "scan"
    alias: str | None = None
    device_type: str = "projector"
    capabilities: list[str] = field(default_factory=list)
    stream_port: int = 5004
    audio_port: int = 5006
    info: dict = field(default_factory=dict)


class _AsyncCollectingListener:
    def __init__(self, azc: AsyncZeroconf, results: list[DiscoveredDevice]):
        self.azc = azc
        self.results = results
        self._tasks: set[asyncio.Task] = set()

    def add_service(self, zc: Zeroconf, type_: str, name: str) -> None:
        task = asyncio.create_task(self._process_service(type_, name))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    def update_service(self, zc: Zeroconf, type_: str, name: str) -> None:
        pass

    def remove_service(self, zc: Zeroconf, type_: str, name: str) -> None:
        pass

    async def _process_service(self, type_: str, name: str) -> None:
        try:
            info = AsyncServiceInfo(type_, name)
            await info.async_request(self.azc.zeroconf, 3000)
            if not info or not info.addresses:
                return

            # Keyword filtering for generic HTTP services
            if type_ == "_http._tcp.local.":
                name_lower = name.lower()
                if not any(kw in name_lower for kw in HTTP_KEYWORDS):
                    return

            capabilities = []
            if info.properties:
                for k, v in info.properties.items():
                    if isinstance(v, bytes):
                        try:
                            v_str = v.decode("utf-8")
                        except UnicodeDecodeError:
                            v_str = repr(v)
                    else:
                        v_str = str(v)
                    capabilities.append(
                        f"{k.decode('utf-8') if isinstance(k, bytes) else k}={v_str}"
                    )

            device_type = "projector"
            if "_eshare" in type_:
                device_type = "eshare_receiver"
            elif "_pjlink" in type_:
                device_type = "pjlink_projector"

            for addr in info.addresses_by_version(4):
                ip_str = socket.inet_ntoa(addr)
                self.results.append(
                    DiscoveredDevice(
                        name=name,
                        address=ip_str,
                        port=info.port or ESCVP_PORT,
                        source="mdns",
                        device_type=device_type,
                        capabilities=capabilities,
                        stream_port=5004,
                        audio_port=5006,
                        info={"type": type_, "server": info.server},
                    )
                )
        except Exception as e:
            log.debug("mDNS async process error: %s", e)


async def discover_mdns(timeout: float = 3.0) -> list[DiscoveredDevice]:
    results: list[DiscoveredDevice] = []
    try:
        try:
            interfaces = [str(i.ip) for i in _active_ipv4_interfaces()]
        except Exception as e:
            log.debug("Interface enumeration failed: %s", e)
            interfaces = []
        # Only bind to interfaces that are up; zeroconf's default uses every
        # interface with an address, which logs ENETUNREACH for down links.
        zc_kwargs = {"interfaces": interfaces} if interfaces else {}
        async with AsyncZeroconf(**zc_kwargs) as azc:
            listener = _AsyncCollectingListener(azc, results)
            browsers = [
                AsyncServiceBrowser(azc.zeroconf, svc, listener) for svc in SERVICE_TYPES
            ]
            await asyncio.sleep(timeout)
            for b in browsers:
                await b.async_cancel()
    except Exception as e:
        log.debug("mDNS discovery error: %s", e)
    return results


def _iface_is_up(name: str) -> bool:
    """True unless the kernel reports the interface's operational state as down.

    Interfaces without carrier (e.g. an unplugged Ethernet port) keep their
    addresses but report "down"; sending to them fails with ENETUNREACH.
    """
    try:
        with open(f"/sys/class/net/{name}/operstate", encoding="ascii") as f:
            state = f.read().strip().lower()
            if state in ("down", "lowerlayerdown", "notpresent", "dormant"):
                return False
    except OSError:
        pass

    try:
        with open(f"/sys/class/net/{name}/carrier", encoding="ascii") as f:
            if f.read().strip() == "0":
                return False
    except OSError:
        pass

    return True


def _active_ipv4_interfaces() -> list[ipaddress.IPv4Interface]:
    """Non-loopback IPv4 addresses of this host's interfaces that are up."""
    import ifaddr  # dependency of zeroconf

    result: list[ipaddress.IPv4Interface] = []
    for adapter in ifaddr.get_adapters():
        if not _iface_is_up(adapter.name):
            log.debug("Skipping interface %s: not up", adapter.name)
            continue
        for ip in adapter.ips:
            if ip.is_IPv4 and not ip.ip.startswith("127."):
                try:
                    result.append(ipaddress.IPv4Interface(f"{ip.ip}/{ip.network_prefix}"))
                except ValueError:
                    pass
    return result


def _local_ipv4_networks() -> list[ipaddress.IPv4Network]:
    """Find this host's active IPv4 /24 subnets across all network interfaces."""
    nets: list[ipaddress.IPv4Network] = []
    try:
        for iface in _active_ipv4_interfaces():
            # Constrain large networks (e.g. link-local /16) to /24 around host to keep scan fast
            if iface.network.prefixlen < 24 or iface.network.prefixlen == 32:
                sub = ipaddress.IPv4Network(f"{iface.ip}/24", strict=False)
                if sub not in nets:
                    nets.append(sub)
            elif iface.network not in nets:
                nets.append(iface.network)
    except Exception as e:
        log.debug("Interface enumeration failed: %s", e)

    if not nets:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            local_ip = s.getsockname()[0]
            s.close()
            iface = ipaddress.ip_interface(f"{local_ip}/24")
            nets.append(iface.network)
        except OSError:
            pass

    return nets


def _get_arp_neighbor_ips(
    active_interfaces: list[ipaddress.IPv4Interface] | list[ipaddress.IPv4Network] | set[str] | None = None,
) -> set[str]:
    """Retrieve active neighbor IPs from the ARP table for fast direct-link discovery."""
    ips = set()
    try:
        with open("/proc/net/arp", "r", encoding="utf-8") as f:
            for line in f.readlines()[1:]:
                parts = line.split()
                # The kernel drops dynamic entries of a link that goes down,
                # but not static ones.
                if len(parts) >= 6 and not _iface_is_up(parts[5]):
                    continue
                if len(parts) >= 4 and parts[3] not in ("00:00:00:00:00:00", "00:00:00:00:00:00:00:00"):
                    ip_cand = parts[0].strip()
                    try:
                        ip_obj = ipaddress.IPv4Address(ip_cand)
                        if active_interfaces is not None:
                            matched = False
                            for item in active_interfaces:
                                if isinstance(item, ipaddress.IPv4Network) and ip_obj in item:
                                    matched = True
                                    break
                                elif isinstance(item, ipaddress.IPv4Interface) and ip_obj in item.network:
                                    matched = True
                                    break
                                elif isinstance(item, str) and len(parts) >= 6 and parts[5].strip() == item:
                                    matched = True
                                    break
                            if not matched:
                                continue
                        ips.add(ip_cand)
                    except ValueError:
                        pass
    except Exception:
        pass
    return ips


async def _probe(ip: str, port: int, sem: asyncio.Semaphore) -> DiscoveredDevice | None:
    async with sem:
        try:
            fut = asyncio.open_connection(ip, port)
            reader, writer = await asyncio.wait_for(fut, timeout=SCAN_TIMEOUT)
            writer.close()
            try:
                await writer.wait_closed()
            except OSError:
                pass
            return DiscoveredDevice(
                name=ip,
                address=ip,
                port=port,
                source="scan",
                device_type="projector",
                stream_port=5004,
                audio_port=5006,
            )
        except (OSError, asyncio.TimeoutError):
            return None


async def discover_by_scan(
    ports: list[int] | None = None, network: ipaddress.IPv4Network | None = None
) -> list[DiscoveredDevice]:
    if ports is None:
        # 3629 = ESC/VP, 4352 = PJLink, 3620/3621 = iProjection data ports
        ports = [ESCVP_PORT, PJLINK_PORT, 3620, 3621]

    sem = asyncio.Semaphore(SCAN_CONCURRENCY)
    tasks = []
    seen_ips = set()

    # Determine active networks
    networks = [network] if network else _local_ipv4_networks()

    # Strategy 1: Fast ARP neighbor sweep on active networks
    # Filter ARP neighbors to active networks so disconnected links aren't probed
    arp_ips = _get_arp_neighbor_ips(active_interfaces=networks)
    for ip in arp_ips:
        try:
            ip_obj = ipaddress.IPv4Address(ip)
            if not any(ip_obj in net for net in networks):
                continue
        except ValueError:
            continue
        seen_ips.add(ip)
        for port in ports:
            tasks.append(_probe(ip, port, sem))

    # Strategy 2: Subnet sweep
    for net in networks:
        for host in net.hosts():
            host_str = str(host)
            if host_str not in seen_ips:
                for port in ports:
                    tasks.append(_probe(host_str, port, sem))

    if not tasks:
        log.warning("Could not determine local subnet - enter the projector IP manually")
        return []

    results = await asyncio.gather(*tasks)
    discovered: list[DiscoveredDevice] = []
    dedup_addresses = set()
    for r in results:
        if r is not None and r.address not in dedup_addresses:
            dedup_addresses.add(r.address)
            discovered.append(r)
    return discovered


# Native EasyMP identity and JPEG capabilities (TCP registration).
async def discover_eemp(timeout: float = 2.0) -> list[DiscoveredDevice]:
    """Validate EasyMP devices with real TCP registration, not guessed UDP flags."""
    from .easymp import EasyMPClient
    from .protocol import ProjectorError

    devices = await discover_by_scan(ports=[3620])
    limit = asyncio.Semaphore(8)

    async def identify(device):
        async with limit:
            try:
                client = EasyMPClient(device.address)
                identity = await asyncio.wait_for(asyncio.to_thread(client.inspect), timeout)
            except (OSError, ProjectorError, ValueError):
                return None
            return DiscoveredDevice(
                name=identity.name.decode("utf-8", errors="replace"),
                address=device.address, port=ESCVP_PORT, source="eemp",
                capabilities=["easymp", "jpeg_tiles"], stream_port=3621, audio_port=3621,
                info={"streaming_mode": "easymp", "frame_size": [identity.width, identity.height]},
            )

    return [device for device in await asyncio.gather(*(identify(d) for d in devices)) if device]


async def discover_all(mdns_timeout: float = 3.0) -> list[DiscoveredDevice]:
    """Run all discovery strategies concurrently, dedupe by address."""
    mdns_task = asyncio.create_task(discover_mdns(mdns_timeout))
    scan_task = asyncio.create_task(discover_by_scan())
    eemp_task = asyncio.create_task(discover_eemp(timeout=2.0))
    mdns_results, scan_results, eemp_results = await asyncio.gather(
        mdns_task, scan_task, eemp_task
    )

    seen: dict[str, DiscoveredDevice] = {}
    # Priority: verified EasyMP > mDNS > port scan.
    for d in [*eemp_results, *mdns_results, *scan_results]:
        if d.address not in seen or seen[d.address].source == "scan":
            seen[d.address] = d
    return list(seen.values())

