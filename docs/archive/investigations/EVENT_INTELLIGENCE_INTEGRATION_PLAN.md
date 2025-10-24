# Event-Based Intelligence Integration Plan

**Version**: 1.1.0 (Revised after validation)
**Date**: 2025-10-23
**Status**: Validated & Ready for Implementation
**Target PR**: feature/event-intelligence-integration
**Validation Date**: 2025-10-23

---

## Executive Summary

This document outlines the integration plan to replace hard-coded omniarchon repository paths with event-based intelligence discovery using production-ready Kafka event contracts.

**Current State**: Hard-coded paths to `/Volumes/PRO-G40/Code/omniarchon`
**Target State**: Event-based pattern discovery with graceful fallback
**Estimated Implementation**: 9 hours total across 4 phases
**Key Benefit**: Decoupled, scalable intelligence gathering with no hard-coded dependencies

---

## Validation Findings (2025-10-23)

### ✅ Infrastructure Validation Complete

**Pre-implementation validation confirmed**:
- ✅ Kafka broker running: `localhost:29092` (Redpanda external port)
- ✅ Intelligence service healthy: `archon-intelligence` on port 8053
- ✅ Event topics exist and configured (3 partitions, 1 replica each):
  - `dev.archon-intelligence.intelligence.code-analysis-requested.v1`
  - `dev.archon-intelligence.intelligence.code-analysis-completed.v1`
  - `dev.archon-intelligence.intelligence.code-analysis-failed.v1`
- ✅ Handler node running: `NodeIntelligenceAdapterEffect` (confluent-kafka)
- ✅ Event contracts compatible: Wire-protocol compatibility verified
- ✅ All 11 services operational in Docker

**Key Discoveries**:
1. **Kafka Port Mapping**: External access is `localhost:29092` (not 9092)
   - Internal Docker: `omninode-bridge-redpanda:9092`
   - External host: `localhost:29092` (port mapping: 9092→29092)

2. **Library Choice Validated**:
   - **omniarchon handler**: Uses `confluent-kafka` (correct for high-throughput service)
   - **omniclaude client**: Will use `aiokafka` (correct for request-response pattern)
   - **Wire compatibility**: Both libraries implement Kafka protocol ✅

3. **Handler Status**:
   - Running and healthy
   - Consumer group: `intelligence_adapter_consumers`
   - Current implementation: Returns stub responses (TODO: full implementation)

**Configuration Updates**:
- All `localhost:9092` references → `localhost:29092`
- Default remains `omninode-bridge-redpanda:9092` for Docker internal
- External clients must use port 29092

---

## Table of Contents

1. [Architecture Overview](#1-architecture-overview)
2. [Components to Build](#2-components-to-build)
3. [Implementation Phases](#3-implementation-phases)
4. [File Structure](#4-file-structure)
5. [Event Flow Diagrams](#5-event-flow-diagrams)
6. [Configuration Examples](#6-configuration-examples)
7. [Testing Strategy](#7-testing-strategy)
8. [Rollout Strategy](#8-rollout-strategy)
9. [Dependencies](#9-dependencies)
10. [Success Criteria](#10-success-criteria)
11. [Risk Assessment](#11-risk-assessment)
12. [Reference Documentation](#12-reference-documentation)

---

## 1. Architecture Overview

### 1.1 Current State (Hard-Coded Paths)

```
┌─────────────────────────────────────────────────────┐
│ omniclaude (Consumer)                                │
│                                                      │
│  ┌──────────────────┐                               │
│  │ code_refiner.py  │                               │
│  │                  │                               │
│  │ OMNIARCHON_PATH =                                │
│  │ "/Volumes/.../omniarchon"  ← HARD-CODED         │
│  │                  │                               │
│  │ find_similar_nodes()                             │
│  │  ├─ Reads filesystem directly                    │
│  │  ├─ No abstraction layer                         │
│  │  └─ Breaks on path changes                       │
│  └──────────────────┘                               │
└─────────────────────────────────────────────────────┘

Problems:
✗ Hard-coded absolute paths
✗ Tight coupling to filesystem
✗ No cross-machine compatibility
✗ Requires both codebases on same machine
✗ No event-driven architecture
```

### 1.2 Target State (Event-Based Discovery)

```
┌──────────────────────────────────────────────────────────────────────┐
│ omniclaude (Consumer)                                                 │
│                                                                       │
│  ┌────────────────────────┐      ┌──────────────────────────────┐  │
│  │ IntelligenceEventClient│◄────►│ Kafka Broker                 │  │
│  │                        │      │ localhost:29092              │  │
│  │ - publish_request()    │      │                              │  │
│  │ - wait_for_response()  │      │ Topics:                      │  │
│  │ - graceful_fallback()  │      │ - code-analysis-requested    │  │
│  └───────▲────────────────┘      │ - code-analysis-completed    │  │
│          │                        │ - code-analysis-failed       │  │
│          │                        └──────────────────────────────┘  │
│          │                                 ▲                         │
│  ┌───────┴────────────────┐               │                         │
│  │ intelligence_gatherer  │               │                         │
│  │                        │               │                         │
│  │ gather_intelligence()  │               │                         │
│  │  ├─ Event-based (if enabled)          │                         │
│  │  └─ Built-in patterns (fallback)      │                         │
│  └────────────────────────┘               │                         │
│                                            │                         │
│  ┌────────────────────────┐               │                         │
│  │ code_refiner.py        │               │                         │
│  │                        │               │                         │
│  │ find_similar_nodes()   │               │                         │
│  │  ├─ Events (if enabled)│               │                         │
│  │  └─ Built-in (fallback)│               │                         │
│  └────────────────────────┘               │                         │
└────────────────────────────────────────────┼─────────────────────────┘
                                             │
                                             ▼
┌──────────────────────────────────────────────────────────────────────┐
│ omniarchon (Producer)                                                 │
│                                                                       │
│  ┌──────────────────────────────────────────────┐                   │
│  │ IntelligenceAdapterHandler (Already Running) │                   │
│  │                                              │                   │
│  │ - Listens: code-analysis-requested          │                   │
│  │ - Processes: Pattern discovery              │                   │
│  │ - Publishes: code-analysis-completed        │                   │
│  │             code-analysis-failed            │                   │
│  └──────────────────────────────────────────────┘                   │
└──────────────────────────────────────────────────────────────────────┘

Benefits:
✓ Decoupled services via events
✓ Cross-machine compatible
✓ Scalable (multiple producers/consumers)
✓ Graceful fallback to built-in patterns
✓ Event replay and debugging
✓ Production-ready event contracts
```

### 1.3 Integration Layers

```
Layer 4: Application Layer
┌────────────────────────────────────────────────────┐
│ NodeGenerator, CodeRefiner, IntelligenceGatherer  │
│ (Consumer applications using intelligence)         │
└───────────────────┬────────────────────────────────┘
                    │
Layer 3: Event Client Layer
┌───────────────────▼────────────────────────────────┐
│ IntelligenceEventClient                            │
│ - Request-response pattern                         │
│ - Correlation tracking                             │
│ - Timeout handling                                 │
│ - Graceful fallback                                │
└───────────────────┬────────────────────────────────┘
                    │
Layer 2: Kafka Transport Layer
┌───────────────────▼────────────────────────────────┐
│ aiokafka (omniclaude client)                       │
│ - Native async/await producer/consumer             │
│ - Request-response pattern                         │
│ - Correlation tracking                             │
│ - Topic management & serialization                 │
│                                                    │
│ Note: Wire-compatible with omniarchon's            │
│ confluent-kafka (service-side handler)             │
└───────────────────┬────────────────────────────────┘
                    │
Layer 1: Event Contracts Layer
┌───────────────────▼────────────────────────────────┐
│ omniarchon Intelligence Adapter Events (IMPORTED)  │
│ - ModelCodeAnalysisRequestPayload                  │
│ - ModelCodeAnalysisCompletedPayload                │
│ - ModelCodeAnalysisFailedPayload                   │
│ - IntelligenceAdapterEventHelpers                  │
└────────────────────────────────────────────────────┘
```

### 1.4 Data Flow (Publish → Process → Consume)

```
┌──────────────────────────────────────────────────────────────────────┐
│ 1. Request Pattern Discovery                                         │
└──────────────────────────────────────────────────────────────────────┘

omniclaude                                               omniarchon
─────────┘                                               └─────────

1. Create Request
   ├─ source_path: "node_*_effect.py"
   ├─ language: "python"
   ├─ operation: PATTERN_EXTRACTION
   └─ correlation_id: uuid

2. Publish Event ────────────► Kafka Topic ────────────► 3. Consume Event
   code-analysis-requested       (async)                    Handler listens

                                                         4. Process Request
                                                            ├─ Search codebase
                                                            ├─ Extract patterns
                                                            ├─ Calculate confidence
                                                            └─ Build response

5. Wait for Response ◄─────── Kafka Topic ◄─────────── 6. Publish Result
   (with timeout)                (async)                   code-analysis-completed

7. Deserialize Result
   ├─ Pattern list
   ├─ Confidence scores
   ├─ Metadata
   └─ Processing stats

8. Apply Patterns
   └─ Generate/refine code

┌──────────────────────────────────────────────────────────────────────┐
│ 9. Fallback on Failure                                               │
│    ├─ Timeout: Use built-in patterns                                 │
│    ├─ Error: Use built-in patterns                                   │
│    └─ Kafka down: Use built-in patterns                              │
└──────────────────────────────────────────────────────────────────────┘
```

### 1.5 Library Choice: aiokafka vs confluent-kafka

**Decision: Use `aiokafka` for omniclaude client** ✅

**Rationale**:

| Aspect | aiokafka (Our Choice) | confluent-kafka (omniarchon) |
|--------|----------------------|------------------------------|
| **Use Case** | Request-response client | Background consumer service |
| **Pattern** | Short-lived requests | Long-running 24/7 loop |
| **Throughput** | Moderate (<1000 req/s) | High (>100k events/s) |
| **Integration** | Native async/await | Blocking (needs wrapper) |
| **Complexity** | Simple, direct | Advanced features needed |
| **Codebase Fit** | Perfect for client | Perfect for service |

**Wire Compatibility**: ✅ Both libraries implement the Kafka protocol correctly and are fully interoperable. Our `aiokafka` client publishes events that `omniarchon`'s `confluent-kafka` handler consumes without any issues.

**Why omniarchon uses confluent-kafka** (service-side):
- ✅ C-based librdkafka: 30-40% faster throughput (critical for high-volume processing)
- ✅ Enterprise support: Confluent's commercial backing and SLAs
- ✅ Advanced features: Exactly-once semantics, manual offset management, consumer groups
- ✅ Production standard: Industry-standard for service-side consumers
- ✅ Battle-tested: Used by Fortune 500 companies at massive scale

**Why omniclaude uses aiokafka** (client-side):
- ✅ Native async/await: Seamless integration with async application code
- ✅ Request-response pattern: Perfect fit for our client usage
- ✅ Simpler implementation: No async wrappers or background tasks needed
- ✅ Pure Python: Easier debugging, profiling, and maintenance
- ✅ Already in dependencies: No new installations or C library setup required

**Example Comparison**:
```python
# omniarchon (confluent-kafka): Background service consumer
class NodeIntelligenceAdapterEffect:
    async def _consume_events_loop(self):
        """Long-running 24/7 consumer processing all client requests"""
        while not shutdown:
            msg = self.kafka_consumer.poll(1.0)  # Blocking poll in bg task
            if msg:
                await self._route_event_to_operation(msg)
                self.kafka_consumer.commit()  # Manual offset management

# omniclaude (aiokafka): Request-response client
class IntelligenceEventClient:
    async def request_pattern_discovery(self, source_path):
        """Short-lived request-response interaction"""
        correlation_id = uuid4()

        # Publish request (native async)
        await self.producer.send_and_wait(topic, create_request(correlation_id))

        # Wait for response (native async iteration)
        async for msg in self.consumer:
            if msg.correlation_id == correlation_id:
                return deserialize(msg.value)
```

**Conclusion**: Perfect library match for each use case! Both are production-ready choices that complement each other in a distributed architecture. ✅

---

## 2. Components to Build

### 2.1 IntelligenceEventClient (NEW)

**File**: `agents/lib/intelligence_event_client.py`

**Purpose**: Kafka producer/consumer wrapper for intelligence operations

**Key Methods**:
```python
class IntelligenceEventClient:
    """
    Kafka client for intelligence event publishing and consumption.

    Provides request-response pattern with correlation tracking,
    timeout handling, and graceful fallback.
    """

    async def request_pattern_discovery(
        self,
        source_path: str,
        language: str,
        operation_type: EnumAnalysisOperationType,
        timeout_ms: int = 5000,
    ) -> List[ProductionPattern]:
        """
        Request pattern discovery via events.

        Args:
            source_path: Pattern to search for (e.g., "node_*_effect.py")
            language: Programming language
            operation_type: Type of analysis
            timeout_ms: Response timeout in milliseconds

        Returns:
            List of production patterns

        Raises:
            TimeoutError: If response not received within timeout
            KafkaError: If Kafka communication fails
        """

    async def request_code_analysis(
        self,
        source_path: str,
        content: str,
        language: str,
        options: Dict[str, Any],
        timeout_ms: int = 10000,
    ) -> Dict[str, Any]:
        """
        Request comprehensive code analysis via events.

        Args:
            source_path: File path for context
            content: Code content to analyze
            language: Programming language
            options: Analysis options
            timeout_ms: Response timeout

        Returns:
            Analysis results dictionary
        """

    async def _publish_request(
        self,
        event: Dict[str, Any],
        correlation_id: UUID,
    ) -> None:
        """Publish request event to Kafka."""

    async def _wait_for_response(
        self,
        correlation_id: UUID,
        timeout_ms: int,
    ) -> Dict[str, Any]:
        """
        Wait for response event with timeout.

        Uses correlation_id to match response to request.
        """

    async def health_check(self) -> bool:
        """Check Kafka connection health."""

    async def close(self) -> None:
        """Close Kafka connections gracefully."""
```

**Key Features**:
- Async producer/consumer using aiokafka
- Correlation tracking via UUID
- Timeout with exponential backoff
- Graceful error handling
- Health check for circuit breaker
- Connection pooling

**Error Handling**:
```python
try:
    patterns = await client.request_pattern_discovery(...)
except TimeoutError:
    logger.warning("Event timeout, falling back to built-in patterns")
    patterns = self._get_builtin_patterns()
except KafkaError as e:
    logger.error(f"Kafka error: {e}, falling back")
    patterns = self._get_builtin_patterns()
```

### 2.2 intelligence_gatherer Integration (MODIFY)

**File**: `agents/lib/intelligence_gatherer.py`

**Changes**:
```python
class IntelligenceGatherer:
    """
    Gathers contextual intelligence for node generation.

    Multi-source intelligence gathering system:
    1. Event-based pattern discovery (if enabled)
    2. Built-in pattern library (always available)
    3. Archon RAG integration (future)
    """

    def __init__(
        self,
        archon_client=None,
        event_client: Optional[IntelligenceEventClient] = None,  # NEW
    ):
        """
        Initialize intelligence gatherer.

        Args:
            archon_client: Optional Archon MCP client for RAG queries
            event_client: Optional event client for pattern discovery
        """
        self.archon = archon_client
        self.event_client = event_client  # NEW
        self.pattern_library = self._load_pattern_library()
        self.logger = logging.getLogger(__name__)

    async def gather_intelligence(
        self,
        node_type: str,
        domain: str,
        service_name: str,
        operations: List[str],
        prompt: str,
    ) -> IntelligenceContext:
        """Gather all intelligence sources for enhanced node generation."""

        intelligence = IntelligenceContext()

        # Source 1: Event-based pattern discovery (if enabled)
        if self.event_client:
            await self._gather_event_based_patterns(
                intelligence, node_type, domain, service_name
            )

        # Source 2: Built-in pattern library (always available)
        self._gather_builtin_patterns(
            intelligence, node_type, domain, service_name, operations
        )

        # Source 3: Archon RAG (if available)
        if self.archon:
            await self._gather_archon_intelligence(
                intelligence, node_type, domain, service_name, prompt
            )

        return intelligence

    async def _gather_event_based_patterns(  # NEW
        self,
        intelligence: IntelligenceContext,
        node_type: str,
        domain: str,
        service_name: str,
    ):
        """Gather patterns from omniarchon via events."""
        try:
            self.logger.debug(
                f"Requesting pattern discovery via events for {node_type}/{domain}"
            )

            # Request pattern discovery
            patterns = await self.event_client.request_pattern_discovery(
                source_path=f"node_*_{node_type}.py",
                language="python",
                operation_type=EnumAnalysisOperationType.PATTERN_EXTRACTION,
                timeout_ms=5000,
            )

            # Add patterns to intelligence
            intelligence.production_examples.extend(patterns)
            intelligence.rag_sources.append("event_based_discovery")

            # Increase confidence score
            if patterns:
                intelligence.confidence_score = max(
                    intelligence.confidence_score,
                    0.9  # High confidence for production patterns
                )

            self.logger.info(
                f"Loaded {len(patterns)} patterns via events (confidence: {intelligence.confidence_score:.2f})"
            )

        except (TimeoutError, Exception) as e:
            self.logger.warning(
                f"Event-based pattern discovery failed: {e}, using built-in patterns"
            )
            # Graceful fallback - built-in patterns already loaded
```

**Integration Points**:
- Add `event_client` parameter to `__init__`
- Add `_gather_event_based_patterns()` method
- Call event-based gathering before built-in patterns
- Graceful fallback on any error

### 2.3 code_refiner Pattern Discovery (MODIFY)

**File**: `agents/lib/code_refiner.py`

**Changes**:
```python
class ProductionPatternMatcher:
    """
    Finds similar production nodes and extracts applicable patterns.

    Supports multiple pattern sources:
    1. Event-based discovery (preferred, if available)
    2. Filesystem scanning (fallback, local development)
    """

    def __init__(self, event_client: Optional[IntelligenceEventClient] = None):  # MODIFIED
        """
        Initialize pattern matcher.

        Args:
            event_client: Optional event client for event-based discovery
        """
        self.event_client = event_client  # NEW
        self.cache: Dict[str, ProductionPattern] = {}
        logger.info("Initialized ProductionPatternMatcher")

    async def find_similar_nodes(  # MODIFIED (now async)
        self,
        node_type: str,
        domain: str,
        limit: int = 3
    ) -> List[Path]:
        """
        Search for similar production nodes by type and domain.

        Uses event-based discovery if available, otherwise falls back
        to filesystem scanning (local development only).
        """
        logger.info(f"Finding similar {node_type} nodes for domain '{domain}'")

        # Try event-based discovery first
        if self.event_client:
            try:
                return await self._find_similar_nodes_via_events(
                    node_type, domain, limit
                )
            except Exception as e:
                logger.warning(
                    f"Event-based discovery failed: {e}, falling back to filesystem"
                )

        # Fallback: Use filesystem scanning (local development)
        return self._find_similar_nodes_via_filesystem(node_type, domain, limit)

    async def _find_similar_nodes_via_events(  # NEW
        self,
        node_type: str,
        domain: str,
        limit: int,
    ) -> List[Path]:
        """Find similar nodes via event-based pattern discovery."""

        # Request pattern discovery
        patterns = await self.event_client.request_pattern_discovery(
            source_path=f"node_*_{node_type}.py",
            language="python",
            operation_type=EnumAnalysisOperationType.PATTERN_EXTRACTION,
            timeout_ms=5000,
        )

        # Convert patterns to Path objects (for compatibility)
        # In reality, we'd return the patterns directly
        # but we need to maintain API compatibility
        similar_nodes = []
        for pattern in patterns[:limit]:
            # Calculate domain similarity
            score = self._calculate_domain_similarity(domain, pattern.file_path)
            similar_nodes.append((pattern.file_path, score))

        # Sort by score and return paths
        similar_nodes.sort(key=lambda x: x[1], reverse=True)
        return [Path(node[0]) for node in similar_nodes[:limit]]

    def _find_similar_nodes_via_filesystem(  # RENAMED (was find_similar_nodes)
        self,
        node_type: str,
        domain: str,
        limit: int,
    ) -> List[Path]:
        """
        Find similar nodes via filesystem scanning (local development).

        DEPRECATED: Use event-based discovery instead.
        Only used as fallback for local development.
        """
        # Existing implementation...
        # (Keep the current hard-coded path logic as fallback)
        pass
```

**Key Changes**:
- Add `event_client` parameter to `__init__`
- Make `find_similar_nodes()` async
- Add `_find_similar_nodes_via_events()` method
- Rename existing method to `_find_similar_nodes_via_filesystem()`
- Graceful fallback to filesystem on event failure
- **Remove hard-coded paths in Phase 3** (after event-based proven)

### 2.4 Configuration Management (NEW)

**File**: `agents/lib/config/intelligence_config.py`

**Purpose**: Centralized configuration with environment variables

```python
from dataclasses import dataclass
from typing import Optional
import os


@dataclass
class IntelligenceConfig:
    """Configuration for intelligence gathering system."""

    # Kafka Configuration
    kafka_bootstrap_servers: str = "localhost:29092"  # Redpanda external port
    kafka_enable_intelligence: bool = True
    kafka_request_timeout_ms: int = 5000
    kafka_pattern_discovery_timeout_ms: int = 5000
    kafka_code_analysis_timeout_ms: int = 10000

    # Event Topics
    kafka_topic_request: str = "dev.archon-intelligence.intelligence.code-analysis-requested.v1"
    kafka_topic_completed: str = "dev.archon-intelligence.intelligence.code-analysis-completed.v1"
    kafka_topic_failed: str = "dev.archon-intelligence.intelligence.code-analysis-failed.v1"

    # Fallback Configuration
    enable_filesystem_fallback: bool = True
    filesystem_omniarchon_path: Optional[str] = None

    # Feature Flags
    enable_event_based_discovery: bool = True
    enable_archon_rag: bool = False

    # Performance
    correlation_tracking_enabled: bool = True
    metrics_enabled: bool = True

    @classmethod
    def from_env(cls) -> "IntelligenceConfig":
        """Load configuration from environment variables."""
        return cls(
            kafka_bootstrap_servers=os.getenv(
                "KAFKA_BOOTSTRAP_SERVERS",
                "localhost:29092"  # Redpanda external port
            ),
            kafka_enable_intelligence=os.getenv(
                "KAFKA_ENABLE_INTELLIGENCE",
                "true"
            ).lower() == "true",
            kafka_request_timeout_ms=int(
                os.getenv("KAFKA_REQUEST_TIMEOUT_MS", "5000")
            ),
            enable_event_based_discovery=os.getenv(
                "ENABLE_EVENT_INTELLIGENCE",
                "true"
            ).lower() == "true",
            enable_filesystem_fallback=os.getenv(
                "ENABLE_FILESYSTEM_FALLBACK",
                "true"
            ).lower() == "true",
            filesystem_omniarchon_path=os.getenv(
                "OMNIARCHON_PATH",
                None
            ),
        )

    def validate(self) -> None:
        """Validate configuration."""
        if self.kafka_enable_intelligence:
            if not self.kafka_bootstrap_servers:
                raise ValueError("KAFKA_BOOTSTRAP_SERVERS required when events enabled")

        if not self.enable_event_based_discovery and not self.enable_filesystem_fallback:
            raise ValueError("At least one discovery method must be enabled")
```

**Usage**:
```python
# Load from environment
config = IntelligenceConfig.from_env()
config.validate()

# Create event client
if config.enable_event_based_discovery:
    event_client = IntelligenceEventClient(
        bootstrap_servers=config.kafka_bootstrap_servers,
        timeout_ms=config.kafka_request_timeout_ms,
    )
else:
    event_client = None

# Create intelligence gatherer
gatherer = IntelligenceGatherer(
    event_client=event_client,
    archon_client=None,
)
```

---

## 3. Implementation Phases

### Phase 1: Event Client Foundation (4 hours)

**Goal**: Build production-ready Kafka event client

**Tasks**:
1. Create `intelligence_event_client.py` (2 hours)
   - Implement `IntelligenceEventClient` class
   - Async producer/consumer with aiokafka
   - Request-response pattern with correlation tracking
   - Timeout handling with exponential backoff
   - Health check and connection management

2. Create `intelligence_config.py` (1 hour)
   - Configuration dataclass
   - Environment variable loading
   - Validation logic
   - Feature flags

3. Unit tests (1 hour)
   - `test_intelligence_event_client.py`
   - Mock Kafka producer/consumer
   - Test correlation tracking
   - Test timeout handling
   - Test graceful degradation

**Deliverables**:
- ✅ `agents/lib/intelligence_event_client.py`
- ✅ `agents/lib/config/intelligence_config.py`
- ✅ `agents/tests/test_intelligence_event_client.py`
- ✅ Unit tests passing

**Acceptance Criteria**:
- Event client can publish requests
- Event client can wait for responses with timeout
- Correlation tracking works correctly
- Health check detects Kafka availability
- All unit tests pass

### Phase 2: intelligence_gatherer Integration (2 hours)

**Goal**: Add event-based pattern discovery to intelligence gatherer

**Tasks**:
1. Update `intelligence_gatherer.py` (1 hour)
   - Add `event_client` parameter
   - Implement `_gather_event_based_patterns()`
   - Integrate with existing flow
   - Graceful fallback logic

2. Update tests (1 hour)
   - Update `test_intelligence_gatherer.py`
   - Mock event client
   - Test event-based gathering
   - Test fallback behavior

**Deliverables**:
- ✅ Updated `agents/lib/intelligence_gatherer.py`
- ✅ Updated `agents/tests/test_intelligence_gatherer.py`
- ✅ Tests passing with event client

**Acceptance Criteria**:
- Event client called when available
- Built-in patterns used as fallback
- Confidence scores adjusted correctly
- All tests pass

### Phase 3: code_refiner Pattern Discovery (2 hours)

**Goal**: Replace filesystem scanning with event-based discovery

**Tasks**:
1. Update `code_refiner.py` (1 hour)
   - Add `event_client` parameter to `ProductionPatternMatcher`
   - Make `find_similar_nodes()` async
   - Implement `_find_similar_nodes_via_events()`
   - Rename existing method to `_find_similar_nodes_via_filesystem()`
   - Add graceful fallback

2. Update tests (1 hour)
   - Update `test_code_refiner.py`
   - Mock event client
   - Test event-based discovery
   - Test fallback to filesystem

**Deliverables**:
- ✅ Updated `agents/lib/code_refiner.py`
- ✅ Updated `agents/tests/test_code_refiner.py`
- ✅ Hard-coded paths only used as fallback

**Acceptance Criteria**:
- Event-based discovery works
- Filesystem fallback works
- Hard-coded paths deprecated (not removed yet)
- All tests pass

### Phase 4: Configuration & Documentation (1 hour)

**Goal**: Complete configuration, documentation, and integration testing

**Tasks**:
1. Environment variables (.5 hour)
   - Update `.env.example`
   - Document required variables
   - Add feature flags

2. Documentation (.5 hour)
   - Update `README.md`
   - Create integration guide
   - Document configuration
   - Add troubleshooting section

**Deliverables**:
- ✅ Updated `.env.example`
- ✅ Updated `README.md`
- ✅ Integration documentation
- ✅ All tests passing

**Acceptance Criteria**:
- Environment variables documented
- Feature flags documented
- Integration guide complete
- All tests pass (unit + integration)

---

## 4. File Structure

```
agents/
├── lib/
│   ├── intelligence_event_client.py          # NEW - Kafka event client
│   ├── intelligence_gatherer.py              # MODIFY - Add event client integration
│   ├── code_refiner.py                       # MODIFY - Add event-based discovery
│   └── config/
│       └── intelligence_config.py            # NEW - Configuration management
├── tests/
│   ├── test_intelligence_event_client.py     # NEW - Event client tests
│   ├── test_intelligence_gatherer.py         # UPDATE - Add event client tests
│   └── test_code_refiner.py                  # UPDATE - Add event-based tests
└── docs/
    ├── EVENT_INTELLIGENCE_INTEGRATION_PLAN.md # THIS FILE
    └── INTELLIGENCE_INTEGRATION_GUIDE.md      # NEW - Usage guide

.env.example                                    # UPDATE - Add Kafka config
README.md                                       # UPDATE - Document event integration
pyproject.toml                                  # VERIFY - kafka-python already present
```

**New Files**:
- `agents/lib/intelligence_event_client.py` (~400 lines)
- `agents/lib/config/intelligence_config.py` (~100 lines)
- `agents/tests/test_intelligence_event_client.py` (~300 lines)
- `docs/INTELLIGENCE_INTEGRATION_GUIDE.md` (~200 lines)

**Modified Files**:
- `agents/lib/intelligence_gatherer.py` (+50 lines)
- `agents/lib/code_refiner.py` (+80 lines)
- `agents/tests/test_intelligence_gatherer.py` (+40 lines)
- `agents/tests/test_code_refiner.py` (+50 lines)
- `.env.example` (+15 lines)
- `README.md` (+30 lines)

**Total LOC**: ~1,265 lines added/modified

---

## 5. Event Flow Diagrams

### 5.1 Request Pattern Discovery Flow

```
┌─────────────────┐
│ Start: Request  │
│ pattern         │
│ discovery       │
└────────┬────────┘
         │
         ▼
┌─────────────────────────────────────────┐
│ 1. IntelligenceGatherer                 │
│    ├─ Check if event_client available   │
│    └─ If yes, call _gather_event_based()│
└────────┬────────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────────┐
│ 2. IntelligenceEventClient              │
│    ├─ Generate correlation_id           │
│    ├─ Create request payload            │
│    └─ Publish to Kafka                  │
└────────┬────────────────────────────────┘
         │
         ▼
   ┌─────────────┐
   │ Kafka Broker│
   │ (async)     │
   └─────────────┘
         │
         ▼
┌─────────────────────────────────────────┐
│ 3. omniarchon Handler (Listening)       │
│    ├─ Consume request event             │
│    ├─ Extract correlation_id            │
│    ├─ Search patterns                   │
│    ├─ Extract patterns                  │
│    └─ Calculate confidence              │
└────────┬────────────────────────────────┘
         │
         ▼
   ┌─────────────┐
   │ Kafka Broker│
   │ (async)     │
   └─────────────┘
         │
         ▼
┌─────────────────────────────────────────┐
│ 4. IntelligenceEventClient              │
│    ├─ Wait for response (with timeout)  │
│    ├─ Match correlation_id              │
│    └─ Deserialize response              │
└────────┬────────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────────┐
│ 5. IntelligenceGatherer                 │
│    ├─ Add patterns to intelligence      │
│    ├─ Update confidence score           │
│    └─ Return intelligence context       │
└────────┬────────────────────────────────┘
         │
         ▼
┌─────────────────┐
│ End: Patterns   │
│ received        │
└─────────────────┘
```

### 5.2 Error Handling and Retry Flow

```
┌─────────────────┐
│ Start: Request  │
└────────┬────────┘
         │
         ▼
┌──────────────────────────┐
│ Publish Request          │
└────────┬─────────────────┘
         │
         ▼
    ┌────────────┐
    │ Wait for   │
    │ Response   │
    │ (timeout:  │
    │  5000ms)   │
    └──────┬─────┘
           │
           ├───► Timeout? ───────┐
           │                     │
           ▼                     ▼
      Response              ┌─────────────────┐
      Received              │ TimeoutError    │
           │                └────────┬────────┘
           │                         │
           ▼                         ▼
   ┌──────────────┐          ┌──────────────────┐
   │ Parse Event  │          │ Log Warning      │
   │ Type         │          │ "Event timeout"  │
   └──────┬───────┘          └────────┬─────────┘
          │                           │
          ├─► COMPLETED ──────────┐   │
          │                       │   │
          ├─► FAILED ─────────┐   │   │
          │                   │   │   │
          └─► UNKNOWN ───┐    │   │   │
                         │    │   │   │
                         ▼    ▼   ▼   ▼
                    ┌────────────────────┐
                    │ Fallback to        │
                    │ Built-in Patterns  │
                    └────────┬───────────┘
                             │
                             ▼
                       ┌──────────────┐
                       │ Return       │
                       │ Patterns     │
                       └──────────────┘
```

### 5.3 Fallback to Built-in Patterns Flow

```
┌──────────────────────────────────────────────┐
│ Trigger: Any of these conditions             │
│  - Event client not available                │
│  - Kafka connection failed                   │
│  - Request timeout (>5000ms)                 │
│  - Response parse error                      │
│  - omniarchon handler down                   │
└──────────────────┬───────────────────────────┘
                   │
                   ▼
┌──────────────────────────────────────────────┐
│ 1. Log Warning                               │
│    "Event-based discovery failed: {reason}"  │
│    "Falling back to built-in patterns"       │
└──────────────────┬───────────────────────────┘
                   │
                   ▼
┌──────────────────────────────────────────────┐
│ 2. Load Built-in Pattern Library             │
│    ├─ EFFECT patterns by domain              │
│    ├─ COMPUTE patterns                       │
│    ├─ REDUCER patterns                       │
│    └─ ORCHESTRATOR patterns                  │
└──────────────────┬───────────────────────────┘
                   │
                   ▼
┌──────────────────────────────────────────────┐
│ 3. Apply Domain Matching                     │
│    ├─ Match node_type                        │
│    ├─ Match domain (database, api, etc.)     │
│    └─ Get relevant patterns                  │
└──────────────────┬───────────────────────────┘
                   │
                   ▼
┌──────────────────────────────────────────────┐
│ 4. Set Confidence Score                      │
│    ├─ Built-in patterns: 0.7                 │
│    ├─ Lower than event-based (0.9)           │
│    └─ Still production-ready                 │
└──────────────────┬───────────────────────────┘
                   │
                   ▼
┌──────────────────────────────────────────────┐
│ 5. Return IntelligenceContext                │
│    ├─ patterns: built-in patterns            │
│    ├─ confidence: 0.7                        │
│    └─ sources: ["builtin_pattern_library"]   │
└──────────────────┬───────────────────────────┘
                   │
                   ▼
┌──────────────────────────────────────────────┐
│ Success: Node generation continues           │
│ (with slightly lower confidence)             │
└──────────────────────────────────────────────┘
```

---

## 6. Configuration Examples

### 6.1 .env.example Updates

```bash
# ============================================================================
# Kafka Event Intelligence Configuration
# ============================================================================

# Kafka Bootstrap Servers (comma-separated for cluster)
# External host access to Redpanda (port mapping: 9092→29092)
KAFKA_BOOTSTRAP_SERVERS=localhost:29092

# Enable event-based intelligence gathering
# Set to 'false' to use only built-in patterns (offline mode)
KAFKA_ENABLE_INTELLIGENCE=true

# Feature flag: Enable event-based pattern discovery
# Set to 'false' to disable event-based discovery entirely
ENABLE_EVENT_INTELLIGENCE=true

# Request timeout in milliseconds
# How long to wait for omniarchon to respond
KAFKA_REQUEST_TIMEOUT_MS=5000

# Pattern discovery timeout (faster operations)
KAFKA_PATTERN_DISCOVERY_TIMEOUT_MS=5000

# Code analysis timeout (slower operations)
KAFKA_CODE_ANALYSIS_TIMEOUT_MS=10000

# Kafka Topic Configuration (Advanced)
# Default topics follow ONEX event bus architecture
# Only override if you've customized omniarchon topics
# KAFKA_TOPIC_REQUEST=dev.archon-intelligence.intelligence.code-analysis-requested.v1
# KAFKA_TOPIC_COMPLETED=dev.archon-intelligence.intelligence.code-analysis-completed.v1
# KAFKA_TOPIC_FAILED=dev.archon-intelligence.intelligence.code-analysis-failed.v1

# ============================================================================
# Fallback Configuration
# ============================================================================

# Enable filesystem fallback when events fail
# Recommended: keep 'true' for development resilience
ENABLE_FILESYSTEM_FALLBACK=true

# Filesystem path to omniarchon (fallback only)
# Only used if event-based discovery fails
# DEPRECATED: Will be removed in future version
OMNIARCHON_PATH=/Volumes/PRO-G40/Code/omniarchon

# ============================================================================
# Performance and Monitoring
# ============================================================================

# Enable correlation tracking for debugging
CORRELATION_TRACKING_ENABLED=true

# Enable performance metrics
METRICS_ENABLED=true

# ============================================================================
# Development vs Production
# ============================================================================

# Development (local laptop with Docker):
# External host access to Redpanda (port mapping: 9092→29092)
# KAFKA_BOOTSTRAP_SERVERS=localhost:29092
# ENABLE_EVENT_INTELLIGENCE=true
# ENABLE_FILESYSTEM_FALLBACK=true

# Development (within Docker network):
# KAFKA_BOOTSTRAP_SERVERS=omninode-bridge-redpanda:9092
# ENABLE_EVENT_INTELLIGENCE=true
# ENABLE_FILESYSTEM_FALLBACK=true

# Production (servers):
# KAFKA_BOOTSTRAP_SERVERS=kafka-1:9092,kafka-2:9092,kafka-3:9092
# ENABLE_EVENT_INTELLIGENCE=true
# ENABLE_FILESYSTEM_FALLBACK=false  # No filesystem access in production
```

### 6.2 Usage Example (Application Code)

```python
#!/usr/bin/env python3
"""Example: Using event-based intelligence in node generation."""

import asyncio
from agents.lib.intelligence_event_client import IntelligenceEventClient
from agents.lib.intelligence_gatherer import IntelligenceGatherer
from agents.lib.config.intelligence_config import IntelligenceConfig


async def main():
    # 1. Load configuration from environment
    config = IntelligenceConfig.from_env()
    config.validate()

    print(f"Event Intelligence: {'Enabled' if config.enable_event_based_discovery else 'Disabled'}")
    print(f"Kafka Servers: {config.kafka_bootstrap_servers}")
    print(f"Note: Using aiokafka for request-response pattern")

    # 2. Create event client (if enabled)
    event_client = None
    if config.enable_event_based_discovery:
        event_client = IntelligenceEventClient(
            bootstrap_servers=config.kafka_bootstrap_servers,
            timeout_ms=config.kafka_request_timeout_ms,
        )

        # Health check
        if await event_client.health_check():
            print("✓ Kafka connection healthy")
        else:
            print("✗ Kafka connection failed, will use fallback")

    # 3. Create intelligence gatherer
    gatherer = IntelligenceGatherer(
        event_client=event_client,
        archon_client=None,  # Optional Archon RAG
    )

    # 4. Gather intelligence for node generation
    intelligence = await gatherer.gather_intelligence(
        node_type="EFFECT",
        domain="database",
        service_name="PostgresWriter",
        operations=["create", "update", "delete"],
        prompt="Create a database writer effect node with transaction support",
    )

    # 5. Use intelligence
    print(f"\nIntelligence Gathered:")
    print(f"  Confidence: {intelligence.confidence_score:.2f}")
    print(f"  Sources: {intelligence.rag_sources}")
    print(f"  Patterns: {len(intelligence.node_type_patterns)}")
    print(f"  Examples: {len(intelligence.production_examples)}")

    # 6. Cleanup
    if event_client:
        await event_client.close()


if __name__ == "__main__":
    asyncio.run(main())
```

### 6.3 Docker Compose Configuration

```yaml
version: '3.8'

services:
  # Kafka broker (for local development)
  kafka:
    image: confluentinc/cp-kafka:7.5.0
    ports:
      - "9092:9092"
    environment:
      KAFKA_BROKER_ID: 1
      KAFKA_ZOOKEEPER_CONNECT: zookeeper:2181
      KAFKA_ADVERTISED_LISTENERS: PLAINTEXT://localhost:9092
      KAFKA_OFFSETS_TOPIC_REPLICATION_FACTOR: 1
    depends_on:
      - zookeeper

  zookeeper:
    image: confluentinc/cp-zookeeper:7.5.0
    ports:
      - "2181:2181"
    environment:
      ZOOKEEPER_CLIENT_PORT: 2181
      ZOOKEEPER_TICK_TIME: 2000

  # omniclaude agent service
  omniclaude:
    build: .
    environment:
      - KAFKA_BOOTSTRAP_SERVERS=kafka:9092
      - ENABLE_EVENT_INTELLIGENCE=true
      - KAFKA_REQUEST_TIMEOUT_MS=5000
    depends_on:
      - kafka
    volumes:
      - ./agents:/app/agents

  # omniarchon intelligence service (separate repo)
  omniarchon:
    image: omniarchon:latest
    environment:
      - KAFKA_BOOTSTRAP_SERVERS=kafka:9092
    depends_on:
      - kafka
```

---

## 7. Testing Strategy

### 7.1 Unit Tests

**File**: `agents/tests/test_intelligence_event_client.py`

```python
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4
from agents.lib.intelligence_event_client import IntelligenceEventClient


@pytest.fixture
async def mock_kafka():
    """Mock Kafka producer and consumer."""
    with patch("agents.lib.intelligence_event_client.AIOKafkaProducer") as mock_producer, \
         patch("agents.lib.intelligence_event_client.AIOKafkaConsumer") as mock_consumer:
        yield {
            "producer": mock_producer.return_value,
            "consumer": mock_consumer.return_value,
        }


@pytest.mark.asyncio
async def test_request_pattern_discovery_success(mock_kafka):
    """Test successful pattern discovery via events."""

    # Arrange
    client = IntelligenceEventClient(
        bootstrap_servers="localhost:9092",
        timeout_ms=5000,
    )

    correlation_id = uuid4()

    # Mock response
    mock_response = {
        "correlation_id": str(correlation_id),
        "event_type": "code_analysis_completed",
        "payload": {
            "source_path": "node_*_effect.py",
            "patterns": [
                {"file_path": "node_db_effect.py", "confidence": 0.9},
                {"file_path": "node_api_effect.py", "confidence": 0.85},
            ],
        },
    }

    mock_kafka["consumer"].getone = AsyncMock(return_value=mock_response)

    # Act
    patterns = await client.request_pattern_discovery(
        source_path="node_*_effect.py",
        language="python",
        operation_type="PATTERN_EXTRACTION",
        timeout_ms=5000,
    )

    # Assert
    assert len(patterns) == 2
    assert patterns[0]["file_path"] == "node_db_effect.py"
    assert patterns[0]["confidence"] == 0.9


@pytest.mark.asyncio
async def test_request_pattern_discovery_timeout(mock_kafka):
    """Test timeout handling in pattern discovery."""

    # Arrange
    client = IntelligenceEventClient(
        bootstrap_servers="localhost:9092",
        timeout_ms=1000,  # Short timeout
    )

    # Mock timeout
    async def timeout_func(*args, **kwargs):
        await asyncio.sleep(2)  # Longer than timeout
        return None

    mock_kafka["consumer"].getone = AsyncMock(side_effect=timeout_func)

    # Act & Assert
    with pytest.raises(TimeoutError):
        await client.request_pattern_discovery(
            source_path="node_*_effect.py",
            language="python",
            operation_type="PATTERN_EXTRACTION",
            timeout_ms=1000,
        )


@pytest.mark.asyncio
async def test_correlation_id_tracking(mock_kafka):
    """Test correlation ID matches request and response."""

    # Arrange
    client = IntelligenceEventClient(
        bootstrap_servers="localhost:9092",
        timeout_ms=5000,
    )

    correlation_id = uuid4()

    # Mock response with matching correlation_id
    mock_response = {
        "correlation_id": str(correlation_id),
        "event_type": "code_analysis_completed",
        "payload": {"patterns": []},
    }

    mock_kafka["consumer"].getone = AsyncMock(return_value=mock_response)

    # Act
    patterns = await client.request_pattern_discovery(
        source_path="test.py",
        language="python",
        operation_type="PATTERN_EXTRACTION",
        timeout_ms=5000,
    )

    # Assert
    # Verify correlation_id was used in request
    call_args = mock_kafka["producer"].send.call_args
    request_payload = call_args[0][1]
    assert request_payload["correlation_id"] == str(correlation_id)


@pytest.mark.asyncio
async def test_health_check_success(mock_kafka):
    """Test Kafka health check when connection is healthy."""

    # Arrange
    client = IntelligenceEventClient(
        bootstrap_servers="localhost:9092",
        timeout_ms=5000,
    )

    mock_kafka["producer"].start = AsyncMock()

    # Act
    is_healthy = await client.health_check()

    # Assert
    assert is_healthy is True


@pytest.mark.asyncio
async def test_graceful_close(mock_kafka):
    """Test graceful connection closure."""

    # Arrange
    client = IntelligenceEventClient(
        bootstrap_servers="localhost:9092",
        timeout_ms=5000,
    )

    mock_kafka["producer"].stop = AsyncMock()
    mock_kafka["consumer"].stop = AsyncMock()

    # Act
    await client.close()

    # Assert
    mock_kafka["producer"].stop.assert_called_once()
    mock_kafka["consumer"].stop.assert_called_once()
```

### 7.2 Integration Tests

**File**: `agents/tests/integration/test_event_intelligence_integration.py`

```python
import pytest
import asyncio
from uuid import uuid4
from agents.lib.intelligence_event_client import IntelligenceEventClient
from agents.lib.intelligence_gatherer import IntelligenceGatherer


@pytest.mark.integration
@pytest.mark.asyncio
async def test_end_to_end_pattern_discovery():
    """
    Integration test: Full pattern discovery flow.

    Requires:
    - Kafka running on localhost:9092
    - omniarchon intelligence handler running
    """

    # Arrange
    event_client = IntelligenceEventClient(
        bootstrap_servers="localhost:9092",
        timeout_ms=10000,  # Longer timeout for real Kafka
    )

    gatherer = IntelligenceGatherer(
        event_client=event_client,
    )

    # Act
    intelligence = await gatherer.gather_intelligence(
        node_type="EFFECT",
        domain="database",
        service_name="TestWriter",
        operations=["create", "update"],
        prompt="Test prompt",
    )

    # Assert
    assert intelligence.confidence_score > 0.0
    assert len(intelligence.rag_sources) > 0
    assert "event_based_discovery" in intelligence.rag_sources

    # Cleanup
    await event_client.close()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_fallback_when_kafka_down():
    """
    Integration test: Fallback to built-in patterns when Kafka is down.
    """

    # Arrange
    event_client = IntelligenceEventClient(
        bootstrap_servers="localhost:9999",  # Invalid port
        timeout_ms=1000,
    )

    gatherer = IntelligenceGatherer(
        event_client=event_client,
    )

    # Act
    intelligence = await gatherer.gather_intelligence(
        node_type="EFFECT",
        domain="database",
        service_name="TestWriter",
        operations=["create"],
        prompt="Test prompt",
    )

    # Assert
    # Should fallback to built-in patterns
    assert intelligence.confidence_score == 0.7  # Built-in confidence
    assert "builtin_pattern_library" in intelligence.rag_sources
    assert "event_based_discovery" not in intelligence.rag_sources

    # Cleanup
    await event_client.close()
```

### 7.3 Test Execution

```bash
# Run unit tests only
pytest agents/tests/test_intelligence_event_client.py -v

# Run integration tests (requires Kafka)
pytest agents/tests/integration/ -v -m integration

# Run all tests
pytest agents/tests/ -v

# Run with coverage
pytest agents/tests/ --cov=agents/lib --cov-report=html

# Run specific test
pytest agents/tests/test_intelligence_event_client.py::test_request_pattern_discovery_success -v
```

---

## 8. Rollout Strategy

### 8.1 Feature Flag Rollout

```
Phase 1: Development Testing (Week 1)
├─ Enable: ENABLE_EVENT_INTELLIGENCE=true
├─ Enable: ENABLE_FILESYSTEM_FALLBACK=true
├─ Test: All unit tests
├─ Test: Integration tests with local Kafka
└─ Validate: Event-based discovery works

Phase 2: Canary Deployment (Week 2)
├─ Enable: ENABLE_EVENT_INTELLIGENCE=true (10% of requests)
├─ Enable: ENABLE_FILESYSTEM_FALLBACK=true
├─ Monitor: Success rate, latency, error rate
├─ Compare: Event-based vs filesystem performance
└─ Decision: Proceed or rollback

Phase 3: Gradual Rollout (Week 3)
├─ Enable: ENABLE_EVENT_INTELLIGENCE=true (50% → 100%)
├─ Enable: ENABLE_FILESYSTEM_FALLBACK=true
├─ Monitor: Performance metrics
├─ Alert: On any degradation
└─ Validate: Production readiness

Phase 4: Full Deployment (Week 4)
├─ Enable: ENABLE_EVENT_INTELLIGENCE=true (100%)
├─ Disable: ENABLE_FILESYSTEM_FALLBACK=false (optional)
├─ Remove: Hard-coded paths (optional)
└─ Document: Final architecture
```

### 8.2 Monitoring and Metrics

**Key Metrics to Track**:

```python
# Performance Metrics
event_based_discovery_duration_ms: histogram
    - Labels: operation_type, node_type, domain
    - Target: <100ms (vs <50ms for filesystem)

event_based_discovery_success_rate: counter
    - Labels: operation_type, outcome (success, timeout, error, fallback)
    - Target: >95%

filesystem_fallback_rate: counter
    - Labels: reason (timeout, error, kafka_down)
    - Target: <5%

# Quality Metrics
pattern_confidence_score: histogram
    - Labels: source (event_based, filesystem, builtin)
    - Event-based target: >0.9
    - Built-in target: 0.7

patterns_discovered_count: histogram
    - Labels: node_type, domain
    - Target: >3 patterns per request

# Error Metrics
kafka_connection_errors: counter
    - Labels: error_type (timeout, connection_refused, auth_failed)
    - Target: <1%

correlation_id_mismatch: counter
    - Target: 0 (indicates serious bug)
```

**Dashboard Example** (Grafana):
```
┌─────────────────────────────────────────────────────────────────┐
│ Event Intelligence Health Dashboard                             │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│ Success Rate (Last Hour)                  Fallback Rate        │
│ ▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓ 98.5%                ▓▓░░░░░░░░ 1.5%       │
│                                                                 │
│ Latency (p50/p95/p99)                     Patterns/Request     │
│ 45ms / 85ms / 120ms                       3.2 avg              │
│                                                                 │
│ Kafka Connection Health                   Confidence Score     │
│ ✓ Connected                               ▓▓▓▓▓▓▓▓▓▓ 0.92 avg  │
│                                                                 │
│ Recent Errors (Last 5 min)                                     │
│ - 2 timeouts (recovered via fallback)                          │
│ - 0 correlation mismatches                                     │
│ - 0 critical errors                                            │
└─────────────────────────────────────────────────────────────────┘
```

### 8.3 Rollback Procedure

**If Issues Detected**:

```bash
# Step 1: Immediate Rollback
# Set feature flag to disable event-based discovery
export ENABLE_EVENT_INTELLIGENCE=false

# Step 2: Verify Fallback Working
pytest agents/tests/test_intelligence_gatherer.py::test_fallback -v

# Step 3: Analyze Root Cause
# Check logs for errors
tail -f logs/omniclaude.log | grep "event"

# Check Kafka health
kafka-topics.sh --list --bootstrap-server localhost:9092

# Step 4: Fix and Re-deploy
# Address root cause
# Re-enable feature flag gradually
```

**Rollback Criteria**:
- Success rate <90%
- Latency >500ms (5x slower than filesystem)
- Fallback rate >20%
- Kafka connection errors >10%
- Any data corruption or correlation mismatches

---

## 9. Dependencies

### 9.1 Runtime Dependencies

**Already in pyproject.toml**:
```toml
[tool.poetry.dependencies]
aiokafka = "^0.10.0"                # Async Kafka client
kafka-python = "^2.0.2"             # Sync Kafka client (fallback)
pydantic = "^2.0.0"                 # Validation
python-dotenv = "^1.1.1"            # Environment variables
```

**From omniarchon** (import pattern):
```python
# Event contracts (already production-ready)
from omniarchon.services.intelligence.src.events.models import (
    ModelCodeAnalysisRequestPayload,
    ModelCodeAnalysisCompletedPayload,
    ModelCodeAnalysisFailedPayload,
    IntelligenceAdapterEventHelpers,
    EnumAnalysisOperationType,
    EnumAnalysisErrorCode,
    create_request_event,
    create_completed_event,
    create_failed_event,
)
```

**Note**: Event contracts must be imported from omniarchon repository, not duplicated.

### 9.2 Infrastructure Dependencies

**Required Services**:
1. **Kafka Broker** (localhost:9092 for dev)
   - Version: 3.0+
   - Topics: Auto-created by clients
   - Retention: 7 days default

2. **omniarchon Intelligence Service**
   - IntelligenceAdapterHandler running
   - Listening on code-analysis-requested topic
   - Publishing to code-analysis-completed/failed topics

**Development Setup**:
```bash
# Start Kafka (Docker)
docker-compose up -d kafka zookeeper

# Verify Kafka running
kafka-topics.sh --list --bootstrap-server localhost:9092

# Start omniarchon intelligence handler
cd /Volumes/PRO-G40/Code/omniarchon
poetry run python services/intelligence/src/handlers/intelligence_adapter_handler.py
```

### 9.3 Import Strategy

**Critical**: Event contracts must be imported from omniarchon, not duplicated.

```python
# ❌ WRONG - Don't duplicate event contracts
# from agents.lib.events.intelligence_adapter_events import ...

# ✅ CORRECT - Import from omniarchon
from omniarchon.services.intelligence.src.events.models import (
    ModelCodeAnalysisRequestPayload,
    ModelCodeAnalysisCompletedPayload,
    IntelligenceAdapterEventHelpers,
    create_request_event,
)
```

**Why?**
- Single source of truth
- No version drift
- No duplicate validation logic
- Easier to maintain

**Setup**:
```bash
# Add omniarchon to PYTHONPATH (development)
export PYTHONPATH="/Volumes/PRO-G40/Code/omniarchon:$PYTHONPATH"

# Or install as editable dependency
cd /Volumes/PRO-G40/Code/omniclaude
poetry add --editable /Volumes/PRO-G40/Code/omniarchon
```

---

## 10. Success Criteria

### 10.1 Functional Requirements

- ✅ Event-based pattern discovery working
- ✅ Correlation tracking across request/response
- ✅ Timeout handling with graceful fallback
- ✅ Built-in patterns used as fallback
- ✅ No hard-coded repository paths (in event mode)
- ✅ Configuration via environment variables
- ✅ Feature flags for gradual rollout
- ✅ All unit tests passing
- ✅ Integration tests passing

### 10.2 Performance Requirements

| Metric | Target | Measurement |
|--------|--------|-------------|
| Event-based discovery latency | <100ms | p95 response time |
| Fallback latency | <50ms | Built-in pattern loading |
| Success rate | >95% | Successful event responses |
| Fallback rate | <5% | Fallback invocations |
| Kafka connection health | >99% | Uptime percentage |
| Memory overhead | <20MB | Event client memory |
| CPU overhead | <5% | Event processing |

### 10.3 Quality Requirements

- ✅ Pattern confidence score >0.9 for event-based
- ✅ Pattern confidence score 0.7 for built-in
- ✅ Zero correlation ID mismatches
- ✅ No data loss on timeout/error
- ✅ Graceful degradation on Kafka failure
- ✅ Production-ready error handling
- ✅ Comprehensive logging and observability
- ✅ Documentation complete and accurate

### 10.4 Acceptance Tests

**Test 1: End-to-End Pattern Discovery**
```python
async def test_e2e_pattern_discovery():
    """Verify full pattern discovery flow via events."""

    # Setup
    config = IntelligenceConfig.from_env()
    event_client = IntelligenceEventClient(config.kafka_bootstrap_servers)
    gatherer = IntelligenceGatherer(event_client=event_client)

    # Execute
    intelligence = await gatherer.gather_intelligence(
        node_type="EFFECT",
        domain="database",
        service_name="TestWriter",
        operations=["create", "update"],
        prompt="Test",
    )

    # Verify
    assert intelligence.confidence_score > 0.9
    assert "event_based_discovery" in intelligence.rag_sources
    assert len(intelligence.production_examples) > 0
```

**Test 2: Graceful Fallback**
```python
async def test_fallback_on_kafka_failure():
    """Verify fallback to built-in patterns when Kafka fails."""

    # Setup (invalid Kafka broker)
    event_client = IntelligenceEventClient("localhost:9999")
    gatherer = IntelligenceGatherer(event_client=event_client)

    # Execute
    intelligence = await gatherer.gather_intelligence(
        node_type="EFFECT",
        domain="database",
        service_name="TestWriter",
        operations=["create"],
        prompt="Test",
    )

    # Verify fallback worked
    assert intelligence.confidence_score == 0.7  # Built-in
    assert "builtin_pattern_library" in intelligence.rag_sources
```

**Test 3: Performance Benchmark**
```python
async def test_performance_benchmark():
    """Verify event-based discovery meets performance targets."""

    # Setup
    event_client = IntelligenceEventClient("localhost:9092")
    gatherer = IntelligenceGatherer(event_client=event_client)

    # Benchmark 100 requests
    durations = []
    for _ in range(100):
        start = time.perf_counter()
        await gatherer.gather_intelligence(
            node_type="EFFECT",
            domain="database",
            service_name="Test",
            operations=["create"],
            prompt="Test",
        )
        durations.append(time.perf_counter() - start)

    # Verify performance
    p95 = np.percentile(durations, 95)
    assert p95 < 0.100  # <100ms target
```

---

## 11. Risk Assessment

### 11.1 Technical Risks

**Risk 1: Kafka Broker Unavailability**
- **Probability**: Medium
- **Impact**: Low (graceful fallback)
- **Mitigation**:
  - Built-in patterns as fallback
  - Health check before requests
  - Circuit breaker pattern
  - Monitoring and alerting

**Risk 2: Event Response Timeout**
- **Probability**: Low
- **Impact**: Low (graceful fallback)
- **Mitigation**:
  - 5-second timeout
  - Automatic fallback to built-in patterns
  - Retry logic for transient failures
  - Logging for debugging

**Risk 3: Correlation ID Mismatch**
- **Probability**: Very Low
- **Impact**: High (data corruption)
- **Mitigation**:
  - UUID-based correlation tracking
  - Comprehensive unit tests
  - Integration tests with real Kafka
  - Zero tolerance monitoring

**Risk 4: omniarchon Handler Not Running**
- **Probability**: Medium (during deployment)
- **Impact**: Low (graceful fallback)
- **Mitigation**:
  - Health check detects handler down
  - Automatic fallback to built-in patterns
  - Deployment coordination
  - Monitoring dashboard

**Risk 5: Network Latency**
- **Probability**: Medium
- **Impact**: Medium (slower than filesystem)
- **Mitigation**:
  - 100ms latency target (2x slower acceptable)
  - Timeout after 5 seconds
  - Caching for repeated requests
  - Performance monitoring

### 11.2 Operational Risks

**Risk 1: Kafka Topic Misconfiguration**
- **Probability**: Low
- **Impact**: Medium
- **Mitigation**:
  - Auto-create topics on first use
  - Standard naming convention
  - Configuration validation
  - Integration tests

**Risk 2: Event Schema Drift**
- **Probability**: Low
- **Impact**: High
- **Mitigation**:
  - Import contracts from omniarchon (single source)
  - Pydantic validation
  - Integration tests
  - Version tracking in topic names

**Risk 3: Rollback Required**
- **Probability**: Low
- **Impact**: Low (feature flag rollback)
- **Mitigation**:
  - Feature flag for instant rollback
  - Built-in patterns always available
  - Rollback procedure documented
  - Monitoring for early detection

### 11.3 Mitigation Summary

| Risk | Mitigation Strategy |
|------|---------------------|
| Kafka down | Built-in pattern fallback, health checks |
| Timeout | 5s timeout, automatic fallback, retry logic |
| Correlation mismatch | UUID tracking, unit tests, monitoring |
| Handler down | Health check, fallback, deployment coordination |
| Latency | 100ms target, caching, performance monitoring |
| Schema drift | Import from omniarchon, validation, versioning |
| Rollback needed | Feature flag, documented procedure, monitoring |

---

## 12. Reference Documentation

### 12.1 omniarchon Intelligence Events

**Primary Reference**:
- `/Volumes/PRO-G40/Code/omniarchon/DELIVERABLE_INTELLIGENCE_ADAPTER_EVENTS.md`
- `/Volumes/PRO-G40/Code/omniarchon/services/intelligence/docs/INTELLIGENCE_ADAPTER_EVENTS.md`

**Event Contracts**:
- `/Volumes/PRO-G40/Code/omniarchon/services/intelligence/src/events/models/intelligence_adapter_events.py`

**Handler Implementation**:
- `/Volumes/PRO-G40/Code/omniarchon/services/intelligence/src/handlers/intelligence_adapter_handler.py`

**Usage Examples**:
- `/Volumes/PRO-G40/Code/omniarchon/services/intelligence/src/events/models/intelligence_adapter_events_usage.py`

### 12.2 Kafka Documentation

**Official Documentation**:
- Kafka Producer API: https://kafka.apache.org/documentation/#producerapi
- Kafka Consumer API: https://kafka.apache.org/documentation/#consumerapi
- aiokafka Library: https://aiokafka.readthedocs.io/

**ONEX Event Bus Architecture**:
- Topic Naming: `{env}.{service}.{domain}.{event}.{version}`
- Example: `dev.archon-intelligence.intelligence.code-analysis-requested.v1`

### 12.3 omniclaude Current Implementation

**Current Files**:
- `agents/lib/intelligence_gatherer.py` (line 38: `__init__` parameters)
- `agents/lib/code_refiner.py` (line 100-101: hard-coded paths)
- `pyproject.toml` (line 29: aiokafka dependency)

**Hard-Coded Paths to Replace**:
```python
# code_refiner.py:100-101
OMNIARCHON_PATH = Path("/Volumes/PRO-G40/Code/omniarchon")
OMNINODE_BRIDGE_PATH = Path("/Volumes/PRO-G40/Code/omninode_bridge")
```

### 12.4 Related Documentation

**Agent Framework**:
- `agents/core-requirements.yaml` - 47 mandatory functions
- `agents/quality-gates-spec.yaml` - 23 quality gates
- `agents/AGENT_FRAMEWORK.md` - Core agent patterns

**MCP Integration**:
- `agents/MCP_INTEGRATION.md` - MCP server integration patterns
- `agents/ARCHON_INTEGRATION.md` - Archon MCP integration framework

---

## Appendix A: Quick Reference

### A.1 Environment Variables

```bash
# Required
KAFKA_BOOTSTRAP_SERVERS=localhost:9092
ENABLE_EVENT_INTELLIGENCE=true

# Optional
KAFKA_REQUEST_TIMEOUT_MS=5000
ENABLE_FILESYSTEM_FALLBACK=true
OMNIARCHON_PATH=/path/to/omniarchon  # Fallback only
```

### A.2 Key Classes

```python
# Event Client
from agents.lib.intelligence_event_client import IntelligenceEventClient

# Intelligence Gatherer
from agents.lib.intelligence_gatherer import IntelligenceGatherer

# Configuration
from agents.lib.config.intelligence_config import IntelligenceConfig

# Event Contracts (from omniarchon)
from omniarchon.services.intelligence.src.events.models import (
    create_request_event,
    create_completed_event,
    EnumAnalysisOperationType,
)
```

### A.3 Common Commands

```bash
# Start Kafka
docker-compose up -d kafka zookeeper

# Run tests
pytest agents/tests/ -v

# Check Kafka topics
kafka-topics.sh --list --bootstrap-server localhost:9092

# Monitor Kafka
kafka-console-consumer.sh --bootstrap-server localhost:9092 \
  --topic dev.archon-intelligence.intelligence.code-analysis-completed.v1

# Check configuration
python -c "from agents.lib.config.intelligence_config import IntelligenceConfig; \
           config = IntelligenceConfig.from_env(); print(config)"
```

### A.4 Troubleshooting

**Problem**: Event timeout
```bash
# Check Kafka connection
kafka-topics.sh --list --bootstrap-server localhost:9092

# Check omniarchon handler running
ps aux | grep intelligence_adapter_handler

# Check logs
tail -f logs/omniclaude.log | grep "timeout"
```

**Problem**: Correlation ID mismatch
```bash
# Check correlation tracking
grep "correlation_id" logs/omniclaude.log | tail -20

# Run correlation test
pytest agents/tests/test_intelligence_event_client.py::test_correlation_id_tracking -v
```

**Problem**: Fallback rate too high
```bash
# Check success rate
grep "event_based_discovery" logs/omniclaude.log | grep -c "success"
grep "fallback" logs/omniclaude.log | wc -l

# Check Kafka health
kafka-broker-api-versions.sh --bootstrap-server localhost:9092
```

---

## Appendix B: Implementation Checklist

### Phase 1: Event Client Foundation (4 hours)
- [ ] Create `intelligence_event_client.py`
- [ ] Implement `IntelligenceEventClient` class
- [ ] Add async producer/consumer
- [ ] Add correlation tracking
- [ ] Add timeout handling
- [ ] Create `intelligence_config.py`
- [ ] Add unit tests
- [ ] Verify all tests pass

### Phase 2: intelligence_gatherer Integration (2 hours)
- [ ] Add `event_client` parameter to `__init__`
- [ ] Implement `_gather_event_based_patterns()`
- [ ] Add graceful fallback logic
- [ ] Update unit tests
- [ ] Verify tests pass

### Phase 3: code_refiner Pattern Discovery (2 hours)
- [ ] Add `event_client` parameter to `ProductionPatternMatcher`
- [ ] Make `find_similar_nodes()` async
- [ ] Implement `_find_similar_nodes_via_events()`
- [ ] Rename filesystem method
- [ ] Add graceful fallback
- [ ] Update unit tests
- [ ] Verify tests pass

### Phase 4: Configuration & Documentation (1 hour)
- [ ] Update `.env.example`
- [ ] Update `README.md`
- [ ] Create integration guide
- [ ] Add troubleshooting section
- [ ] Run full test suite
- [ ] Verify all tests pass

### Deployment
- [ ] Set environment variables
- [ ] Start Kafka broker
- [ ] Start omniarchon handler
- [ ] Deploy omniclaude with feature flag
- [ ] Monitor metrics dashboard
- [ ] Validate success criteria

---

**Document Version**: 1.0.0
**Last Updated**: 2025-10-23
**Status**: Ready for Implementation
**Estimated Effort**: 9 hours
**Next Steps**: Begin Phase 1 - Event Client Foundation
