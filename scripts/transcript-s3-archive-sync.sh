#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
#
# transcript-s3-archive-sync.sh — durable daily sync of local Claude Code
# session history (~/.claude) to the encrypted S3 archive (OMN-18189,
# OMN-19513).
#
# Runs the canonical sync script that already lives in omninode_infra
# (scripts/archive_claude_sessions.sh) against the live archive bucket and its
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
INFRA_SYNC_SCRIPT="${OMNI_HOME}/omninode_infra/scripts/archive_claude_sessions.sh"
[[ -x "${INFRA_SYNC_SCRIPT}" ]] || {
  echo "REFUSED: sync script not found or not executable: ${INFRA_SYNC_SCRIPT}" >&2
  exit 1
}

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
