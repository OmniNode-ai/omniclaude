# Claude Toggle Multi-Provider Support Plan

## Overview
Enhance the existing `toggle-claude-provider.sh` script to support multiple third-party providers through a flexible configuration-based approach, replacing hardcoded provider logic.

## Current State
- Single hardcoded Z.ai provider configuration
- Limited to GLM model mapping
- Hardcoded API keys and rate limits
- Manual script updates needed for new providers

## Proposed Solution

### 1. Configuration File Structure
**File**: `claude-providers.json`

```json
{
  "providers": {
    "provider_id": {
      "name": "Human Readable Name",
      "description": "Provider description",
      "base_url": "https://api.example.com/anthropic",
      "api_key": "key_or_env_var",
      "models": {
        "haiku": "model-name-haiku",
        "sonnet": "model-name-sonnet",
        "opus": "model-name-opus"
      },
      "rate_limits": {
        "model-name-haiku": 5,
        "model-name-sonnet": 20,
        "model-name-opus": 10
      },
      "setup_vars": {
        "ANTHROPIC_BASE_URL": "{{base_url}}",
        "ANTHROPIC_AUTH_TOKEN": "{{api_key}}",
        "ANTHROPIC_DEFAULT_HAIKU_MODEL": "{{models.haiku}}",
        "ANTHROPIC_DEFAULT_SONNET_MODEL": "{{models.sonnet}}",
        "ANTHROPIC_DEFAULT_OPUS_MODEL": "{{models.opus}}"
      }
    }
  },
  "settings": {
    "default_provider": "anthropic",
    "backup_suffix": ".backup"
  }
}
```

### 2. Supported Providers

#### Anthropic (Native)
- No base_url (null)
- Uses ANTHROPIC_API_KEY environment variable
- Cleans up all custom variables

#### Z.ai (Current)
- Base: `https://api.z.ai/api/anthropic`
- Models: GLM-4.5-Air, GLM-4.5, GLM-4.6
- Rate limits: 5, 20, 10 concurrent

#### Together AI (New)
- Base: `https://api.together.xyz/api/anthropic`
- Models: Llama-3.1 variants
- Rate limits: 50, 20, 10 concurrent

#### OpenRouter (New)
- Base: `https://openrouter.ai/api/v1/anthropic`
- Models: Anthropic models via OpenRouter
- Rate limits: OpenRouter-specific

### 3. Script Enhancement Plan

#### Phase 1: Configuration Loading
- Load `claude-providers.json`
- Validate JSON structure
- Handle missing config file gracefully
- Support config file path override

#### Phase 2: Dynamic Provider Management
- Replace hardcoded provider logic
- Add provider discovery (`./toggle-claude-provider.sh list`)
- Dynamic provider switching (`./toggle-claude-provider.sh zai`)
- Configuration validation

#### Phase 3: Enhanced Features
- Rate limit calculation and display
- API key validation (basic format check)
- Configuration file template generation
- Provider comparison tools

#### Phase 4: User Experience
- Better error messages
- Interactive provider selection
- Configuration file editing assistance
- Migration from current setup

### 4. Implementation Steps

1. **Create configuration file** with initial providers
2. **Update toggle script** to read configuration
3. **Implement provider validation** and error handling
4. **Add new command line options** for provider management
5. **Test migration** from current Z.ai setup
6. **Add documentation** and usage examples

### 5. Backward Compatibility
- Current Z.ai configuration remains functional
- Automatic migration from hardcoded settings
- Fallback to original behavior if config missing

### 6. Security Considerations
- API key validation without exposing values
- Secure handling of sensitive configuration
- Warning for placeholder API keys
- Support for environment variable references

### 7. Future Extensibility
- Easy addition of new providers
- Support for provider-specific features
- Custom model mapping capabilities
- Provider performance tracking

## Benefits

### For Users
- **Multi-provider support**: Choose from various AI providers
- **Easy customization**: Edit JSON instead of bash script
- **Better rate limiting**: Clear visibility of concurrency limits
- **Provider comparison**: Side-by-side feature comparison

### For Maintenance
- **Configuration-driven**: Add providers without code changes
- **Validation**: Built-in configuration checking
- **Documentation**: Self-documenting provider configurations
- **Testing**: Easier to test new provider setups

## Migration Path

1. **Phase 1**: Deploy alongside existing script
2. **Phase 2**: Automatic migration of current Z.ai setup
3. **Phase 3**: Deprecate hardcoded logic
4. **Phase 4**: Remove legacy code (future version)

## Success Metrics
- Zero breaking changes for existing users
- Support for 3+ providers out of the box
- <5 minutes to add new provider
- Clear rate limit visibility
- Robust error handling and validation

## Next Steps

1. ✅ Create initial configuration file structure
2. 🔄 Update toggle script with configuration support
3. ⏳ Add provider validation and selection logic
4. ⏳ Test migration from current setup
5. ⏳ Add documentation and examples