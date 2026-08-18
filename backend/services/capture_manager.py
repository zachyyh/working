"""Manage Wireshark sidecar containers for in-browser packet capture.

Each capture session spins up a linuxserver/wireshark container that shares
the target container's network namespace, exposing noVNC on a dynamic port.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from dataclasses import dataclass

from services import ansible_manager

log = logging.getLogger(__name__)

# ── Config ────────────────────────────────────────────────────────

CAPTURE_IMAGE = os.getenv("AE3GIS_CAPTURE_IMAGE", "lscr.io/linuxserver/wireshark:latest")
WIRESHARK_NOVNC_PORT = 3000  # noVNC port inside the wireshark container

# ── Data ──────────────────────────────────────────────────────────


@dataclass
class CaptureSession:
    topology_id: str
    container_id: str
    container_name: str   # target clab container name
    docker_name: str      # wireshark sidecar container name
    port: int             # noVNC port (3000 inside the shared network ns)
    target_ip: str        # IP of the target container (for proxying)
    created_at: float


# ── State ─────────────────────────────────────────────────────────

_sessions: dict[tuple[str, str], CaptureSession] = {}
_lock = asyncio.Lock()


# ── Helpers ───────────────────────────────────────────────────────


async def _run(*cmd: str) -> tuple[int, str, str]:
    """Run a command and return (returncode, stdout, stderr)."""
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    return (
        proc.returncode or 0,
        (stdout or b"").decode(errors="replace").strip(),
        (stderr or b"").decode(errors="replace").strip(),
    )



# ── Public API ────────────────────────────────────────────────────


async def start_capture(
    topology_id: str,
    container_id: str,
    container_name: str,
) -> CaptureSession:
    """Start a Wireshark sidecar for the given container. Returns existing session if active."""
    async with _lock:
        key = (topology_id, container_id)

        # Already running?
        if key in _sessions:
            existing = _sessions[key]
            # Verify docker container is still alive
            rc, _, _ = await _run("sudo", "docker", "inspect", existing.docker_name)
            if rc == 0:
                log.info("Capture already active for %s on port %d", container_name, existing.port)
                return existing
            # Container gone — clean up stale entry
            del _sessions[key]

        port = WIRESHARK_NOVNC_PORT  # always 3000 inside the shared network ns
        docker_name = f"ae3gis-capture-{topology_id[:8]}-{container_id[:12]}"

        # Stop any leftover container with same name
        await _run("sudo", "docker", "rm", "-f", docker_name)

        # Get the target container's IP so we can proxy to it
        rc, ip_out, _ = await _run(
            "sudo", "docker", "inspect", "-f",
            "{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}",
            container_name,
        )
        if rc != 0 or not ip_out:
            raise RuntimeError(f"Cannot determine IP of container {container_name}")
        target_ip = ip_out.strip().split("\n")[0]  # first IP if multiple networks

        log.info("Starting capture for %s (IP %s)", container_name, target_ip)

        # NOTE: --network=container: shares the target's network namespace so
        # Wireshark sees all its interfaces.  -p is NOT allowed with this mode,
        # so we proxy to target_ip:3000 from the backend instead.
        rc, stdout, stderr = await _run(
            "sudo", "docker", "run", "-d", "--rm",
            "--name", docker_name,
            f"--network=container:{container_name}",
            "--cap-add=NET_ADMIN",
            "-e", "PUID=1000",
            "-e", "PGID=1000",
            CAPTURE_IMAGE,
        )

        if rc != 0:
            raise RuntimeError(f"Failed to start capture container: {stderr or stdout}")

        # Return immediately — noVNC readiness is checked via the /ready endpoint
        # so the browser overlay appears without blocking on a 15-second poll.

        # The image may auto-capture on eth0 (management network).
        # Data-plane interfaces are eth1+. Users can switch via
        # Capture > Options in the Wireshark GUI.

        session = CaptureSession(
            topology_id=topology_id,
            container_id=container_id,
            container_name=container_name,
            docker_name=docker_name,
            port=port,
            target_ip=target_ip,
            created_at=time.time(),
        )
        _sessions[key] = session
        log.info("Capture started: %s on port %d", docker_name, port)
        return session


async def stop_capture(topology_id: str, container_id: str) -> None:
    """Stop and remove a capture session."""
    async with _lock:
        key = (topology_id, container_id)
        session = _sessions.pop(key, None)
        if not session:
            return

        log.info("Stopping capture: %s", session.docker_name)
        await _run("sudo", "docker", "rm", "-f", session.docker_name)


def get_session(topology_id: str, container_id: str) -> CaptureSession | None:
    """Return an existing capture session, or None."""
    return _sessions.get((topology_id, container_id))


async def check_ready(topology_id: str, container_id: str) -> bool:
    """Return True if the noVNC port inside the capture container is accepting connections."""
    session = _sessions.get((topology_id, container_id))
    if not session:
        return False
    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(session.target_ip, WIRESHARK_NOVNC_PORT),
            timeout=1.0,
        )
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:
            pass
        return True
    except Exception:
        return False


async def stop_all_for_topology(topology_id: str) -> None:
    """Stop all capture sessions for a topology (called during destroy)."""
    async with _lock:
        to_remove = [k for k in _sessions if k[0] == topology_id]
        for key in to_remove:
            session = _sessions.pop(key)
            log.info("Stopping capture (topology cleanup): %s", session.docker_name)
            await _run("sudo", "docker", "rm", "-f", session.docker_name)


async def export_pcap(topology_id: str, container_id: str) -> tuple[bytes, str]:
    """Find the most recent pcap/pcapng file saved by Wireshark and return its bytes + filename.

    Searches common locations where Wireshark writes captures inside the
    linuxserver/wireshark container.
    """
    session = _sessions.get((topology_id, container_id))
    if not session:
        raise RuntimeError("No active capture session for this container")

    # Find the newest pcap/pcapng file in the container
    # Wireshark saves to /tmp (auto temp files) and /config (user saves)
    rc, found, _ = await _run(
        "sudo", "docker", "exec", session.docker_name,
        "bash", "-c",
        "find /tmp /config /root /home -maxdepth 4 "
        "\\( -name '*.pcap' -o -name '*.pcapng' -o -name '*.cap' \\) "
        "-printf '%T@ %p\\n' 2>/dev/null | sort -rn | head -1",
    )

    if rc != 0 or not found.strip():
        raise RuntimeError("No capture file found — make sure you have an active or saved capture in Wireshark")

    # Parse: "<timestamp> <filepath>"
    parts = found.strip().split(" ", 1)
    if len(parts) < 2:
        raise RuntimeError("No capture file found")
    filepath = parts[1]
    filename = filepath.rsplit("/", 1)[-1]

    # Copy the file out via stdout
    proc = await asyncio.create_subprocess_exec(
        "sudo", "docker", "exec", session.docker_name, "cat", filepath,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    if proc.returncode and proc.returncode != 0:
        raise RuntimeError(f"Failed to read capture file: {(stderr or b'').decode(errors='replace')}")
    if not stdout:
        raise RuntimeError("Capture file is empty")

    return stdout, filename


async def cleanup_stale() -> None:
    """Remove sessions whose Docker containers no longer exist."""
    async with _lock:
        to_remove = []
        for key, session in _sessions.items():
            rc, _, _ = await _run("sudo", "docker", "inspect", session.docker_name)
            if rc != 0:
                to_remove.append(key)

        for key in to_remove:
            session = _sessions.pop(key)
            log.info("Cleaned up stale capture session: %s", session.docker_name)