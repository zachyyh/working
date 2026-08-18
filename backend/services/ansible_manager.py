"""Manage Ansible Provisioning for AE3GIS topologies."""

import yaml
import asyncio
import logging
from pathlib import Path
import json

from config import CLAB_WORKDIR

log = logging.getLogger(__name__)

ANSIBLE_DIR = CLAB_WORKDIR / "ansible"
ANSIBLE_DIR.mkdir(parents=True, exist_ok=True)


def generate_inventory(topology_id: str, topology_data: dict) -> Path:
    """Parses the topology JSON and generates an Ansible inventory file."""
    
    inventory = {
        "all": {
            "children": {
                "web_servers": {"hosts": {}},
                "directory_servers": {"hosts": {}},
                "file_servers": {"hosts": {}},
                "open_canary": {"hosts": {}},
                "honeypots": {"hosts": {}},
                "database_servers": {"hosts": {}},
                "proxy_servers": {"hosts": {}},
            }
        }
    }
    
    topo_name = topology_data.get("name", "ae3gis-topology")
    
    for site in topology_data.get("sites", []):
        for subnet in site.get("subnets", []):
            for container in subnet.get("containers", []):
                
                # Fetch config, but default to an empty dict so we NEVER skip the node
                config = container.get("config") or {}
                
                docker_name = f"clab-{topo_name}-{container['id']}"
                ctype = container.get("type", "").strip()
                
                host_vars = {
                    "ansible_connection": "docker",
                    "ansible_host": docker_name, 
                }
                
                # Merge the user's config directly into the Ansible variables
                host_vars.update(config)

                # Route the host to the strictly correct Ansible group
                if ctype == "web-server":
                    inventory["all"]["children"]["web_servers"]["hosts"][docker_name] = host_vars
                elif ctype == "directory-server":
                    inventory["all"]["children"]["directory_servers"]["hosts"][docker_name] = host_vars
                elif ctype == "file-server": # <-- Route the file servers here
                    inventory["all"]["children"]["file_servers"]["hosts"][docker_name] = host_vars
                elif ctype == "opencanary" or ctype == "honeypot":
                    inventory["all"]["children"]["honeypots"]["hosts"][docker_name] = host_vars
                elif ctype == "database-server": 
                    inventory["all"]["children"]["database_servers"]["hosts"][docker_name] = host_vars
                elif ctype == "proxy":
                    inventory["all"]["children"]["proxy_servers"]["hosts"][docker_name] = host_vars
                

    # DIAGNOSTIC LOG: Prints the exact inventory so we can verify it!
    log.info(f"GENERATED ANSIBLE INVENTORY: {json.dumps(inventory, indent=2)}")

    inventory_path = ANSIBLE_DIR / f"{topology_id}_inventory.yml"
    with open(inventory_path, "w") as f:
        yaml.dump(inventory, f, default_flow_style=False)

    return inventory_path


async def run_provisioning(topology_id: str, topology_data: dict) -> None:
    """Generates the inventory and runs the Ansible playbook."""
    
    log.info(f"Starting Config Provisioning for topology {topology_id}...")
    
    # 1. Generate the dynamic inventory
    inventory_path = generate_inventory(topology_id, topology_data)
    
    # 2. Define the path to our static playbook 
    backend_root = Path(__file__).parent.parent
    playbook_path = backend_root / "ansible" / "deploy_configs.yml"
    
    if not playbook_path.exists():
        log.warning(f"Playbook not found at {playbook_path}. Skipping config provisioning.")
        return

    # 3. Execute Ansible using the subprocess module
    cmd = [
        "ansible-playbook",
        "-i", str(inventory_path),
        str(playbook_path)
    ]
    
    log.info(f"Running Ansible: {' '.join(cmd)}")
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    
    stdout, stderr = await proc.communicate()
    
    if proc.returncode == 0:
        log.info(f"Config Provisioning Successful!\n{stdout.decode()}")
    else:
        log.error(f"Config Provisioning Failed!\n{stderr.decode()}\n{stdout.decode()}")