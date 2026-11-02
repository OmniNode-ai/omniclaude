# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Agent Trace and PR Debugging System — replay engine package.

Only the replay engine still lives here. The trace models (ChangeFrame, the PR
envelope and the trace table rows) are in ``omniclaude.models.trace``; frame
assembly, failure signatures, fix transitions and the intelligence integration
are in ``omniclaude.handlers.trace`` (OMN-21943).

NOTE: Migration freeze is active (OMN-2055 / .migration_freeze).
The Alembic migration for the trace tables must be applied once the freeze lifts.
See src/omniclaude/models/trace/model_trace_db_schema.py for the complete DDL.
"""
