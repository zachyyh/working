"""Convert a TopologyData dict into a ContainerLab YAML string."""

from __future__ import annotations

from collections import defaultdict, deque
import hashlib
import ipaddress
import logging
import os
import posixpath
from pathlib import Path

import requests

import yaml

from config import CLAB_WORKDIR

# Path to scripts directory ON THE HOST that ContainerLab will bind-mount
# into clab containers.  Inside Docker the backend sees /app/scripts, but
# clab runs on the host, so we need the real host path.
SCRIPTS_DIR = Path(os.environ.get("AE3GIS_HOST_SCRIPTS_DIR", str(Path(__file__).parent.parent / "scripts")))

log = logging.getLogger(__name__)

_IMAGE_ROUTER     = "b3nwilson/frr-ssh:latest"
# Use a plain Linux image for switch containers. The previous OVS image
# attempts to load host kernel modules on startup, which breaks on vanilla
# installs where openvswitch is not present.
_IMAGE_SWITCH     = "alpine:latest"
_IMAGE_HOST       = "alpine:latest"
_IMAGE_WEB_SERVER = "httpd:alpine"

_ROUTER_TYPES = frozenset({"router", "firewall"})
_SWITCH_TYPES = frozenset({"switch"})
_PERSIST_ROOT = CLAB_WORKDIR / "persistent"

# Mapping of container types to script subdirectories
_SCRIPT_TYPE_MAP = {
    "workstation": "workstation",
    "hmi": "workstation",
    "web-server": "server",
    "file-server": "server",
    "plc": "plc",
    "router": "router",
    "firewall": "firewall",
    "switch": "switch",
}
DOCKERHUB_URL = "https://hub.docker.com/v2/repositories/uiaegisv3/?page_size=100"
DOCKERHUB_DATA = requests.get(DOCKERHUB_URL).json()
DOCKERHUB_USER = 'uiaegisv3'




def getRepoNames():
    repo_names = {}
    repo_tags = {}

    if not DOCKERHUB_DATA or 'results' not in DOCKERHUB_DATA:
        log.error("Failed to fetch or parse DockerHub data.")
        return repo_names, repo_tags

    for container in DOCKERHUB_DATA['results']:
        desc = container.get('description')
        if not desc:
            continue
            
        description_chunks = desc.split()
        if len(description_chunks) < 2:
            continue

        if description_chunks[0] == "server":
            repo_names[description_chunks[1]+"-server"] = container['name']
        else:
            repo_names[description_chunks[1]] = container['name']

        count = 5
        tags = []
        while count < len(description_chunks) and description_chunks[count] != "#":
            tags.append(description_chunks[count])
            count +=1
        
        if description_chunks[0] == "server":
            repo_tags[description_chunks[1]+"-server"] = tags
        else:
            repo_tags[description_chunks[1]] = tags


    return repo_names, repo_tags

repos, tags = getRepoNames()


def image_for_container_type(ctype: str) -> str:
    if ctype == "router":
        return "uiaegisv3/router"
    if ctype == "firewall":
        return "uiaegisv3/fwallperim"
    if ctype in _SWITCH_TYPES:
        return "uiaegisv3/switch"
    if ctype == "web-server":
        return "uiaegisv3/nginx-webserver:1.0"
    if ctype == "database-server":
        return "uiaegisv3/debian-postgres:1.0"
    if ctype == "directory-server":
        return "uiaegisv3/ubuntu-openldap"
    if ctype == "ids":
        return "uiaegisv3/ids"
    if ctype == "siem":
        return "uiaegisv3/custom-wazuh-debian:1.0"
    if ctype == "workstation":
        return "uiaegisv3/workstation"
    if ctype == "bastion":
        return "uiaegisv3/bastion"
    if ctype == "pcap":
        return "uiaegisv3/tcp-pcap"
    if ctype == "proxy":
        return "uiaegisv3/seproxy"
    if ctype == "internal-dns-server" or ctype == "internaldns-server":
        return "uiaegisv3/internaldns"
    if ctype == "external-dns-server" or ctype == "externaldns-server":
        return "uiaegisv3/externaldns"
    if ctype == "dhcp-server":
        return "uiaegisv3/dhcpserv"
    if ctype == "plc":
        return "uiaegisv3/plc" 
    if ctype == "hmi":
        return "uiaegisv3/hmi"
    if ctype == "file-server":
        return "uiaegisv3/ubuntu-samba"
    if ctype == "honeypot":
        return "uiaegisv3/honeypot-opencanary"
    return _IMAGE_HOST


def resolve_container_image(container: dict | None = None, ctype: str | None = None) -> str:
    """Return the explicit container image when provided, else the type default."""
    tag = ""
    if container:
        if ctype is None:
            ctype = str(container.get("type") or "").strip()
        tag = str(container.get("image") or "").strip()
        
    repo_name = repos.get(ctype)
    if not repo_name:
        return image_for_container_type((ctype or "").strip())
        
    # Get the specific list of valid tags for this container type
    valid_tags = tags.get(ctype, [])
    
    # Check if the requested tag exists in that list
    if tag == "" or not repo_name or tag not in valid_tags:
        return image_for_container_type((ctype or "").strip())
    else:
        return f"{DOCKERHUB_USER}/{repo_name}:{tag}"


def get_script_bind(ctype: str) -> str | None:
    """Get the read-only bind mount for a container type's scripts.
    
    Returns a bind string like '/path/scripts/workstation:/scripts/workstation:ro'
    or None if no scripts directory exists for this type.
    """
    script_dir = _SCRIPT_TYPE_MAP.get(ctype)
    if not script_dir:
        return None
    
    host_path = SCRIPTS_DIR / script_dir
    # When running inside Docker, SCRIPTS_DIR points to a host path that
    # isn't visible from inside the container — skip the existence check.
    if "AE3GIS_HOST_SCRIPTS_DIR" not in os.environ and not host_path.exists():
        log.warning("Script directory does not exist: %s", host_path)
        return None
    
    return f"{host_path}:/scripts/{script_dir}:ro"


def _eth_index(iface: str) -> int:
    """Extract numeric index from interface name like 'eth1' → 1."""
    try:
        return int(iface.replace("eth", ""))
    except ValueError:
        return 0


def normalize_persistence_path(path: str) -> str | None:
    """Return a normalized absolute in-container path or None if invalid."""
    raw = (path or "").strip()
    if not raw:
        return None
    normalized = posixpath.normpath(raw)
    if not normalized.startswith("/") or normalized == "/":
        return None
    return normalized


def persistence_host_path(topology_id: str, container_id: str, container_path: str) -> Path:
    digest = hashlib.sha1(container_path.encode("utf-8")).hexdigest()[:12]
    return _PERSIST_ROOT / topology_id / container_id / digest


def _gateway_belongs_to_subnet(gateway: str, cidr: str) -> bool:
    """Return True when the gateway IP is a valid host address in the subnet."""
    if not gateway or not cidr:
        return False
    try:
        return ipaddress.ip_address(gateway) in ipaddress.ip_network(cidr, strict=False)
    except ValueError:
        return False


def generate_clab_yaml(topology: dict, topology_id: str | None = None) -> str:
    """Accept the raw topology dict (as stored in the DB) and return clab YAML.

    The topology dict matches the frontend TopologyData shape:
      { name?, sites[], siteConnections[] }

    Node images chosen by type:
      router / firewall  → frrouting/frr:latest
      switch             → alpine:latest
      web-server         → httpd:alpine
      everything else    → alpine:latest

    Cross-subnet routing is fully automatic:
      - When a subnet/site connection has no explicit container endpoints, the
        generator finds the gateway router in each subnet and connects them.
      - Router↔router cross-subnet links get auto-assigned /30 PtP IPs from
        10.255.0.0/24 plus matching static routes on each side.
      - Hosts get static routes to every other subnet via their effective gateway.
        If subnet.gateway is unset, the first router/firewall in the subnet is
        used as the effective gateway so hosts are always routed correctly.
      - Switches are configured with Open vSwitch (ovs-vsctl).
    """

    nodes: dict[str, dict] = {}
    links: list[dict] = []

    # ── Step 1: Build container + subnet metadata (multi-homing aware) ──────
    #
    # A container can now appear in more than one subnet's `containers` list
    # (e.g. a firewall with a leg in the DMZ and another leg in a Servers
    # VLAN). Each such occurrence is a distinct *membership*: its own real
    # interface, in its own real subnet, with its own real IP. `container_type`
    # holds the single logical type for the node; `container_memberships`
    # holds one entry per subnet the node has an interface in.

    container_type: dict[str, str] = {}
    container_memberships: dict[str, list[dict]] = defaultdict(list)
    all_subnets:    dict[str, dict] = {}
    subnet_id_map:  dict[str, dict] = {}
    subnet_id_containers: dict[str, list] = {}
    site_id_subnets: dict[str, list] = {}

    for site in topology.get("sites", []):
        site_id = site.get("id", "")
        if site_id:
            site_id_subnets[site_id] = site.get("subnets", [])

        for subnet in site.get("subnets", []):
            sid     = subnet.get("id", "")
            cidr    = subnet.get("cidr", "")
            gateway = subnet.get("gateway") or ""
            pfx     = cidr.split("/")[1] if "/" in cidr else "24"
            containers = subnet.get("containers", [])

            if gateway and not _gateway_belongs_to_subnet(gateway, cidr):
                log.warning(
                    "Subnet %s has gateway %s outside %s; auto-detecting gateway from local router",
                    sid or subnet.get("name", "<unnamed>"),
                    gateway,
                    cidr,
                )
                gateway = ""

            # If gateway is unset or invalid, auto-detect from the first router/
            # firewall in the subnet that actually belongs to the subnet so hosts
            # always have a working cross-subnet gateway.
            if not gateway:
                for c in containers:
                    candidate_ip = c.get("ip", "")
                    if c.get("type", "") in _ROUTER_TYPES and _gateway_belongs_to_subnet(candidate_ip, cidr):
                        gateway = candidate_ip
                        break

            if cidr:
                all_subnets[cidr] = {"gateway": gateway, "prefix_len": pfx}
            if sid:
                subnet_id_map[sid] = {"cidr": cidr, "gateway": gateway, "prefix_len": pfx}
                subnet_id_containers[sid] = containers

            for c in containers:
                cid   = c["id"]
                ctype = c.get("type", "")
                if cid in container_type and container_type[cid] != ctype:
                    log.warning(
                        "Container %s has inconsistent type across its subnet memberships "
                        "(%s vs %s); using the first one seen",
                        cid, container_type[cid], ctype,
                    )
                container_type.setdefault(cid, ctype)
                container_memberships[cid].append({
                    "subnet_id":  sid,
                    "cidr":       cidr,
                    "ip":         c.get("ip", ""),
                    "prefix_len": pfx,
                    "gateway":    gateway,
                })

    def _primary(cid: str) -> dict:
        """First-seen membership — the only one that matters for the vast
        majority of nodes (hosts/switches), which are single-homed."""
        memberships = container_memberships.get(cid) or [{}]
        return memberships[0]

    def _membership_for_subnet(cid: str, sid: str | None) -> dict | None:
        if not sid:
            return None
        for m in container_memberships.get(cid, []):
            if m["subnet_id"] == sid:
                return m
        return None

    # Thin backward-compatible view for code (Step 4's switch/host branches)
    # that only ever cares about a single-homed node's one IP/subnet.
    container_info: dict[str, dict] = {
        cid: {"type": container_type[cid], **_primary(cid)}
        for cid in container_memberships
    }

    # Build lookup: subnet_id / site_id → best gateway router container_id.
    # Priority: router/firewall whose IP in *this subnet* matches the
    # subnet's gateway. Fallback: first router/firewall found in the subnet.
    def _find_gateway_router(containers: list[dict], sid: str | None = None) -> str | None:
        best = fallback = None
        for c in containers:
            cid = c["id"]
            if container_type.get(cid, "") not in _ROUTER_TYPES:
                continue
            m = _membership_for_subnet(cid, sid) or _primary(cid)
            if c.get("ip") == m.get("gateway") and not best:
                best = cid
            if not fallback:
                fallback = cid
        return best or fallback

    gateway_router_map: dict[str, str] = {}      # subnet_id → container_id
    site_gateway_router_map: dict[str, str] = {}  # site_id → container_id

    for sid, containers in subnet_id_containers.items():
        gw = _find_gateway_router(containers, sid)
        if gw:
            gateway_router_map[sid] = gw

    for site_id, subnets in site_id_subnets.items():
        for subnet in subnets:
            gw = _find_gateway_router(subnet.get("containers", []), subnet.get("id"))
            if gw:
                site_gateway_router_map[site_id] = gw
                break  # use first subnet that has a router

    def _resolve_endpoint(raw_id: str | None) -> str | None:
        """Map subnet/site IDs to their gateway router; pass container IDs through."""
        if not raw_id:
            return None
        if raw_id in container_memberships:
            return raw_id
        return gateway_router_map.get(raw_id) or site_gateway_router_map.get(raw_id)

    # ── Step 2: Resolve all connections and auto-assign interfaces ───────────

    iface_counter:   dict[str, int]       = defaultdict(int)
    container_ifaces: dict[str, set[str]] = defaultdict(set)

    def _next_iface(cid: str) -> str:
        iface_counter[cid] += 1
        iface = f"eth{iface_counter[cid]}"
        container_ifaces[cid].add(iface)
        return iface

    # Pre-register all explicitly named interfaces so that auto-assignment
    # (_next_iface) never collides with an interface already claimed by an
    # existing connection in the topology data.
    def _preregister(conn: dict) -> None:
        raw_from = conn.get("fromContainer") or conn.get("from")
        raw_to   = conn.get("toContainer")   or conn.get("to")
        from_id  = _resolve_endpoint(raw_from) or raw_from
        to_id    = _resolve_endpoint(raw_to)   or raw_to
        if from_id and conn.get("fromInterface"):
            idx = _eth_index(conn["fromInterface"])
            iface_counter[from_id] = max(iface_counter[from_id], idx)
            container_ifaces[from_id].add(conn["fromInterface"])
        if to_id and conn.get("toInterface"):
            idx = _eth_index(conn["toInterface"])
            iface_counter[to_id] = max(iface_counter[to_id], idx)
            container_ifaces[to_id].add(conn["toInterface"])

    for site in topology.get("sites", []):
        for subnet in site.get("subnets", []):
            for conn in subnet.get("connections", []):
                _preregister(conn)
        for conn in site.get("subnetConnections", []):
            _preregister(conn)
    for conn in topology.get("siteConnections", []):
        _preregister(conn)

    def _resolve_conn(conn: dict) -> tuple[str | None, str, str | None, str]:
        from_id = conn.get("fromContainer") or conn.get("from")
        to_id   = conn.get("toContainer")   or conn.get("to")
        fi = conn.get("fromInterface") or (from_id and _next_iface(from_id))
        ti = conn.get("toInterface")   or (to_id   and _next_iface(to_id))
        if from_id and conn.get("fromInterface"):
            container_ifaces[from_id].add(conn["fromInterface"])
            iface_counter[from_id] = max(iface_counter[from_id], _eth_index(conn["fromInterface"]))
        if to_id and conn.get("toInterface"):
            container_ifaces[to_id].add(conn["toInterface"])
            iface_counter[to_id] = max(iface_counter[to_id], _eth_index(conn["toInterface"]))
        return from_id, fi, to_id, ti

    # link_registry entries now carry the *subnet_id* a connection was
    # declared under (None for subnetConnections/siteConnections). Step 3
    # uses that to pick the right membership for multi-homed endpoints
    # instead of assuming a single global "home" IP per container.
    link_registry: list[tuple[str, str, str, str, str | None]] = []

    def _add_link(conn: dict, subnet_id: str | None) -> None:
        """Resolve a connection and add it only if both endpoints are containers.

        Subnet and site IDs are automatically resolved to their gateway router/
        firewall so that a user dragging a connection between two subnets or
        sites in the UI automatically sets up a physical WAN link (and routing)
        between the appropriate router containers without manual configuration.
        """
        raw_from = conn.get("fromContainer") or conn.get("from")
        raw_to   = conn.get("toContainer")   or conn.get("to")

        from_id = _resolve_endpoint(raw_from)
        to_id   = _resolve_endpoint(raw_to)

        if not from_id or not to_id:
            return
        if from_id not in container_memberships or to_id not in container_memberships:
            return

        # Rebuild conn with resolved container IDs so _resolve_conn picks them up.
        resolved = {**conn, "fromContainer": from_id, "toContainer": to_id}
        _, fi, _, ti = _resolve_conn(resolved)

        links.append({"endpoints": [f"{from_id}:{fi}", f"{to_id}:{ti}"]})
        link_registry.append((from_id, fi, to_id, ti, subnet_id))

    # Intra-subnet connections first → routers/hosts get their home interface
    # assigned as eth1 before any cross-subnet WAN interfaces are allocated.
    for site in topology.get("sites", []):
        for subnet in site.get("subnets", []):
            for conn in subnet.get("connections", []):
                _add_link(conn, subnet.get("id"))
        for conn in site.get("subnetConnections", []):
            _add_link(conn, None)
    for conn in topology.get("siteConnections", []):
        _add_link(conn, None)

    # ── Step 3: Compute per-interface IPs and static routes ─────────────────
    #
    # Link classification, in priority order:
    #   1. Declared inside a specific subnet's `connections` list, and at
    #      least one endpoint has a real membership in that subnet → assign
    #      that endpoint its *real, doc-specified* IP from that membership.
    #      This is what makes multi-legged firewalls work: wire each leg
    #      inside its own subnet's `connections` block and it keeps that
    #      subnet's real address, no matter how many other subnets the same
    #      container is also a member of.
    #   2. No subnet context (subnetConnections / siteConnections) → the
    #      original auto-assigned /30 PtP WAN link between two routers.

    iface_ips:  dict[tuple[str, str], tuple[str, str]] = {}
    home_iface: dict[str, str] = {}   # single-homed hosts only; read in Step 4
    router_links: dict[str, list[tuple[str, str]]] = defaultdict(list)
    router_networks: dict[str, set[str]] = defaultdict(set)
    ptp_seq: list[int] = [0]

    def _next_ptp() -> tuple[str, str, str]:
        """Allocate next /30 PtP pair from 10.255.0.0/24."""
        n = ptp_seq[0]; ptp_seq[0] += 1
        b = 4 * n
        return f"10.255.0.{b + 1}", f"10.255.0.{b + 2}", "30"

    assigned_iface_for_subnet: dict[tuple[str, str], str] = {}  # (cid, subnet_id) → claimed iface

    for from_id, fi, to_id, ti, subnet_id in link_registry:
        f_mem = _membership_for_subnet(from_id, subnet_id)
        t_mem = _membership_for_subnet(to_id, subnet_id)

        if subnet_id and (f_mem or t_mem):
            if f_mem:
                key = (from_id, subnet_id)
                iface = assigned_iface_for_subnet.setdefault(key, fi)
                iface_ips[(from_id, iface)] = (f_mem["ip"], f_mem["prefix_len"])
                home_iface.setdefault(from_id, iface)
            if t_mem:
                key = (to_id, subnet_id)
                iface = assigned_iface_for_subnet.setdefault(key, ti)
                iface_ips[(to_id, iface)] = (t_mem["ip"], t_mem["prefix_len"])
                home_iface.setdefault(to_id, iface)
        else:
            # No explicit subnet context → synthetic /30 WAN link between two
            # distinct router/firewall containers (unchanged legacy behavior).
            from_ptp, to_ptp, ptp_pfx = _next_ptp()
            ptp_net = str(ipaddress.ip_network(f"{from_ptp}/{ptp_pfx}", strict=False))
            iface_ips[(from_id, fi)] = (from_ptp, ptp_pfx)
            iface_ips[(to_id,   ti)] = (to_ptp,   ptp_pfx)
            router_links[from_id].append((to_id, to_ptp))
            router_links[to_id].append((from_id, from_ptp))
            router_networks[from_id].add(ptp_net)
            router_networks[to_id].add(ptp_net)

    # Router adjacency for static-route propagation now comes directly from
    # *shared subnet membership*, not only from auto-PtP links. Two routers
    # that both have a real interface on the same subnet (e.g. perim-fw and
    # int-fw both sitting on the "Perimeter↔Internal Transit" /30) are
    # adjacent by construction — no synthetic link needed to discover that.
    router_subnets: dict[str, set[str]] = defaultdict(set)
    for cid, memberships in container_memberships.items():
        if container_type.get(cid, "") not in _ROUTER_TYPES:
            continue
        for m in memberships:
            if m["cidr"]:
                router_networks[cid].add(m["cidr"])
                router_subnets[cid].add(m["cidr"])

    routers_by_subnet: dict[str, list[str]] = defaultdict(list)
    for cid, cidrs in router_subnets.items():
        for cidr in cidrs:
            routers_by_subnet[cidr].append(cid)

    for cidr, cids in routers_by_subnet.items():
        for i, cid_a in enumerate(cids):
            for cid_b in cids[i + 1:]:
                ip_a = next((m["ip"] for m in container_memberships[cid_a] if m["cidr"] == cidr), None)
                ip_b = next((m["ip"] for m in container_memberships[cid_b] if m["cidr"] == cidr), None)
                if ip_a and ip_b:
                    router_links[cid_a].append((cid_b, ip_b))
                    router_links[cid_b].append((cid_a, ip_a))

    # Compute static routes for every router to every remote subnet reachable
    # across chained router links. Each route uses the first-hop neighbor's
    # address so multi-hop topologies (edge-rtr → perim-fw → int-fw → VLANs)
    # work out of the box.
    router_static_routes: dict[str, list[tuple[str, str]]] = defaultdict(list)

    for src_router in router_subnets:
        first_hop_via: dict[str, str] = {}
        seen = {src_router}
        queue = deque([(src_router, None)])

        while queue:
            current_router, current_via = queue.popleft()
            for neighbor_router, neighbor_via in router_links.get(current_router, []):
                if neighbor_router in seen:
                    continue
                seen.add(neighbor_router)
                first_hop_via[neighbor_router] = current_via or neighbor_via
                queue.append((neighbor_router, first_hop_via[neighbor_router]))

        added_routes: set[tuple[str, str]] = set()
        directly_connected = router_networks.get(src_router, set())
        for dst_router, via_ip in first_hop_via.items():
            for dst_network in router_networks.get(dst_router, set()):
                route = (dst_network, via_ip)
                if not dst_network or dst_network in directly_connected or route in added_routes:
                    continue
                router_static_routes[src_router].append(route)
                added_routes.add(route)

    # ── Step 4: Build node exec configs ─────────────────────────────────────

    for site in topology.get("sites", []):
        for subnet in site.get("subnets", []):
            for container in subnet.get("containers", []):
                cid    = container["id"]
                info   = container_info.get(cid, {})
                ctype  = info.get("type", "")
                ip     = info.get("ip", "")
                pfx    = info.get("prefix_len", "24")
                ifaces = sorted(container_ifaces.get(cid, set()), key=_eth_index)

                exec_cmds: list[str] = []

                if ctype in _SWITCH_TYPES:
                    # Use Linux bridge for switch nodes.
                    # If bridge creation/config fails on a host, fall back to
                    # placing the switch IP on the first data interface so nodes
                    # remain reachable on vanilla installs.
                    if ifaces:
                        first_iface = ifaces[0]
                        iface_list = " ".join(ifaces)
                        exec_cmds.append(
                            "sh -lc '"
                            f"for i in {iface_list}; do ip link set \"$i\" up >/dev/null 2>&1 || true; done; "
                            "ip link show br0 >/dev/null 2>&1 || ip link add br0 type bridge || true; "
                            f"for i in {iface_list}; do ip link set \"$i\" master br0 >/dev/null 2>&1 || true; done; "
                            "ip link set br0 up >/dev/null 2>&1 || true'"
                        )
                        if ip:
                            exec_cmds.append(
                                "sh -lc '"
                                f"ip addr replace {ip}/{pfx} dev br0 >/dev/null 2>&1 || "
                                f"ip addr replace {ip}/{pfx} dev {first_iface} >/dev/null 2>&1 || true'"
                            )
                    # Switch management traffic still needs a default route for
                    # cross-subnet reachability, same as host endpoints.
                    gateway = info.get("gateway", "")
                    if gateway:
                        exec_cmds.append(f"ip route replace default via {gateway}")

                elif ctype in _ROUTER_TYPES:
                    if ctype == "firewall":
                        # ── VyOS Firewall Native Configuration ──
                        exec_cmds.append("sh -c 'echo \"#!/bin/vbash\" > /tmp/fw_config.sh'")
                        
                        # Wait for the VyOS configuration system to finish booting before sending commands
                        exec_cmds.append("sh -c 'echo \"while ! systemctl is-active vyos-router.service >/dev/null 2>&1; do sleep 2; done; sleep 3\" >> /tmp/fw_config.sh'")
                        
                        exec_cmds.append("sh -c 'echo \"source /opt/vyatta/etc/functions/script-template\" >> /tmp/fw_config.sh'")
                        exec_cmds.append("sh -c 'echo \"configure\" >> /tmp/fw_config.sh'")
                        
                        # Configure Interface IPs
                        for iface in ifaces:
                            key = (cid, iface)
                            if key in iface_ips:
                                r_ip, r_pfx = iface_ips[key]
                                exec_cmds.append(f"sh -c 'echo \"set interfaces ethernet {iface} address {r_ip}/{r_pfx}\" >> /tmp/fw_config.sh'")
                        
                        # Configure Static Routing
                        for dest_cidr, via_ip in router_static_routes.get(cid, []):
                            exec_cmds.append(f"sh -c 'echo \"set protocols static route {dest_cidr} next-hop {via_ip}\" >> /tmp/fw_config.sh'")
                            
                        # Commit and Save
                        exec_cmds.append("sh -c 'echo \"commit\" >> /tmp/fw_config.sh'")
                        exec_cmds.append("sh -c 'echo \"save\" >> /tmp/fw_config.sh'")
                        exec_cmds.append("sh -c 'echo \"exit\" >> /tmp/fw_config.sh'")
                        
                        # Make executable and run as the vyos user
                        exec_cmds.append("chmod +x /tmp/fw_config.sh")
                        exec_cmds.append("su - vyos -c /tmp/fw_config.sh")
                        
                    else:
                        # ── Standard FRR Router Configuration ──
                        exec_cmds.append("sysctl -w net.ipv4.ip_forward=1")
                        for iface in ifaces:
                            key = (cid, iface)
                            if key in iface_ips:
                                r_ip, r_pfx = iface_ips[key]
                                exec_cmds.append(f"ip addr add {r_ip}/{r_pfx} dev {iface}")
                        for dest_cidr, via_ip in router_static_routes.get(cid, []):
                            exec_cmds.append(f"ip route add {dest_cidr} via {via_ip}")

                else:
                    # Host (workstation / web-server / plc / etc.): assign IP on
                    # home interface, then add a default route via the effective
                    # gateway. A default route (rather than per-subnet routes) is
                    # required so that replies to cross-subnet pings sourced from
                    # router PtP addresses (10.255.0.x/30) are forwarded correctly —
                    # the host has no explicit route for those PtP ranges otherwise.
                    if ip and ifaces:
                        target_iface = home_iface.get(cid, ifaces[0])
                        exec_cmds.append(f"ip addr add {ip}/{pfx} dev {target_iface}")
                    gateway = info.get("gateway", "")
                    if gateway:
                        exec_cmds.append(f"ip route replace default via {gateway}")

                node_cfg: dict = {"kind": "linux", "image": resolve_container_image(container, ctype)}

                node_cfg["env"] = {"container": "docker"}
                if container.get("metadata", None) is not None:
                    node_cfg["env"].update(container.get("metadata", None))

                # Initialize binds array for ALL nodes so we can inject the anti-hijack mounts
                binds: list[str] = []

                # --- NUCLEAR FIX FOR TTY HIJACK ---
                # Mask systemd getty services so VyOS cannot spawn a login prompt on the host's physical monitor.
                if ctype == "firewall":
                    binds.extend([
                        "/dev/null:/lib/systemd/system/getty@.service:ro",
                        "/dev/null:/lib/systemd/system/serial-getty@.service:ro",
                        "/dev/null:/lib/systemd/system/console-getty.service:ro",
                        "/dev/null:/lib/systemd/system/container-getty@.service:ro"
                    ])

                if topology_id:
                    raw_persist = container.get("persistencePaths", []) or []
                    if raw_persist:
                        log.info("Container %s has persistencePaths: %s", cid, raw_persist)
                    for raw_path in raw_persist:
                        container_path = normalize_persistence_path(str(raw_path))
                        if not container_path:
                            log.warning("Container %s: persistence path %r rejected by normalize", cid, raw_path)
                            continue
                        host_path = persistence_host_path(topology_id, cid, container_path)
                        host_path.mkdir(parents=True, exist_ok=True)
                        binds.append(f"{host_path}:{container_path}")
                        log.info("Container %s: bind %s -> %s", cid, host_path, container_path)

                # Handle read-only scripts directory
                script_bind = get_script_bind(ctype)
                if script_bind:
                    binds.append(script_bind)
                    log.info("Container %s (%s): mounted scripts at %s", cid, ctype, script_bind.split(":")[1])

                if binds:
                    node_cfg["binds"] = binds
                if exec_cmds:
                    node_cfg["exec"] = exec_cmds
                nodes[cid] = node_cfg

    topo_name = topology.get("name") or "ae3gis-topology"
    clab = {
        "name": topo_name,
        "topology": {
            "nodes": nodes,
            "links": links,
        },
    }

    return yaml.dump(clab, default_flow_style=False, sort_keys=False)
