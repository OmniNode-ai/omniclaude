# Kafka Pipeline Test Document

This is a test document to verify the Kafka documentation ingestion pipeline.

## Test Details

- **Created**: 2025-10-18
- **Purpose**: End-to-end pipeline verification
- **Expected behavior**: Document change should be published to Kafka topic

## Verification Steps

1. Create/modify this document
2. Script publishes event to Kafka
3. Verify message in topic dev.omniclaude.docs.evt.documentation-changed.v1
