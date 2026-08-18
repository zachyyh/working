#!/usr/bin/env bash
# Single entry point: fixes a couple of known WSL/Docker Desktop quirks for
# this user on this machine (idempotent -- safe to run every time), then
# brings up the stack.

set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"

# --- Fix 1: passwordless sudo for containerlab -----------------------------
if ! sudo -n containerlab version >/dev/null 2>&1; then
    echo "First-time setup: granting this user passwordless sudo for containerlab."
    echo "You'll be asked for your password once -- after this, it won't ask again."
    ./scripts/setup-sudoers.sh
fi

# --- Fix 2: broken Docker credsStore under WSL ------------------------------
# Docker Desktop for Windows often writes ~/.docker/config.json pointing at
# a Windows credential helper (docker-credential-desktop[.exe]). The binary
# is usually present on PATH inside WSL (Docker Desktop adds it), but it
# fails when actually invoked from WSL's Linux environment -- "exec format
# error" or a nonzero exit -- because it's a Windows binary running through
# an interop layer that doesn't reliably support this use. Since we only
# ever pull public images and never need stored credentials at all, if we
# detect that specific broken combination, back up the file and strip just
# the credsStore key -- nothing else in it is touched.
DOCKER_CONFIG_FILE="$HOME/.docker/config.json"
if [ -f "$DOCKER_CONFIG_FILE" ] && grep -q '"credsStore"[[:space:]]*:[[:space:]]*"desktop' "$DOCKER_CONFIG_FILE" 2>/dev/null; then
    HELPER="$(python3 -c "import json; print(json.load(open('$DOCKER_CONFIG_FILE')).get('credsStore',''))")"
    HELPER_BIN="docker-credential-${HELPER}"
    HELPER_WORKS=false
    if command -v "$HELPER_BIN" >/dev/null 2>&1; then
        if echo "https://index.docker.io/v1/" | "$HELPER_BIN" get >/dev/null 2>&1; then
            HELPER_WORKS=true
        fi
    fi
    if [ "$HELPER_WORKS" = false ]; then
        echo "Detected a broken Docker credsStore setting (the '$HELPER' credential"
        echo "helper is on PATH but doesn't actually run from inside WSL). Backing up"
        echo "config and removing the broken credsStore entry -- no other Docker"
        echo "settings are touched."
        cp "$DOCKER_CONFIG_FILE" "$DOCKER_CONFIG_FILE.bak"
        python3 - "$DOCKER_CONFIG_FILE" << 'PYEOF'
import json, sys
path = sys.argv[1]
with open(path) as f:
    data = json.load(f)
data.pop("credsStore", None)
with open(path, "w") as f:
    json.dump(data, f, indent=2)
PYEOF
        echo "Done. Original saved to $DOCKER_CONFIG_FILE.bak"
    fi
fi

python3 frontend/src/components/dynamicFrontendGenerator.py

docker compose up --build
