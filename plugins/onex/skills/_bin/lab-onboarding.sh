#!/bin/bash
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
# Compatibility bootstrap: ONEX owns every setup operation.
set -eo pipefail

usage() {
  cat <<'HELP'
Welcome To OmniNode Delegation Onboarding

Usage: lab-onboarding.sh [bootstrap options] [onex setup options]

An installed ONEX CLI runs directly. To install a selected release or local
wheel, explicitly supply --install-package PACKAGE and an existing uv tool.
  --install-package PACKAGE  Install that package with the ONEX executable.
  Python 3.12 must already be available; bootstrap never downloads Python.
  --help                     Show this help.

No repositories, model runtimes, models, or system tools are downloaded by this
script. Ollama runs separately: supply its endpoint and select a discovered model
through onex setup. Use "onex setup --help" for the current setup options.

Legacy aliases: --no-containers/--containers -> --path local/docker,
--local-url/--compat-url -> --url, --local-model/--ollama-model -> --model,
--restart -> --action repair. --set-aside forwards to the CLI recovery owner.
HELP
}

package=""
args=()
while [[ $# -gt 0 ]]; do
  case "$1" in
    --install-package|--local-url|--compat-url|--local-model|--ollama-model)
      option="$1"
      if [[ $# -lt 2 || -z "$2" || "$2" == --* ]]; then
        echo "$option requires a value" >&2
        exit 2
      fi
      case "$option" in
        --install-package) package="$2" ;;
        --local-url|--compat-url) args+=("--url" "$2") ;;
        *) args+=("--model" "$2") ;;
      esac
      shift 2 ;;
    --install-package=*) package="${1#*=}"; shift ;;
    --bootstrap-python|--bootstrap-python=*) echo "Bootstrap supports existing Python 3.12 only; remove --bootstrap-python." >&2; exit 2 ;;
    --local-url=*|--compat-url=*) args+=("--url" "${1#*=}"); shift ;;
    --local-model=*|--ollama-model=*) args+=("--model" "${1#*=}"); shift ;;
    --containers) args+=("--path" "docker"); shift ;;
    --no-containers) args+=("--path" "local"); shift ;;
    --restart) args+=("--action" "repair"); shift ;;
    --set-aside) args+=("--set-aside"); shift ;;
    -h|--help) usage; exit 0 ;;
    *) args+=("$1"); shift ;;
  esac
done

if [[ -n "$package" ]]; then
  if ! command -v uv >/dev/null 2>&1; then
    echo "Install uv yourself, then repeat --install-package with your selected package." >&2
    exit 1
  fi
  uv tool install --no-python-downloads --with-executables-from omnibase-core --python 3.12 "$package"
  binary_dir="$(uv tool dir --bin)"
  onex="$binary_dir/onex"
else
  onex="$(command -v onex || true)"
fi
if [[ -z "$onex" || ! -x "$onex" ]]; then
  echo "ONEX CLI is missing. Supply --install-package PACKAGE with your chosen release or local wheel." >&2
  exit 1
fi
exec "$onex" setup "${args[@]}"
