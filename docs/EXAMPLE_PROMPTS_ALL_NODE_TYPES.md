# Example Prompts for All 4 ONEX Node Types

This document provides example prompts for generating each of the 4 ONEX node types. The PromptParser uses keyword detection and pattern matching to identify the appropriate node type.

## EFFECT Node Examples

**Characteristics**: External I/O, APIs, side effects, database writes, API calls

### EFFECT Node with Intelligence Gathering

**Prompt**:
```
Create EFFECT node called PostgresCRUD for PostgreSQL database with
connection pooling, prepared statements, and transaction support
```

**Intelligence Detected**:
- ✅ Connection pooling (from "database" + "connection pooling")
- ✅ Prepared statements (from "PostgreSQL")
- ✅ Transaction support (from "transaction support")
- ✅ Circuit breaker (from EFFECT + database best practices)

**Generated Code Includes**:
```python
# TODO: Implement connection pool acquisition
# TODO: Use prepared statements for SQL injection prevention
# TODO: Wrap operations in transaction
# TODO: Apply circuit breaker for resilience
```

---

### Example 1: Database Writer
```
Create an EFFECT node called DatabaseWriter that writes customer records to PostgreSQL.
It should handle inserts, updates, and deletes with proper error handling.
```

### Example 2: Email Sender
```
EFFECT node: EmailSender
Sends notification emails via SMTP. Should support templates and attachment handling.
Domain: notification
```

### Example 3: File Storage
```
Build an EFFECT node for S3FileUploader that stores files to AWS S3.
Should handle multipart uploads and generate presigned URLs.
```

### Example 4: API Client
```
Create an EFFECT node that sends HTTP requests to external REST APIs.
Should handle retries, timeouts, and authentication.
```

---

## COMPUTE Node Examples

**Characteristics**: Pure functions, transformations, calculations, data processing, no I/O

### Example 1: Price Calculator
```
Create a COMPUTE node called PriceCalculator that calculates product prices.
It should process pricing rules, apply discounts, and calculate tax.
Pure function with no database access.
```

### Example 2: Data Transformer
```
COMPUTE node: DataTransformer
Transforms raw sensor data into normalized format.
Should validate inputs and apply transformation rules.
Domain: data_services
```

### Example 3: Algorithm Processor
```
Build a COMPUTE node that analyzes text and extracts keywords.
Should use NLP algorithms to process and rank terms.
No external dependencies or I/O.
```

### Example 4: Validation Engine
```
Create a COMPUTE node that validates user input data.
Should check formats, ranges, and business rules.
Returns validation results without side effects.
```

---

## REDUCER Node Examples

**Characteristics**: Aggregation, state accumulation, event reduction, intent emission

### Example 1: Event Aggregator
```
Create a REDUCER node called EventAggregator that aggregates user events.
Groups events by correlation_id and emits intents when thresholds are reached.
Should use FSM for state transitions.
```

### Example 2: Metrics Collector
```
REDUCER node: MetricsCollector
Aggregates performance metrics over time windows.
Emits intents for alerting when SLA thresholds are exceeded.
Domain: analytics
```

### Example 3: Order Combiner
```
Build a REDUCER node that combines order line items into complete orders.
Should reduce multiple events into aggregated state and emit completion intents.
```

### Example 4: Session Manager
```
Create a REDUCER node that aggregates user session data.
Should consolidate session events and emit intents for session completion.
```

---

## ORCHESTRATOR Node Examples

**Characteristics**: Workflow coordination, multi-node orchestration, lease management, actions

### Example 1: Payment Workflow
```
Create an ORCHESTRATOR node called PaymentWorkflow that coordinates payment processing.
Should orchestrate validation, processing, and notification steps.
Uses lease-based actions with epoch versioning.
```

### Example 2: Data Pipeline
```
ORCHESTRATOR node: DataPipelineCoordinator
Manages ETL workflow across multiple processing stages.
Coordinates COMPUTE nodes for transformation and EFFECT nodes for storage.
Domain: data_services
```

### Example 3: Order Fulfillment
```
Build an ORCHESTRATOR node that manages order fulfillment workflow.
Should coordinate inventory check, payment, shipping, and notification steps.
Issues ModelAction with lease management.
```

### Example 4: Multi-Step Workflow
```
Create an ORCHESTRATOR node for document processing workflow.
Coordinates upload, validation, processing, and archival steps.
Manages dependencies and ensures proper ordering.
```

---

## Detection Keywords Reference

The PromptParser uses these keywords for node type detection:

### EFFECT Keywords
- create, write, send, delete, update, store, save
- External system names: postgres, redis, kafka, s3, smtp, api

### COMPUTE Keywords
- calculate, process, transform, analyze, compute, validate
- Pure function indicators: "no I/O", "no side effects", "pure function"

### REDUCER Keywords
- aggregate, summarize, reduce, combine, merge, consolidate
- State management: "accumulate", "group by", "correlation_id"

### ORCHESTRATOR Keywords
- coordinate, orchestrate, manage, workflow, pipeline
- Multi-step indicators: "steps", "stages", "workflow"

---

## Explicit Node Type Specification

You can also explicitly specify the node type in your prompt:

```
EFFECT node: MyDatabaseWriter
[description...]
```

```
COMPUTE node: MyPriceCalculator
[description...]
```

```
REDUCER node: MyEventAggregator
[description...]
```

```
ORCHESTRATOR node: MyWorkflowCoordinator
[description...]
```

Explicit specification provides 100% confidence in node type detection.

---

## Best Practices

1. **Use clear action verbs** that match the node type characteristics
2. **Specify the node type explicitly** when confidence is important
3. **Include domain information** to help with proper service naming
4. **Describe the business logic** to enable better template generation
5. **Mention external systems** for EFFECT nodes (database names, APIs, etc.)
6. **Emphasize "pure function"** for COMPUTE nodes
7. **Mention "intent emission"** for REDUCER nodes
8. **Describe workflow steps** for ORCHESTRATOR nodes

---

## Testing Node Type Detection

You can test node type detection using the PromptParser directly:

```python
from agents.lib.prompt_parser import PromptParser

parser = PromptParser()
prompt = "Create a COMPUTE node that calculates pricing"
node_type, confidence = parser._extract_node_type(prompt)

print(f"Detected: {node_type} (confidence: {confidence:.2f})")
# Output: Detected: COMPUTE (confidence: 0.70)
```
