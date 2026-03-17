# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# hook-runtime-client.sh — thin shell client for hook runtime daemon [OMN-5308]
#
# Sends a newline-delimited JSON request to the Unix socket daemon and prints
# the JSON response line.  Falls back gracefully (returns pass) if daemon is
# not running or times out.
#
# Usage (source this file, then call _hrt_request):
#   source /path/to/hook-runtime-client.sh
#   RESPONSE=$(_hrt_request '{"action":"ping","session_id":"s1","payload":{}}')
#
# Mirrors emit_client_wrapper.py _SocketEmitClient pattern but in bash.
# Uses a Python one-liner for Unix socket I/O (socat not available on stock macOS).

HOOK_RUNTIME_SOCKET="${HOOK_RUNTIME_SOCKET:-/tmp/omniclaude-hook-runtime.sock}"

# Resolve Python interpreter: prefer PYTHON env var, fall back to python3
_HRT_PYTHON="${PYTHON:-python3}"

# _hrt_request <json_payload>
# Sends json_payload + newline to the daemon socket, prints the response line.
# On any error (daemon not running, timeout, parse failure) prints the pass-through
# fallback JSON so callers always get a parseable response.
_hrt_request() {
    local json_payload="$1"
    local _HRT_FALLBACK='{"decision":"pass","message":null,"counters":{}}'

    if [[ ! -S "$HOOK_RUNTIME_SOCKET" ]]; then
        printf '%s\n' "$_HRT_FALLBACK"
        return 0
    fi

    local response
    response=$("$_HRT_PYTHON" -c "
import socket, sys, json

sock_path = sys.argv[1]
payload   = sys.argv[2]
fallback  = '{\"decision\":\"pass\",\"message\":null,\"counters\":{}}'

s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
s.settimeout(0.5)
try:
    s.connect(sock_path)
    s.sendall((payload + '\n').encode())
    line = s.makefile().readline().strip()
    print(line if line else fallback)
except Exception:
    print(fallback)
finally:
    try:
        s.close()
    except Exception:
        pass
" "$HOOK_RUNTIME_SOCKET" "$json_payload" 2>/dev/null) || true

    printf '%s\n' "${response:-$_HRT_FALLBACK}"
}
