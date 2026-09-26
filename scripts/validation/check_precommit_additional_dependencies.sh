#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
#
# Reject VCS-backed pre-commit additional_dependencies. Installing one while
# git commit exports GIT_INDEX_FILE can let the dependency checkout overwrite
# the committing worktree's index (OMN-19666).

set -euo pipefail

config_path="${1:-.pre-commit-config.yaml}"

if [[ ! -f "${config_path}" ]]; then
  echo "pre-commit dependency guard: config not found: ${config_path}" >&2
  exit 2
fi

awk '
function indentation(line, copy) {
    copy = line
    sub(/[^ \t].*$/, "", copy)
    return length(copy)
}

function active_text(line, text) {
    text = line
    sub(/[[:space:]]+#.*/, "", text)
    return tolower(text)
}

function is_forbidden(text) {
    return index(text, "git+") > 0 || text ~ /@[[:space:]]+git/
}

function refuse(line_number, text) {
    printf "%s:%d: additional_dependencies must use a released package, not a git dependency: %s\n", path, line_number, text > "/dev/stderr"
    bad = 1
}

BEGIN {
    inside_dependencies = 0
    dependencies_indent = -1
    bad = 0
}

{
    stripped = $0
    sub(/^[ \t]+/, "", stripped)

    if (stripped == "" || stripped ~ /^#/) {
        next
    }

    current_indent = indentation($0)
    if (inside_dependencies && current_indent <= dependencies_indent) {
        inside_dependencies = 0
    }

    if (stripped ~ /^additional_dependencies[[:space:]]*:/) {
        inside_dependencies = 1
        dependencies_indent = current_indent
        inline_value = stripped
        sub(/^additional_dependencies[[:space:]]*:[[:space:]]*/, "", inline_value)
        inline_value = active_text(inline_value)
        if (is_forbidden(inline_value)) {
            refuse(NR, inline_value)
        }
        next
    }

    if (inside_dependencies) {
        dependency = active_text(stripped)
        if (is_forbidden(dependency)) {
            refuse(NR, dependency)
        }
    }
}

END {
    exit bad
}
' path="${config_path}" "${config_path}"
