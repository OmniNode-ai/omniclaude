# Example: PostgresCRUD Node Generation

This example demonstrates how the casing preservation fix correctly handles a service name with acronyms throughout the entire generation pipeline.

## User Input

```
EFFECT node called PostgresCRUD for database operations
```

## Pipeline Execution

### Stage 1: Prompt Parsing

**PromptParser.\_extract\_node\_name()**

```python
# Input prompt
prompt = "EFFECT node called PostgresCRUD for database operations"

# Pattern match
pattern = r"(?:called|named)\s+([A-Z][A-Za-z0-9_]+)"
match = re.search(pattern, prompt)

# Extract name (PRESERVES CASING)
name = match.group(1)  # "PostgresCRUD"

# BEFORE FIX ❌: return name.lower()  → "postgrescrud"
# AFTER FIX ✅: return name  → "PostgresCRUD"
```

### Stage 2: Service Name Extraction

**GenerationPipeline.\_extract\_service\_name()**

```python
# Input from parser
node_name = "PostgresCRUD"

# Convert to snake_case for internal storage
def _to_snake_case(text: str) -> str:
    # "PostgresCRUD" → "Postgres_CRUD" → "postgres_crud"
    result = re.sub(r'([a-z0-9])([A-Z])', r'\1_\2', text)
    result = re.sub(r'([A-Z]+)([A-Z][a-z])', r'\1_\2', result)
    return result.lower()

service_name = _to_snake_case(node_name)  # "postgres_crud"

# BEFORE FIX ❌: service_name = "postgrescrud" (lost underscore)
# AFTER FIX ✅: service_name = "postgres_crud" (proper snake_case)
```

### Stage 3: PascalCase Generation

**OmniNodeTemplateEngine.\_to\_pascal\_case()**

```python
# Input from pipeline
microservice_name = "postgres_crud"

# Convert back to PascalCase with acronym awareness
def _to_pascal_case(text: str) -> str:
    CORE_ACRONYMS = {"CRUD", "API", "SQL", ...}

    words = text.split("_")  # ["postgres", "crud"]
    result_parts = []

    for idx, word in enumerate(words):
        word_upper = word.upper()

        if word_upper in CORE_ACRONYMS:
            result_parts.append(word_upper)  # "CRUD"
        else:
            result_parts.append(word.capitalize())  # "Postgres"

    return "".join(result_parts)  # "PostgresCRUD"

pascal_name = _to_pascal_case(microservice_name)  # "PostgresCRUD"

# BEFORE FIX ❌: pascal_name = "Postgrescrud" (lost acronym)
# AFTER FIX ✅: pascal_name = "PostgresCRUD" (preserved acronym)
```

## Generated Output

### Class Definitions

**Node Implementation**
```python
class NodePostgresCRUDEffect(NodeEffect):
    """PostgresCRUD Effect node for database operations."""

    async def execute_effect(
        self,
        contract: ModelPostgresCRUDEffectContract
    ) -> ModelPostgresCRUDOutput:
        # Implementation here
        pass
```

### Model Files

**Input Model** (`v1_0_0/models/model_postgres_crud_input.py`)
```python
class ModelPostgresCRUDInput(BaseModel):
    """Input envelope for postgres_crud operations"""

    operation_type: str = Field(..., description="Type of operation to perform")
    parameters: Dict[str, Any] = Field(default_factory=dict)
```

**Output Model** (`v1_0_0/models/model_postgres_crud_output.py`)
```python
class ModelPostgresCRUDOutput(BaseModel):
    """Output envelope for postgres_crud operations"""

    result_data: Dict[str, Any] = Field(default_factory=dict)
    success: bool = Field(..., description="Operation success status")
```

**Contract Model** (`v1_0_0/models/model_postgres_crud_effect_contract.py`)
```python
class ModelPostgresCRUDEffectContract(BaseModel):
    """Contract model for postgres_crud EFFECT node."""

    INTERFACE_VERSION: ClassVar[ModelSemVer] = ModelSemVer(major=1, minor=0, patch=0)

    contract_version: ModelSemVer = Field(
        default=ModelSemVer(major=1, minor=0, patch=0),
        description="Contract version following semantic versioning",
    )
```

### File Structure

```
node_data_services_postgres_crud_effect/
├── node.manifest.yaml
└── v1_0_0/
    ├── __init__.py
    ├── node.py                                    # NodePostgresCRUDEffect
    ├── contract.yaml
    ├── version.manifest.yaml
    ├── models/
    │   ├── __init__.py
    │   ├── model_postgres_crud_input.py          # ModelPostgresCRUDInput
    │   ├── model_postgres_crud_output.py         # ModelPostgresCRUDOutput
    │   ├── model_postgres_crud_config.py         # ModelPostgresCRUDConfig
    │   └── model_postgres_crud_effect_contract.py # ModelPostgresCRUDEffectContract
    └── enums/
        ├── __init__.py
        └── enum_postgres_crud_operation_type.py  # EnumPostgresCRUDOperationType
```

## Naming Consistency

| Context | Before Fix ❌ | After Fix ✅ |
|---------|--------------|-------------|
| User Input | PostgresCRUD | PostgresCRUD |
| Internal Storage | postgrescrud | postgres_crud |
| Class Names | NodePostgrescrudEffect | NodePostgresCRUDEffect |
| Model Names | ModelPostgrescrudInput | ModelPostgresCRUDInput |
| File Names | model_postgrescrud_input.py | model_postgres_crud_input.py |
| Directory Name | node_data_services_postgrescrud_effect | node_data_services_postgres_crud_effect |

## Key Improvements

1. ✅ **Casing Preserved**: "PostgresCRUD" maintains proper PascalCase throughout
2. ✅ **Acronym Recognition**: "CRUD" recognized and kept uppercase
3. ✅ **Consistent Naming**: Files use proper snake_case with underscores
4. ✅ **Readability**: Class names are clear and follow Python conventions
5. ✅ **ONEX Compliance**: Naming follows ONEX architecture standards

## Round-Trip Validation

```
Input:      PostgresCRUD
  ↓
Snake:      postgres_crud     (storage/file naming)
  ↓
Pascal:     PostgresCRUD      (class naming)
  ✅ VALIDATED: Casing preserved correctly!
```

## Additional Examples

### RestAPI
```
Input:  RestAPI
Snake:  rest_api
Pascal: RestAPI (first word "Rest" capitalized, last word "API" all caps)
Class:  NodeRestAPIEffect
```

### HttpClient
```
Input:  HttpClient
Snake:  http_client
Pascal: HttpClient (first word "Http" capitalized, second word normal)
Class:  NodeHttpClientEffect
```

### SQLConnector
```
Input:  SQLConnector
Snake:  sql_connector
Pascal: SQLConnector ("SQL" always all caps as core acronym)
Class:  NodeSQLConnectorEffect
```

## Conclusion

The casing preservation fix ensures that service names with acronyms are handled correctly throughout the entire generation pipeline, resulting in clean, readable, and standards-compliant generated code.
