# Node Behavior Map

> Quick reference: for any node, where does each piece of behavior live?

## Standard Node Anatomy

Every ONEX node in omniclaude follows this structure:

| Layer | File | What It Controls |
|-------|------|-----------------|
| **Contract** | `contract.yaml` | Capabilities, I/O models, error budgets, handler routing, retry policy |
| **Node** | `node.py` | Thin orchestration shell -- delegates to protocol/handler |
| **Protocol** | `protocols/protocol_*.py` | Runtime-checkable interface the handler must satisfy |
| **Handler/Backend** | `handlers/` or `backends/` | Actual business logic implementation |
| **Models** | `models/model_*.py` | Strongly typed input/output Pydantic models |
| **CI checks** | `scripts/validation/` + `.github/workflows/ci.yml` | Naming, imports, architecture rules |
| **Hooks** | `plugins/onex/hooks/` | Session lifecycle, event emission, context injection |

## Key Nodes -- Behavior Location

### Transition Selector (`node_transition_selector_effect`)

| Question | Answer | File:Line |
|----------|--------|-----------|
| What does it do? | Selects next navigation action via local LLM classification | `contract.yaml` |
| Where is the prompt built? | `_build_prompt()` | `node.py` |
| Where is the LLM called? | `_call_model()` | `node.py` |
| What model is used? | Qwen3-14B via `LLM_CODER_FAST_URL` | `contract.yaml:handler_routing` |
| What errors can occur? | 5 kinds in `SelectionErrorKind` | `models/model_transition_selector_result.py` |
| What protocol must it satisfy? | `ProtocolTransitionSelector.select()` | `protocols/protocol_transition_selector.py` |

### Local LLM Inference (`node_local_llm_inference_effect`)

| Question | Answer | File:Line |
|----------|--------|-----------|
| What does it do? | Generic LLM inference with pluggable backends | `contract.yaml` |
| Where is inference logic? | `VllmInferenceBackend.infer()` | `backends/backend_vllm.py` |
| How are endpoints resolved? | `LocalLlmEndpointRegistry` by purpose | `config/model_local_llm_config.py` |
| What purposes are supported? | 7: ROUTING, CODE_ANALYSIS, EMBEDDING, GENERAL, VISION, FUNCTION_CALLING, REASONING | `config/model_local_llm_config.py:66` |

### Agent Routing (`node_agent_routing_compute`)

| Question | Answer | File:Line |
|----------|--------|-----------|
| What does it do? | Routes prompts to specialized agents | `contract.yaml` |
| Where is LLM routing? | `HandlerRoutingLlm` | `handler_routing_llm.py` |
| What is the fallback? | `HandlerRoutingDefault` (trigger matching, no LLM) | `handler_routing_default.py` |

## How to Find Behavior for Any Node

1. **Start with the contract**: `src/omniclaude/nodes/<node_name>/contract.yaml`
   - This tells you capabilities, I/O types, error handling, and handler routing
2. **Check the node class**: `node.py` -- usually thin, shows orchestration flow
3. **Find the protocol**: `protocols/` -- the interface contract handlers must implement
4. **Read the handler/backend**: `handlers/` or `backends/` -- where the real work happens
5. **Check models**: `models/` -- the strongly typed data shapes

## Validation Path for a PR

See `docs/reference/PR_VALIDATION_PATH.md` for the complete list of checks a PR goes through.
