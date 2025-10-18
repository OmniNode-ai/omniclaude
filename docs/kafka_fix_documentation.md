# Kafka Connection Fix Documentation

## Problem
Confluent-kafka and aiokafka clients failed to publish messages to Redpanda running in Docker due to advertised listener mismatch.

## Solution
Implemented RpkKafkaClient that uses `docker exec` with `rpk` CLI to publish messages directly, bypassing the advertised listener issue.

## Files Modified
- `/Volumes/PRO-G40/Code/omniclaude/agents/lib/kafka_rpk_client.py` - New rpk-based client
- `/Volumes/PRO-G40/Code/omniclaude/scripts/publish_doc_change.py` - Updated to use rpk client first
- `/Volumes/PRO-G40/Code/omniclaude/agents/lib/kafka_codegen_client.py` - Added API version configuration
- `/Volumes/PRO-G40/Code/omniclaude/agents/lib/kafka_confluent_client.py` - Added delivery confirmation

## Testing
Successfully published test messages to `dev.omniclaude.docs.evt.documentation-changed.v1` topic.
