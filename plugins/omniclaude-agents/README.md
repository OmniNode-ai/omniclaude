# OmniClaude Agents Plugin

A Claude Code plugin providing **53 polymorphic agents** in YAML format for comprehensive development workflow automation, intelligent routing, code review, security auditing, performance optimization, and more.

## Why YAML Agent Format?

Unlike simple markdown-based agent definitions, the OmniClaude agents use a **structured YAML format** that enables:

| Feature | Benefit |
|---------|---------|
| **Machine-Readable Structure** | Agents can be programmatically parsed, validated, and indexed |
| **Fuzzy Matching on Aliases/Triggers** | Router can match user intent against structured activation patterns |
| **Performance Targets** | Quantitative targets can be validated and enforced programmatically |
| **Quality Gates** | Machine-enforceable quality requirements |
| **ONEX Compliance Checking** | Automated verification of architectural standards |
| **Dynamic Routing** | Polymorphic agent can transform into any specialized agent at runtime |
| **Registry Integration** | Centralized agent discovery with <0.5ms resolution time |

**Key Advantage**: YAML enables the polymorphic agent framework to make intelligent routing decisions based on structured metadata, not just keyword matching against prose.

---

## Installation

This plugin is designed to be installed via Claude Code's plugin system.

```bash
# The plugin is located at: plugins/omniclaude-agents/
# Agents are in: plugins/omniclaude-agents/agents/
```

---

## YAML Agent Schema

All agents follow a consistent YAML schema that enables programmatic parsing and intelligent routing.

### Core Schema Structure

```yaml
# Schema Version and Agent Classification
schema_version: "1.0.0"           # Version of agent schema format
agent_type: "pr_review"           # Type classification for routing
definition_format: "yaml_agent_v1" # Format identifier
priority: "high"                  # Routing priority: high | medium | low
specialization: "domain_name"     # Domain specialization for matching

# Agent Identity - Core identification and purpose
agent_identity:
  name: "agent-name"              # Canonical agent name
  short_name: "name"              # Short form for display
  aliases: ["alias1", "alias2"]   # Alternative names for fuzzy matching
  title: "Agent Title"            # Human-readable title
  description: "..."              # Full description
  domain: "domain_context"        # Primary domain
  color: "green"                  # UI color: green|blue|orange|red|purple|gray|cyan|teal|yellow
  core_purpose: "..."             # Primary mission statement
  task_agent_type: "type"         # Task routing type
  specialization_level: "expert"  # expert | specialist | general

  specializations:                # List of specialized capabilities
    - "Capability 1"
    - "Capability 2"

# Agent Philosophy - Guiding principles and methodology
agent_philosophy:
  approach: "..."                 # High-level approach description
  core_responsibility: "..."      # Single responsibility statement

  core_principles:                # Guiding principles
    - "Principle 1"
    - "Principle 2"

  methodology:
    primary: "Method Name"        # Primary methodology (e.g., "ONEX Anti-YOLO Method")
    quality_gates: "..."          # Quality gate approach
    compliance: "..."             # Compliance requirements

# Capabilities - What the agent can do
capabilities:
  primary_functions:              # Main capabilities with performance targets
    - name: "Function Name"
      description: "What it does"
      performance_target: "<100ms response time"  # Measurable target

  secondary:                      # Secondary capabilities
    - "Capability description"

  specialized:                    # Domain-specific capabilities
    - "Specialized capability"

  specialized_capabilities:       # Grouped specialized capabilities
    category_name:
      - "Capability 1"
      - "Capability 2"

# Framework Integration - YAML framework references
framework_integration:
  yaml_framework_references:
    - "@core-requirements.yaml"
    - "@quality-gates-spec.yaml"

  domain_queries:
    domain: "keyword1 keyword2"
    implementation: "pattern1 pattern2"

  mandatory_functions:            # Required function implementations
    - "function_name() - Description"

  template_system:
    primary_template: "template_name"
    config_path: "/configs/agent.yaml"
    parameters:
      match_count: 5
      confidence_threshold: 0.6

  pattern_catalog:
    applicable_patterns:
      - "CDP-001: Clean Design Principles"
      - "QAP-001: Quality Assurance Protocols"

# ONEX Integration - Operational excellence requirements
onex_integration:
  architecture_reference: "@ONEX_4_Node_System_Developer_Guide.md"
  strong_typing: "ZERO tolerance for Any types"
  error_handling: "OnexError with proper exception chaining"
  naming_conventions: "ONEX naming patterns"
  contract_driven: "Validated contracts before implementation"
  registry_pattern: "Dependency injection for services"

  four_node_coordination:         # For orchestrator agents
    effect:
      responsibilities: "External interactions, APIs"
      routing_criteria: "API requests, UI updates"
      agent_types: ["agent-api-architect", "agent-frontend-developer"]
    compute:
      responsibilities: "Data processing, business logic"
      routing_criteria: "Algorithm implementation"
      agent_types: ["agent-python-fastapi-expert"]
    reducer:
      responsibilities: "State management, persistence"
      routing_criteria: "Database operations"
      agent_types: ["agent-repository-setup"]
    orchestrator:
      responsibilities: "Workflow coordination"
      routing_criteria: "Workflow management"
      agent_types: ["polymorphic-agent"]

# Intelligence Integration - AI-enhanced capabilities
intelligence_integration:
  focus_areas:
    - "Quality-Enhanced: Code quality analysis"
    - "Performance-Assisted: Performance optimization"

  quality_assessment:
    - "assess_code_quality()"
    - "check_architectural_compliance()"

  success_metrics:
    - "100% integration of quality insights"

# Activation Patterns - How the agent is triggered
activation_patterns:
  primary_triggers:               # Explicit trigger scenarios
    - "Complex task decomposition"
    - "Multi-agent coordination"

  activation_keywords:            # Keywords for fuzzy matching
    - "keyword1"
    - "keyword2"
    - "phrase with spaces"

  explicit_triggers:              # Alternative trigger format
    - "trigger phrase"

  context_triggers:               # Context-based triggers
    - "When user is doing X"

  context_requirements:           # Required context
    - "Task complexity data"
    - "Project requirements"

  capability_matching:            # Capability-based routing
    - "Code quality assessment needs"

  success_indicators:             # Success criteria
    - ">95% success rate"

# Workflow Templates - Execution patterns
workflow_templates:
  initialization:
    function_name: "establish_context"
    phases:
      - "Initialize correlation context"
      - "Repository detection"

  intelligence_gathering:
    function_name: "gather_intelligence"
    phases:
      - "Execute RAG queries"
      - "Search code examples"

  task_execution:
    function_name: "execute_task"
    phases:
      - "Analyze requirements"
      - "Execute with quality gates"

  knowledge_capture:
    function_name: "capture_knowledge"
    phases:
      - "Document methodology"
      - "Contribute to intelligence"

# Quality Gates - Enforceable requirements
quality_gates:
  must_have_requirements:
    - "No Any types used"
    - "Proper OnexError usage"

  quality_standards:
    - "Code is readable"
    - "Error handling implemented"

  coverage_requirements:
    - "Unit tests: >=90% coverage"

  performance_requirements:
    - "Test execution: <200ms"

# Integration Points - Agent collaboration
integration_points:
  complementary_agents:
    - "agent-security-audit: Security assessment"
    - "agent-performance: Performance analysis"

  collaboration_patterns:
    - "Route to X for Y needs"

# Transformation Context - Dynamic role assumption
transformation_context:
  identity_assumption_triggers:
    - "User requests specific assistance"

  capability_inheritance:
    - "Full domain expertise"

  execution_context:
    - "Maintain focus throughout"

# Claude Skills Integration
claude_skills_references:
  - "@skill-name - Description"

# Git Policy
git_policy:
  auto_commit: "NEVER"
  commit_behavior: "ONLY on explicit request"

# Metadata
version: "2.0.0"
schema_compliance: "dynamic_role_system_v1"
performance_target: "<0.5ms access time"
```

---

## Agent Categories

### Coordination Agents (7)

Core orchestration and workflow management.

| Agent | Description | Priority | Key Triggers |
|-------|-------------|----------|--------------|
| **polymorphic-agent** | Main orchestrator for multi-agent workflows and dynamic role transformation (Polly) | high | `polly`, `poly`, `coordinate`, `orchestrate workflow`, `spawn poly` |
| **multi-step-framework** | Complex multi-step workflow orchestration | high | `multi-step`, `workflow`, `complex task` |
| **onex-coordinator** | ONEX system coordination and 4-node architecture navigation | high | `onex`, `coordinate`, `architecture` |
| **ticket-manager** | AI-powered ticket management with dependency analysis | high | `ticket`, `issue`, `task management` |
| **parameter-collector** | Intelligent parameter collection with prompts and validation | high | `collect parameters`, `workflow parameters` |
| **overnight-automation** | Long-running automated workflows | medium | `overnight`, `automation`, `batch` |
| **workflow-generator** | Workflow template generation and optimization | medium | `generate workflow`, `workflow template` |

### Quality Assurance Agents (8)

Testing, code quality, and compliance verification.

| Agent | Description | Priority | Key Triggers |
|-------|-------------|----------|--------------|
| **pr-review** | Pull request review and merge readiness assessment | high | `pr review`, `code review`, `merge readiness` |
| **testing** | Comprehensive test strategy and quality assurance | high | `test`, `testing`, `quality assurance`, `coverage` |
| **code-quality-analyzer** | Code quality metrics and ONEX compliance verification | high | `code quality`, `quality analysis`, `anti-patterns` |
| **contract-validator** | Contract validation and standards compliance | high | `contract`, `validate`, `standards` |
| **type-validator** | Type safety validation and type checking | high | `type check`, `type safety`, `typing` |
| **security-audit** | Vulnerability assessment and compliance validation | high | `security`, `audit`, `vulnerability` |
| **ui-testing** | UI component testing and visual validation | medium | `ui test`, `visual test`, `component test` |
| **address-pr-comments** | Systematic PR comment resolution | medium | `address comments`, `fix pr feedback` |

### Development Agents (14)

Core coding, debugging, and implementation.

| Agent | Description | Priority | Key Triggers |
|-------|-------------|----------|--------------|
| **python-fastapi-expert** | Python/FastAPI development specialist | high | `python`, `fastapi`, `async`, `backend` |
| **frontend-developer** | React/TypeScript UI development | high | `frontend`, `react`, `typescript`, `ui component` |
| **debug** | Systematic troubleshooting and incident documentation | high | `debug`, `troubleshoot`, `investigate` |
| **debug-intelligence** | Advanced debugging with root cause analysis | high | `debug`, `error`, `root cause`, `bug` |
| **debug-database** | Database-specific debugging | medium | `database debug`, `sql issue`, `db error` |
| **debug-log-writer** | Structured debug log creation | medium | `debug log`, `log investigation` |
| **ast-generator** | AST-based code generation | high | `ast`, `generate code`, `scaffold` |
| **performance** | Bottleneck detection and system optimization | high | `performance`, `optimization`, `bottleneck` |
| **commit** | Semantic commit message generation | medium | `commit`, `git commit`, `semantic commit` |
| **repository-crawler** | Repository analysis and knowledge extraction | medium | `crawl`, `index codebase`, `repository analysis` |
| **repository-crawler-claude-code** | Claude Code specific repository indexing | medium | `claude code crawl`, `index for claude` |
| **context-gatherer** | Context collection and synthesis | medium | `gather context`, `collect context` |
| **structured-logging** | Structured logging implementation | medium | `logging`, `structured logs` |
| **velocity-tracker** | Development velocity tracking | medium | `velocity`, `sprint tracking` |

### Architecture Agents (8)

System design and architectural planning.

| Agent | Description | Priority | Key Triggers |
|-------|-------------|----------|--------------|
| **api-architect** | RESTful API design and FastAPI optimization | high | `api design`, `openapi`, `fastapi`, `microservices` |
| **contract-driven-generator** | Contract-first code generation | high | `contract driven`, `generate from contract` |
| **onex-readme** | ONEX documentation generation | medium | `onex readme`, `documentation` |
| **pr-create** | Pull request creation workflow | high | `create pr`, `new pull request` |
| **pr-workflow** | Multi-step PR workflow orchestration | high | `pr workflow`, `systematic pr` |
| **pr-ticket-writer** | PR-to-ticket conversion | medium | `pr ticket`, `create ticket from pr` |
| **quota-optimizer** | Resource quota optimization | medium | `quota`, `resource optimization` |
| **research** | Research and investigation specialist | medium | `research`, `investigate`, `explore` |

### Infrastructure Agents (6)

DevOps, monitoring, and infrastructure management.

| Agent | Description | Priority | Key Triggers |
|-------|-------------|----------|--------------|
| **devops-infrastructure** | Container orchestration and CI/CD optimization | high | `devops`, `infrastructure`, `docker`, `kubernetes` |
| **production-monitor** | 24/7 production monitoring and observability | high | `production`, `monitor`, `observability`, `alerting` |
| **agent-observability** | Agent execution health and diagnostics | high | `observability`, `agent health`, `diagnostics` |
| **repository-setup** | Repository initialization and configuration | high | `repository setup`, `repo init`, `project setup` |
| **intelligence-initializer** | Intelligence system initialization | medium | `init intelligence`, `setup intelligence` |
| **omniagent-batch-processor** | Batch processing automation | medium | `batch`, `bulk process` |

### Documentation Agents (5)

Technical documentation and knowledge management.

| Agent | Description | Priority | Key Triggers |
|-------|-------------|----------|--------------|
| **documentation-architect** | Technical documentation architecture | high | `documentation`, `docs`, `api docs`, `developer experience` |
| **documentation-indexer** | Documentation indexing and search | medium | `index docs`, `documentation search` |
| **rag-query** | RAG query execution | medium | `rag query`, `knowledge query` |
| **rag-update** | RAG knowledge base updates | medium | `update rag`, `add to knowledge` |
| **velocity-log-writer** | Velocity log documentation | medium | `velocity log`, `sprint log` |

### Content Processing Agents (1)

Content transformation and summarization.

| Agent | Description | Priority | Key Triggers |
|-------|-------------|----------|--------------|
| **content-summarizer** | Intelligent content summarization | medium | `summarize`, `condense`, `extract key information` |

### Special Purpose Agents (4)

Domain-specific integrations.

| Agent | Description | Priority | Key Triggers |
|-------|-------------|----------|--------------|
| **omniagent-archon-tickets** | Archon ticket integration | medium | `archon ticket`, `archon issue` |
| **omniagent-smart-responder** | Intelligent response generation | medium | `smart response`, `auto respond` |
| **agent-address-pr-comments** | Automated PR comment handling | medium | `address pr`, `fix comments` |

---

## Complete Agent List (53 Agents)

```
address-pr-comments          multi-step-framework
agent-address-pr-comments    omniagent-archon-tickets
agent-observability          omniagent-batch-processor
agent-registry               omniagent-smart-responder
api-architect                onex-coordinator
ast-generator                onex-readme
code-quality-analyzer        overnight-automation
commit                       parameter-collector
content-summarizer           performance
context-gatherer             polymorphic-agent
contract-driven-generator    pr-create
contract-validator           pr-review
debug                        pr-ticket-writer
debug-database               pr-workflow
debug-intelligence           production-monitor
debug-log-writer             python-fastapi-expert
devops-infrastructure        quota-optimizer
documentation-architect      rag-query
documentation-indexer        rag-update
frontend-developer           repository-crawler
intelligence-initializer     repository-crawler-claude-code
                             repository-setup
                             research
                             security-audit
                             structured-logging
                             testing
                             ticket-manager
                             type-validator
                             ui-testing
                             velocity-log-writer
                             velocity-tracker
                             workflow-generator
```

---

## How the Polymorphic Framework Uses YAML

### Agent Resolution Flow

```
User Request
    |
    v
+-------------------+
|  Parse Request    |  Extract intent, keywords, context
+-------------------+
    |
    v
+-------------------+
|  Registry Lookup  |  Query agent-registry.yaml (<0.5ms)
+-------------------+
    |
    v
+-------------------+
|  Trigger Match    |  Fuzzy match against activation_keywords
+-------------------+
    |
    v
+-------------------+
|  Load Agent YAML  |  Load full definition from file
+-------------------+
    |
    v
+-------------------+
|  Transform        |  Polymorphic agent assumes identity
+-------------------+
    |
    v
+-------------------+
|  Execute          |  Execute with inherited capabilities
+-------------------+
```

### Key Resolution Mechanisms

1. **Alias Matching**: The `aliases` field allows fuzzy matching:
   ```yaml
   aliases: ["polly", "poly", "workflow-coordinator", "onex-coordinator"]
   ```

2. **Trigger Keywords**: The `activation_keywords` enable intent detection:
   ```yaml
   activation_keywords:
     - "polly"
     - "spawn poly"
     - "coordinate"
     - "orchestrate workflow"
   ```

3. **Capability Matching**: Route based on required capabilities:
   ```yaml
   capabilities:
     primary:
       - name: "Multi-Agent Orchestration"
         performance_target: "Support 5+ concurrent agents"
   ```

4. **Context Requirements**: Validate context before routing:
   ```yaml
   context_requirements:
     - "Task complexity assessment data"
     - "Available agent capabilities"
   ```

### Performance Characteristics

| Metric | Target | Description |
|--------|--------|-------------|
| Registry load | <50ms | Initial registry.yaml parse |
| Agent resolution | <25ms | Trigger matching and selection |
| Identity assumption | <100ms | Full agent definition loading |
| **Total overhead** | **<175ms** | Complete transformation |
| Context reduction | 75% | Compared to individual .md files |

### Programmatic Benefits

1. **Validation**: Schema can be validated at startup
   ```python
   def validate_agent_schema(agent_yaml: dict) -> bool:
       required_fields = ["agent_identity", "capabilities", "activation_patterns"]
       return all(field in agent_yaml for field in required_fields)
   ```

2. **Performance Target Enforcement**: Targets are machine-parseable
   ```python
   def check_performance_target(target: str) -> tuple[str, float]:
       # Parse "<100ms response time" -> ("ms", 100)
       match = re.match(r"<(\d+)(ms|s)", target)
       return match.groups() if match else None
   ```

3. **Quality Gate Automation**: Gates can be programmatically checked
   ```python
   def enforce_quality_gates(agent: dict) -> list[str]:
       gates = agent.get("quality_gates", {})
       violations = []
       if "ZERO tolerance for Any" in str(gates):
           # Run mypy check for Any types
           ...
       return violations
   ```

4. **ONEX Compliance Checking**: Architectural compliance is verifiable
   ```python
   def verify_onex_compliance(agent: dict) -> bool:
       onex = agent.get("onex_integration", {})
       return (
           onex.get("strong_typing") and
           onex.get("error_handling") and
           onex.get("registry_pattern")
       )
   ```

---

## Agent Registry

The `agent-registry.yaml` provides centralized discovery:

```yaml
schema_version: "1.0.0"
total_agents: 52
registry_type: "dynamic_role_system"

categories:
  development:
    description: "Core development and coding agents"
    count: 14
    priority: "high"
  # ... more categories

agents:
  api-architect:
    name: "agent-api-architect"
    title: "API Architect Specialist"
    category: "architecture"
    priority: "high"
    capabilities: ["api_design", "openapi_specs", "fastapi_optimization"]
    activation_triggers: ["api design", "openapi", "rest api"]
    definition_path: "agents/onex/api-architect.yaml"
  # ... more agents

transformation_config:
  base_agent: "agent-polymorphic-agent"
  transformation_method: "identity_assumption"
  performance_target_ms: 500
```

---

## ONEX 4-Node Architecture

All agents follow the ONEX 4-node architecture:

| Node Type | Purpose | Example Agents |
|-----------|---------|----------------|
| **Effect** | External I/O, APIs, UI | api-architect, frontend-developer, parameter-collector |
| **Compute** | Data processing, algorithms | python-fastapi-expert, performance, ast-generator |
| **Reducer** | State management, persistence | repository-setup, structured-logging, debug-database |
| **Orchestrator** | Workflow coordination | polymorphic-agent, multi-step-framework, testing |

### ONEX Compliance Requirements

All agents enforce:

- **Strong Typing**: Zero tolerance for `Any` types
- **Error Handling**: OnexError with proper exception chaining
- **Naming Conventions**: ONEX naming patterns (ModelX, NodeXEffect, etc.)
- **Contract-Driven**: Validated contracts before implementation
- **Registry Pattern**: Dependency injection for services

---

## Performance Targets

| Metric | Target | Critical Threshold |
|--------|--------|-------------------|
| Agent routing | <10ms | >100ms |
| Quality gates | <200ms | >500ms |
| Manifest query | <2000ms | >5000ms |
| Routing accuracy | >95% | <80% |
| Agent resolution | <25ms | >100ms |
| Transformation overhead | <175ms | >500ms |

---

## License

MIT License - see the main OmniClaude repository for details.

---

## Related

- [OmniClaude Repository](https://github.com/OmniNode-ai/omniclaude)
- [ONEX Standards](./docs/onex/)
- [Agent Registry](./agents/agent-registry.yaml)
- [Polymorphic Agent Definition](./agents/polymorphic-agent.yaml)
