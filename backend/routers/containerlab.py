import asyncio
import contextlib
import fcntl
import json
import logging
import os
import pty
import signal
import struct
import termios
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, WebSocket, WebSocketDisconnect
from sqlalchemy.orm import Session

from auth import (
    AuthIdentity,
    require_any_auth,
    require_instructor,
    validate_student_topology,
)
from config import INSTRUCTOR_TOKEN
from database import get_db
from models import StudentSlot, Topology
from schemas import FirewallRulesResponse, FirewallRulesUpdate
from services import capture_manager, clab_generator, clab_manager, ansible_manager
from services.exec_session_manager import exec_session_manager

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/topologies", tags=["containerlab"])


# ── Helpers ─────────────────────────────────────────────────────────


def _get_topo(topology_id: str, db: Session) -> Topology:
    topo = db.get(Topology, topology_id)
    if not topo:
        raise HTTPException(404, "Topology not found")
    return topo


def _topo_name(topo: Topology) -> str:
    """Return the clab topology name (used for inspect)."""
    return clab_manager.deployment_name(topo.id, topo.data)


def _find_container(topo: Topology, container_id: str) -> dict[str, Any] | None:
    data = topo.data or {}
    for site in data.get("sites", []):
        for subnet in site.get("subnets", []):
            for container in subnet.get("containers", []):
                if container.get("id") == container_id:
                    return container
    return None


def _validate_ws_token(token: str | None, topology_id: str, db: Session) -> bool:
    """Validate a WebSocket token (query param) for the given topology."""
    if not token:
        return False
    if token == INSTRUCTOR_TOKEN:
        return True
    slot = db.query(StudentSlot).filter(StudentSlot.join_code == token).first()
    return slot is not None and slot.topology_id == topology_id


def _interactive_shell_command() -> list[str]:
    """Prefer a richer interactive shell when the container provides one."""
    return [
        "sh",
        "-lc",
        (
            "mkdir -p /tmp; "
            "printf 'set horizontal-scroll-mode Off\nset enable-bracketed-paste Off\n' >/tmp/ae3gis.inputrc 2>/dev/null || true; "
            "export INPUTRC=/tmp/ae3gis.inputrc; "
            "if command -v bash >/dev/null 2>&1; then "
            "exec bash -il; "
            "elif command -v ash >/dev/null 2>&1; then "
            "exec ash -l; "
            "else "
            "exec sh -l; "
            "fi"
        ),
    ]


# ── Available Scripts ───────────────────────────────────────────────


@router.get("/scripts/available")
def list_available_scripts(
    _=Depends(require_instructor),
):
    """Return all scripts available for mounting, grouped by container type."""
    from services.clab_generator import SCRIPTS_DIR, _SCRIPT_TYPE_MAP

    # Invert the map: script_dir -> [container_types]
    dir_to_types: dict[str, list[str]] = {}
    for ctype, sdir in _SCRIPT_TYPE_MAP.items():
        dir_to_types.setdefault(sdir, []).append(ctype)

    results: list[dict[str, Any]] = []
    if SCRIPTS_DIR.exists():
        for script_dir in sorted(SCRIPTS_DIR.iterdir()):
            if not script_dir.is_dir():
                continue
            dir_name = script_dir.name
            container_types = dir_to_types.get(dir_name, [])
            for script_file in sorted(script_dir.rglob("*.sh")):
                rel = script_file.relative_to(script_dir)
                results.append({
                    "path": f"/scripts/{dir_name}/{rel}",
                    "scriptDir": dir_name,
                    "containerTypes": container_types,
                    "filename": script_file.name,
                })

    return {"scripts": results}


# ── Generate ────────────────────────────────────────────────────────


@router.post("/{topology_id}/generate")
def generate(
    topology_id: str,
    db: Session = Depends(get_db),
    _=Depends(require_instructor),
):
    topo = _get_topo(topology_id, db)
    topo_data = {**topo.data, "name": _topo_name(topo)}
    yaml_str = clab_generator.generate_clab_yaml(topo_data, topology_id=topology_id)
    clab_manager.write_yaml(topology_id, yaml_str)

    topo.clab_yaml = yaml_str
    db.commit()

    return {"yaml": yaml_str}


# ── Deploy ──────────────────────────────────────────────────────────


@router.post("/{topology_id}/deploy")
async def deploy(
    topology_id: str,
    db: Session = Depends(get_db),
    _=Depends(require_instructor),
):
    topo = _get_topo(topology_id, db)

    try:
        # Always regenerate YAML from current topology data
        topo_data = {**topo.data, "name": _topo_name(topo)}
        yaml_str = clab_generator.generate_clab_yaml(topo_data, topology_id=topology_id)
        log.info("Generated YAML for %s (%d bytes)", topology_id, len(yaml_str))

        yaml_path = clab_manager.write_yaml(topology_id, yaml_str)

        # Verify what was written to disk matches what was generated
        written = yaml_path.read_text()
        if written != yaml_str:
            log.error("YAML write verification FAILED for %s", topology_id)
            raise RuntimeError("YAML written to disk does not match generated content")
        log.info("YAML write verified OK for %s", topology_id)

        topo.clab_yaml = yaml_str
        await clab_manager.pull_images(topo_data)
        await clab_manager.prepare_persistence_paths(topology_id, topo_data)

        # 1. Start the ContainerLab deployment
        output = await clab_manager.deploy(topology_id)
        
        # 2. Run Ansible Config provisioning on the newly created containers
        await ansible_manager.run_provisioning(topology_id, topo_data)

        topo.status = "deployed"
        db.commit()
        return {"status": "deployed", "output": output}
    except Exception as e:
        log.exception("Deploy failed for %s: %s: %s", topology_id, type(e).__name__, e)
        topo.status = "error"
        db.commit()
        raise HTTPException(500, f"{type(e).__name__}: {e}")

# ── Destroy ─────────────────────────────────────────────────────────


@router.post("/{topology_id}/destroy")
async def destroy(
    topology_id: str,
    db: Session = Depends(get_db),
    _=Depends(require_instructor),
):
    topo = _get_topo(topology_id, db)

    try:
        # Stop any active capture sessions before destroying containers
        await capture_manager.stop_all_for_topology(topology_id)
        output = await clab_manager.destroy(topology_id)
        topo.status = "idle"
        db.commit()
        return {"status": "destroyed", "output": output}
    except (FileNotFoundError, RuntimeError) as e:
        print(f"[ERROR] destroy topology {topology_id}: {e}")
        topo.status = "error"
        db.commit()
        raise HTTPException(500, str(e))


# ── Status (single request) ────────────────────────────────────────


@router.get("/{topology_id}/status")
async def status(
    topology_id: str,
    db: Session = Depends(get_db),
    identity: AuthIdentity = Depends(require_any_auth),
):
    validate_student_topology(identity, topology_id)
    topo = _get_topo(topology_id, db)
    containers = await clab_manager.inspect(_topo_name(topo))
    return {"status": topo.status, "containers": containers}


# ── Status (WebSocket stream) ──────────────────────────────────────


@router.websocket("/ws/{topology_id}/status")
async def status_stream(
    websocket: WebSocket,
    topology_id: str,
    token: str | None = Query(default=None),
):
    db = next(get_db())
    try:
        if not _validate_ws_token(token, topology_id, db):
            await websocket.close(code=4003, reason="Forbidden")
            return

        topo = db.get(Topology, topology_id)
        if not topo:
            await websocket.close(code=4004, reason="Topology not found")
            return

        await websocket.accept()
        topo_name = _topo_name(topo)

        while True:
            containers = await clab_manager.inspect(topo_name)
            await websocket.send_json({
                "status": topo.status,
                "containers": containers,
            })
            await asyncio.sleep(5)
    except WebSocketDisconnect:
        pass
    finally:
        db.close()


# ── Interactive exec terminal ──────────────────────────────────


@router.websocket("/ws/{topology_id}/exec/{container_id}")
async def exec_terminal(
    websocket: WebSocket,
    topology_id: str,
    container_id: str,
    token: str | None = Query(default=None),
):
    """Attach an interactive shell session inside a deployed container via PTY."""
    db = next(get_db())
    proc = None
    master_fd = -1

    def _resize_exec_pty(cols: int, rows: int) -> None:
        nonlocal proc, master_fd
        cols = max(1, int(cols))
        rows = max(1, int(rows))
        fcntl.ioctl(master_fd, termios.TIOCSWINSZ, struct.pack('HHHH', rows, cols, 0, 0))
        if proc is not None and proc.returncode is None:
            with contextlib.suppress(ProcessLookupError):
                proc.send_signal(signal.SIGWINCH)

    try:
        # minimal logging; token/topology errors are handled inline
        if not _validate_ws_token(token, topology_id, db):
            await websocket.close(code=4003, reason="Forbidden")
            return

        topo = db.get(Topology, topology_id)
        await websocket.accept()
        if not topo:
            await websocket.send_text("Error: Topology not found\r\n")
            await websocket.close(code=4004)
            return

        topo_name = _topo_name(topo)
        docker_name = f"clab-{topo_name}-{container_id}"

        await websocket.send_text(f"Connecting to {docker_name}...\r\n")
        log.debug("exec_terminal: accepted websocket for %s/%s", topology_id, container_id)

        # Allocate a PTY pair — pass the slave end to the subprocess so that
        # `docker exec -it` sees a real TTY on its stdin and doesn't error out.
        master_fd, slave_fd = pty.openpty()
        # Set a sensible default terminal size (client will send a resize immediately)
        _resize_exec_pty(80, 24)
        try:
            proc = await asyncio.create_subprocess_exec(
                "sudo",
                "docker",
                "exec",
                "-e",
                "TERM=xterm-256color",
                "-e",
                "COLUMNS=80",
                "-e",
                "LINES=24",
                "-it",
                docker_name,
                *_interactive_shell_command(),
                stdin=slave_fd,
                stdout=slave_fd,
                stderr=slave_fd,
            )
        except Exception as exc:
            log.exception("exec_terminal: subprocess launch failed")
            await websocket.send_text(f"Error starting exec: {exc}\r\n")
            await websocket.close()
            return
        finally:
            os.close(slave_fd)  # Parent only communicates via master_fd

        loop = asyncio.get_running_loop()
        read_queue: asyncio.Queue[bytes] = asyncio.Queue()

        def _on_readable() -> None:
            try:
                data = os.read(master_fd, 4096)
                read_queue.put_nowait(data if data else b"")
            except OSError:
                read_queue.put_nowait(b"")
                loop.remove_reader(master_fd)

        loop.add_reader(master_fd, _on_readable)

        async def _read_pty() -> None:
            while True:
                data = await read_queue.get()
                if not data:
                    break
                try:
                    # Use send_bytes to avoid repeatedly decoding/encoding large output
                    await websocket.send_bytes(data)
                except Exception as e:
                    log.exception("exec_terminal read loop send error:")
                    break

        async def _write_pty() -> None:
            while True:
                try:
                    msg = await websocket.receive()
                    # the dict may contain 'bytes' or 'text'; ignore other event types
                    if msg.get('type') != 'websocket.receive':
                        # connection closed or ping/pong; loop back
                        if msg.get('type') in ("websocket.disconnect", "websocket.close"):
                            break
                        continue
                    data = msg.get('bytes') if msg.get('bytes') is not None else msg.get('text', "")
                    if isinstance(data, str):
                        data = data.encode('utf-8')
                    # handle resize messages sent as JSON
                    try:
                        payload = json.loads(data.decode('utf-8', 'ignore'))
                        if isinstance(payload, dict) and payload.get('type') == 'resize':
                            cols = max(1, int(payload.get('cols', 80)))
                            rows = max(1, int(payload.get('rows', 24)))
                            _resize_exec_pty(cols, rows)
                            continue
                    except (json.JSONDecodeError, TypeError, ValueError):
                        pass
                    os.write(master_fd, data)
                except WebSocketDisconnect:
                    break
                except Exception:
                    log.exception("exec_terminal write loop error:")
                    break

        read_task = asyncio.create_task(_read_pty())
        write_task = asyncio.create_task(_write_pty())
        # heartbeat to keep intermediate proxies happy
        async def _ping() -> None:
            try:
                while True:
                    await asyncio.sleep(15)
                    await websocket.send_json({"type": "ping"})
            except Exception:
                pass
        ping_task = asyncio.create_task(_ping())
        try:
            await asyncio.wait([read_task, write_task], return_when=asyncio.FIRST_COMPLETED)
        finally:
            loop.remove_reader(master_fd)
            read_task.cancel()
            write_task.cancel()
            ping_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await read_task
            with contextlib.suppress(asyncio.CancelledError):
                await write_task

        # Send a clean close so the browser gets onclose instead of onerror
        with contextlib.suppress(Exception):
            await websocket.send_text("\r\n[session ended]\r\n")
            await websocket.close()

    except WebSocketDisconnect:
        pass
    finally:
        if master_fd >= 0:
            with contextlib.suppress(OSError):
                os.close(master_fd)
        if proc and proc.returncode is None:
            proc.terminate()
            with contextlib.suppress(asyncio.TimeoutError):
                await asyncio.wait_for(proc.wait(), timeout=2.0)
        db.close()


# ── Topology notification channel ────────────────────────────────────


@router.websocket("/ws/{topology_id}/notify")
async def topology_notify(
    websocket: WebSocket,
    topology_id: str,
    token: str | None = Query(default=None),
):
    """Push-only channel used to notify students when a phase is executed on their topology."""
    db = next(get_db())
    q = None
    try:
        if not _validate_ws_token(token, topology_id, db):
            await websocket.close(code=4003, reason="Forbidden")
            return

        await websocket.accept()
        q = exec_session_manager.register_notify(topology_id)

        async def _ping() -> None:
            try:
                while True:
                    await asyncio.sleep(15)
                    await websocket.send_json({"type": "ping"})
            except Exception:
                pass

        ping_task = asyncio.create_task(_ping())
        try:
            while True:
                try:
                    msg = await asyncio.wait_for(q.get(), timeout=30.0)
                    await websocket.send_json(msg)
                except asyncio.TimeoutError:
                    continue
        except (WebSocketDisconnect, Exception):
            pass
        finally:
            ping_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await ping_task
    finally:
        if q is not None:
            exec_session_manager.unregister_notify(topology_id, q)
        db.close()


# ── Exec session terminal (for pushed scripts) ───────────────────────


@router.websocket("/ws/{topology_id}/exec-session/{session_id}")
async def exec_session_terminal(
    websocket: WebSocket,
    topology_id: str,
    session_id: str,
    token: str | None = Query(default=None),
):
    """Attach to a running PTY exec session created by a pushed scenario phase.

    Both students and instructors can connect.  Buffered output is replayed
    on connect so late joiners see what they missed.  Keystrokes are
    forwarded to the running process (interactive scripts are supported).
    """
    db = next(get_db())
    try:
        if not _validate_ws_token(token, topology_id, db):
            await websocket.close(code=4003, reason="Forbidden")
            return

        await websocket.accept()

        ok = await exec_session_manager.subscribe(session_id, websocket)
        if not ok:
            await websocket.send_text("Error: session not found or already expired\r\n")
            await websocket.close(code=4004)
            return

        async def _ping() -> None:
            try:
                while True:
                    await asyncio.sleep(15)
                    await websocket.send_json({"type": "ping"})
            except Exception:
                pass

        ping_task = asyncio.create_task(_ping())
        try:
            while True:
                try:
                    msg = await websocket.receive()
                except WebSocketDisconnect:
                    break
                if msg.get("type") in ("websocket.disconnect", "websocket.close"):
                    break
                if msg.get("type") != "websocket.receive":
                    continue
                raw = msg.get("bytes") if msg.get("bytes") is not None else msg.get("text", "")
                if isinstance(raw, str):
                    raw = raw.encode("utf-8")
                # Resize control message
                try:
                    payload = json.loads(raw.decode("utf-8", "ignore"))
                    if isinstance(payload, dict) and payload.get("type") == "resize":
                        cols = max(1, int(payload.get("cols", 80)))
                        rows = max(1, int(payload.get("rows", 24)))
                        exec_session_manager.resize(session_id, cols, rows)
                        continue
                except (json.JSONDecodeError, TypeError, ValueError):
                    pass
                exec_session_manager.write_input(session_id, raw)
        finally:
            ping_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await ping_task
    except WebSocketDisconnect:
        pass
    finally:
        exec_session_manager.unsubscribe(session_id, websocket)
        db.close()


@router.get("/{topology_id}/exec/{container_id}/precheck")
async def exec_precheck(
    topology_id: str,
    container_id: str,
    db: Session = Depends(get_db),
    identity: AuthIdentity = Depends(require_any_auth),
) -> dict[str, Any]:
    """Validate docker exec prerequisites and return a reason code for UI diagnostics."""
    validate_student_topology(identity, topology_id)
    topo = _get_topo(topology_id, db)
    topo_name = _topo_name(topo)
    docker_name = f"clab-{topo_name}-{container_id}"

    try:
        proc = await asyncio.create_subprocess_exec(
            "sudo", "-n", "docker", "inspect", docker_name,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except Exception as exc:
        return {
            "reason": "docker_inspect_failed",
            "detail": str(exc),
            "docker_name": docker_name,
        }

    _stdout, stderr = await proc.communicate()
    detail = (stderr or b"").decode(errors="replace").strip()
    detail_l = detail.lower()

    if proc.returncode == 0:
        return {"reason": "ok", "docker_name": docker_name}

    if "permission denied" in detail_l or "password is required" in detail_l:
        return {
            "reason": "docker_permission_denied",
            "detail": detail or "docker permission denied",
            "docker_name": docker_name,
        }

    if "no such object" in detail_l or "no such container" in detail_l:
        return {
            "reason": "container_not_found",
            "detail": detail or "container not found",
            "docker_name": docker_name,
        }

    return {
        "reason": "docker_inspect_failed",
        "detail": detail or f"docker inspect failed with return code {proc.returncode}",
        "docker_name": docker_name,
    }


@router.post("/{topology_id}/scenarios/{scenario_id}/phases/{phase_id}/execute")
async def execute_phase(
    topology_id: str,
    scenario_id: str,
    phase_id: str,
    db: Session = Depends(get_db),
    _=Depends(require_instructor),
):
    """Execute all script actions in a given attack phase."""
    topo = _get_topo(topology_id, db)
    if topo.status != "deployed":
        raise HTTPException(409, "Topology is not deployed")

    data = topo.data or {}
    scenarios = data.get("scenarios") or []
    scenario = next((s for s in scenarios if s.get("id") == scenario_id), None)
    if not scenario:
        raise HTTPException(404, "Scenario not found")
    phase = next((p for p in scenario.get("phases", []) if p.get("id") == phase_id), None)
    if not phase:
        raise HTTPException(404, "Phase not found")

    topo_name = _topo_name(topo)
    results: list[dict[str, Any]] = []

    for execution in phase.get("executions", []):
        container_id = execution.get("containerId", "")
        script = execution.get("script", "")
        args = execution.get("args") or []

        if not container_id or not script:
            results.append({
                "containerId": container_id,
                "script": script,
                "returncode": -1,
                "stdout": "",
                "stderr": "Missing containerId or script",
            })
            continue

        docker_name = f"clab-{topo_name}-{container_id}"
        cmd = [script, *args]
        env = clab_manager.build_topology_env(data, container_id)
        rc, stdout, stderr = await clab_manager._docker_exec(docker_name, cmd, env=env)
        results.append({
            "containerId": container_id,
            "script": script,
            "returncode": rc,
            "stdout": stdout,
            "stderr": stderr,
        })
        log.info(
            "Phase %s execution on %s: %s -> rc=%d",
            phase.get("name"), container_id, script, rc,
        )

    return {"phase_id": phase_id, "results": results}


@router.get("/{topology_id}/firewall/{container_id}", response_model=FirewallRulesResponse)
async def get_firewall_rules(
    topology_id: str,
    container_id: str,
    db: Session = Depends(get_db),
    identity: AuthIdentity = Depends(require_any_auth),
):
    validate_student_topology(identity, topology_id)
    topo = _get_topo(topology_id, db)
    container = _find_container(topo, container_id)
    if not container:
        raise HTTPException(404, "Container not found")
    if container.get("type") not in {"router", "firewall"}:
        raise HTTPException(400, "Firewall rules are only supported on router/firewall containers")
    if topo.status != "deployed":
        raise HTTPException(409, "Topology is not deployed")

    try:
        rules = await clab_manager.get_firewall_rules(_topo_name(topo), container_id)
        return {"rules": rules}
    except RuntimeError as exc:
        raise HTTPException(500, str(exc))


@router.put("/{topology_id}/firewall/{container_id}", response_model=FirewallRulesResponse)
async def put_firewall_rules(
    topology_id: str,
    container_id: str,
    body: FirewallRulesUpdate,
    db: Session = Depends(get_db),
    _=Depends(require_instructor),
):
    topo = _get_topo(topology_id, db)
    container = _find_container(topo, container_id)
    if not container:
        raise HTTPException(404, "Container not found")
    if container.get("type") not in {"router", "firewall"}:
        raise HTTPException(400, "Firewall rules are only supported on router/firewall containers")
    if topo.status != "deployed":
        raise HTTPException(409, "Topology is not deployed")

    try:
        rules = await clab_manager.apply_firewall_rules(
            _topo_name(topo),
            container_id,
            [r.model_dump() for r in body.rules],
        )
        return {"rules": rules}
    except RuntimeError as exc:
        raise HTTPException(500, str(exc))


# ── Packet Capture (Wireshark in browser) ─────────────────────────


@router.post("/{topology_id}/capture/{container_id}/start")
async def start_capture(
    topology_id: str,
    container_id: str,
    db: Session = Depends(get_db),
    identity: AuthIdentity = Depends(require_any_auth),
):
    validate_student_topology(identity, topology_id)
    topo = _get_topo(topology_id, db)
    if topo.status != "deployed":
        raise HTTPException(409, "Topology is not deployed")
    container = _find_container(topo, container_id)
    if not container:
        raise HTTPException(404, "Container not found")

    topo_name = _topo_name(topo)
    docker_name = f"clab-{topo_name}-{container_id}"

    try:
        session = await capture_manager.start_capture(topology_id, container_id, docker_name)
        return {
            "status": "started",
            "port": session.port,
            "url": f"/api/topologies/{topology_id}/capture/{container_id}/view/",
        }
    except RuntimeError as exc:
        raise HTTPException(500, str(exc))


@router.post("/{topology_id}/capture/{container_id}/prewarm")
async def prewarm_capture(
    topology_id: str,
    container_id: str,
    db: Session = Depends(get_db),
    identity: AuthIdentity = Depends(require_any_auth),
):
    """Start the Wireshark sidecar in the background so it's ready when the user opens capture.
    Returns immediately — use the /ready endpoint to poll for readiness."""
    validate_student_topology(identity, topology_id)
    topo = _get_topo(topology_id, db)
    if topo.status != "deployed":
        return {"status": "skipped", "reason": "not deployed"}

    # Already running
    if capture_manager.get_session(topology_id, container_id):
        return {"status": "already_running"}

    container = _find_container(topo, container_id)
    if not container:
        return {"status": "skipped", "reason": "container not found"}

    topo_name = _topo_name(topo)
    docker_name = f"clab-{topo_name}-{container_id}"

    # Fire and forget — don't await
    asyncio.create_task(capture_manager.start_capture(topology_id, container_id, docker_name))
    return {"status": "starting"}


@router.post("/{topology_id}/capture/{container_id}/stop")
async def stop_capture_endpoint(
    topology_id: str,
    container_id: str,
    db: Session = Depends(get_db),
    identity: AuthIdentity = Depends(require_any_auth),
):
    validate_student_topology(identity, topology_id)
    _get_topo(topology_id, db)
    await capture_manager.stop_capture(topology_id, container_id)
    return {"status": "stopped"}


@router.get("/{topology_id}/capture/{container_id}/status")
async def capture_status(
    topology_id: str,
    container_id: str,
    db: Session = Depends(get_db),
    identity: AuthIdentity = Depends(require_any_auth),
):
    validate_student_topology(identity, topology_id)
    _get_topo(topology_id, db)
    session = capture_manager.get_session(topology_id, container_id)
    return {"active": session is not None, "port": session.port if session else None}


@router.get("/{topology_id}/capture/{container_id}/ready")
async def capture_ready(
    topology_id: str,
    container_id: str,
    identity: AuthIdentity = Depends(require_any_auth),
):
    """Lightweight readiness probe — returns {ready: true} once noVNC is accepting connections."""
    validate_student_topology(identity, topology_id)
    ready = await capture_manager.check_ready(topology_id, container_id)
    return {"ready": ready}


@router.get("/{topology_id}/capture/{container_id}/download")
async def capture_download_pcap(
    topology_id: str,
    container_id: str,
    db: Session = Depends(get_db),
    identity: AuthIdentity = Depends(require_any_auth),
):
    """Download the most recent capture file from the Wireshark GUI session."""
    from fastapi.responses import Response

    validate_student_topology(identity, topology_id)
    topo = _get_topo(topology_id, db)
    if topo.status != "deployed":
        raise HTTPException(409, "Topology is not deployed")

    try:
        pcap_bytes, filename = await capture_manager.export_pcap(
            topology_id, container_id,
        )
    except RuntimeError as exc:
        raise HTTPException(404, str(exc))

    return Response(
        content=pcap_bytes,
        media_type="application/vnd.tcpdump.pcap",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.api_route(
    "/{topology_id}/capture/{container_id}/view/{path:path}",
    methods=["GET", "POST", "PUT", "DELETE", "OPTIONS", "HEAD", "PATCH"],
)
async def capture_proxy_http(
    topology_id: str,
    container_id: str,
    path: str,
    request: Request,
    token: str | None = Query(default=None),
):
    """Reverse-proxy HTTP requests to the Wireshark noVNC container."""
    # Auth via query param, or fall back to token in the Referer URL
    # (sub-resources loaded by the iframe won't have ?token= themselves)
    effective_token = token
    if not effective_token:
        from urllib.parse import parse_qs, urlparse
        referer = request.headers.get("referer", "")
        qs = parse_qs(urlparse(referer).query)
        effective_token = qs.get("token", [None])[0]

    db = next(get_db())
    try:
        if not _validate_ws_token(effective_token, topology_id, db):
            raise HTTPException(403, "Forbidden")
    finally:
        db.close()

    session = capture_manager.get_session(topology_id, container_id)
    if not session:
        raise HTTPException(404, "No active capture session")

    import httpx
    from fastapi.responses import StreamingResponse

    target_url = f"http://{session.target_ip}:{session.port}/{path}"
    query_params = dict(request.query_params)
    query_params.pop("token", None)

    excluded_headers = ["host", "content-length"]
    headers = {k: v for k, v in request.headers.items() if k.lower() not in excluded_headers}

    client = httpx.AsyncClient()
    try:
        req = client.build_request(
            method=request.method,
            url=target_url,
            params=query_params,
            headers=headers,
            content=request.stream(),
        )
        response = await client.send(req, stream=True)
        return StreamingResponse(
            response.aiter_raw(),
            status_code=response.status_code,
            headers={k: v for k, v in response.headers.items() if k.lower() not in ["transfer-encoding"]},
            background=response.aclose,
        )
    except httpx.RequestError as e:
        await client.aclose()
        raise HTTPException(502, f"Failed to proxy to Wireshark: {e}")


@router.websocket("/{topology_id}/capture/{container_id}/view/{path:path}")
async def capture_proxy_ws_view(
    websocket: WebSocket,
    topology_id: str,
    container_id: str,
    path: str,
    token: str | None = Query(default=None),
):
    """WebSocket proxy for noVNC requests coming through the /view/ path."""
    return await _capture_ws_proxy(websocket, topology_id, container_id, path, token)


async def _capture_ws_proxy(
    websocket: WebSocket,
    topology_id: str,
    container_id: str,
    path: str,
    token: str | None,
):
    """Shared WebSocket proxy logic for Wireshark noVNC."""
    db = next(get_db())
    try:
        if not _validate_ws_token(token, topology_id, db):
            await websocket.close(code=4003, reason="Forbidden")
            return
    finally:
        db.close()

    session = capture_manager.get_session(topology_id, container_id)
    if not session:
        await websocket.close(code=4004, reason="No active capture session")
        return

    await websocket.accept()

    import websockets

    ws_url = f"ws://{session.target_ip}:{session.port}/{path}"
    try:
        async with websockets.connect(ws_url, subprotocols=["binary"]) as upstream:
            async def _forward_to_upstream():
                try:
                    while True:
                        msg = await websocket.receive()
                        if msg.get("type") == "websocket.disconnect":
                            break
                        if msg.get("bytes") is not None:
                            await upstream.send(msg["bytes"])
                        elif msg.get("text") is not None:
                            await upstream.send(msg["text"])
                except (WebSocketDisconnect, Exception):
                    pass

            async def _forward_from_upstream():
                try:
                    async for message in upstream:
                        if isinstance(message, bytes):
                            await websocket.send_bytes(message)
                        else:
                            await websocket.send_text(message)
                except (WebSocketDisconnect, Exception):
                    pass

            tasks = [
                asyncio.create_task(_forward_to_upstream()),
                asyncio.create_task(_forward_from_upstream()),
            ]
            await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for t in tasks:
                t.cancel()
    except Exception as e:
        log.warning("Capture WebSocket proxy error: %s", e)
    finally:
        with contextlib.suppress(Exception):
            await websocket.close()


@router.websocket("/ws/{topology_id}/capture/{container_id}/{path:path}")
async def capture_proxy_ws(
    websocket: WebSocket,
    topology_id: str,
    container_id: str,
    path: str,
    token: str | None = Query(default=None),
):
    """Reverse-proxy WebSocket connections to the Wireshark noVNC container."""
    return await _capture_ws_proxy(websocket, topology_id, container_id, path, token)
