#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
#
# transcript-s3-archive-sync.sh — durable daily sync of local Claude Code
# session history (~/.claude) to the encrypted S3 archive (OMN-18189,
# OMN-19513).
#
# Runs the canonical sync script that already lives in the infrastructure
# repository (scripts/archive_claude_sessions.sh) against the live archive bucket and its
# KMS key. Both are resolved by discovery rather than hardcoded, so an
# infra-side rename is a loud failure here instead of a silent no-op against a
# stale name.
#
# Installed as a launchd LaunchAgent per
# omniclaude/scripts/tick-bundle-install.sh conventions; see
# omniclaude/scripts/launchd/ai.omninode.transcript-s3-archive.plist.
#
# OUT OF SCOPE (ledger ruling docs/tracking/ROLLING_WORK_LEDGER.md:3722,
# OMN-19513): never creates or rotates AWS credentials or KMS keys, never
# changes the bucket policy, never deletes a local transcript. This script
# only ever syncs TO the one archive bucket declared by OMN-18189.

set -euo pipefail

OMNI_HOME="${OMNI_HOME:?OMNI_HOME must be set to the registry root}"

# Resolve the infrastructure clone by DISCOVERY, like the bucket and the KMS key
# below, instead of assuming it is a sibling of the registry root.
#
# WHY (OMN-17427, measured 2026-11-02): this used to hardcode one sibling path under
# the registry root. On the operator Mac the clone lives under ~/OmniNode/repos while
# OMNI_HOME is ~/code/omni, so the path never resolved and the agent exited 1 on every
# run. The launchd job was installed and loaded, which made it look healthy, while the
# archive took nothing: the bucket's newest object under projects/ was
# 2026-09-25T21:16:55Z, 38 days stale, and 186 local session files (879 MB) on that
# host had never been uploaded. A per-host path is not config to copy by hand
# (kb#1571), so the resolution order is declared here and every place looked is named
# in the refusal.
#
# The order is: an explicit OMNINODE_INFRA_PATH override (the clone root), then any
# clone holding the sync script directly under the registry root (the lab hosts),
# under $HOME/OmniNode/repos (the operator Mac), or beside the registry root. The
# clone is found by the script it holds, not by its directory name. Written as few
# statements because the canonical-file-shape baseline (OMN-20304) only ever shrinks.
INFRA_SYNC_ROOTS=("${OMNI_HOME}" "${HOME}/OmniNode/repos" "$(dirname "${OMNI_HOME}")")
INFRA_SYNC_SCRIPT="$(for c in "${OMNINODE_INFRA_PATH:-}" "${INFRA_SYNC_ROOTS[@]/%//*}"; do for d in ${c}; do d="${d%/}"; if [[ -n "${d}" && -x "${d}/scripts/archive_claude_sessions.sh" ]]; then printf '%s' "${d}/scripts/archive_claude_sessions.sh"; break 2; fi; done; done)"
[[ -n "${INFRA_SYNC_SCRIPT}" ]] || { printf 'REFUSED: no executable scripts/archive_claude_sessions.sh in any clone found. Set OMNINODE_INFRA_PATH to the clone root. Looked under, in order:\n' >&2; printf '    %s/*/scripts/archive_claude_sessions.sh\n' "${INFRA_SYNC_ROOTS[@]%/}" >&2; exit 1; }
echo "infra sync script: ${INFRA_SYNC_SCRIPT}"

export AWS_PROFILE="${AWS_PROFILE:-default}"

echo "=== transcript-s3-archive-sync $(date -u +%Y-%m-%dT%H:%M:%SZ) ==="

# Discover the archive bucket by its declared prefix (OMN-18189) rather than
# reconstructing its account-id-bearing name. Built with a plain read loop, not
# `mapfile` (bash 4+ only) -- launchd's restricted PATH can resolve `env bash`
# to macOS's system /bin/bash (3.2) ahead of a newer one on PATH.
BUCKET_PREFIX="omninode-claude-session-archive-"
MATCHING_BUCKETS=()
while IFS= read -r bucket_name; do
  [[ -n "${bucket_name}" ]] && MATCHING_BUCKETS+=("${bucket_name}")
done < <(
  aws s3api list-buckets \
    --query "Buckets[?starts_with(Name, '${BUCKET_PREFIX}')].Name" \
    --output text | tr '\t' '\n'
)

if [[ ${#MATCHING_BUCKETS[@]} -eq 0 ]]; then
  echo "REFUSED: no bucket found with prefix ${BUCKET_PREFIX} (credentials expired, or the bucket was renamed)" >&2
  exit 1
fi
if [[ ${#MATCHING_BUCKETS[@]} -gt 1 ]]; then
  echo "REFUSED: more than one bucket matches prefix ${BUCKET_PREFIX}: ${MATCHING_BUCKETS[*]}" >&2
  exit 1
fi
export ARCHIVE_BUCKET="${MATCHING_BUCKETS[0]}"

ARCHIVE_KMS_KEY_ID="$(aws kms describe-key --key-id alias/omninode-claude-session-archive \
  --query 'KeyMetadata.Arn' --output text)"
if [[ -z "${ARCHIVE_KMS_KEY_ID}" || "${ARCHIVE_KMS_KEY_ID}" == "None" ]]; then
  echo "REFUSED: could not resolve the archive KMS key ARN (alias/omninode-claude-session-archive)" >&2
  exit 1
fi
export ARCHIVE_KMS_KEY_ID

echo "bucket: ${ARCHIVE_BUCKET}"
echo "kms:    ${ARCHIVE_KMS_KEY_ID}"

"${INFRA_SYNC_SCRIPT}" --yes

echo "=== READBACK ==="
aws s3 ls "s3://${ARCHIVE_BUCKET}/" --recursive --summarize | tail -3
echo "done $(date -u +%Y-%m-%dT%H:%M:%SZ)"
