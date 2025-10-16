# Mixin Compatibility ML Models

## Overview

This directory contains trained machine learning models for predicting mixin compatibility in the ONEX architecture. The models use an ensemble approach (RandomForest + GradientBoosting) to predict whether two mixins can be safely combined on a specific node type, achieving 100% accuracy on test data with 95.48% cross-validation accuracy.

The ML system learns from historical mixin combination success/failure data stored in PostgreSQL and provides intelligent recommendations for optimal mixin sets.

## Model Files

| File | Size | Description |
|------|------|-------------|
| `mixin_compatibility_rf.pkl` | 282 KB | Primary RandomForest classifier with 200 estimators |
| `mixin_compatibility_metrics.pkl` | 393 B | Model performance metrics and training metadata |

## Model Architecture

### Ensemble Configuration

The system uses an ensemble of two gradient-boosted tree models:

1. **Primary Model: RandomForest Classifier**
   - 200 estimators (decision trees)
   - Max depth: 20 levels
   - Min samples split: 3
   - Min samples leaf: 1
   - Max features: sqrt (square root of total features)
   - Class weight: balanced (handles imbalanced data)
   - Out-of-bag scoring: enabled

2. **Secondary Model: GradientBoosting Classifier**
   - 150 estimators
   - Max depth: 10 levels
   - Learning rate: 0.1
   - Subsample: 0.9

**Ensemble Strategy**: The RandomForest model serves as the primary predictor. When predictions disagree between models, the RF probability threshold (>0.6) determines the final prediction. When both models agree, confidence is boosted.

### Feature Engineering

The system extracts **83 features** per mixin pair:

#### Per-Mixin Features (30 features × 2 mixins = 60 features)
- **One-hot encoding** (16 features): Identifies specific mixin type
- **Category encoding** (4 features): Infrastructure, resilience, business, data_access
- **Characteristics** (10 features):
  - `async_safe`: Whether mixin supports async operations
  - `state_modifying`: Whether mixin modifies state
  - `resource_intensive`: Whether mixin uses significant resources
  - `n_dependencies`: Count of external system dependencies
  - `n_lifecycle_hooks`: Count of lifecycle methods used
  - Tag indicators: `cache`, `resilience`, `security`, `database`, `messaging`

#### Node Type Features (8 features)
- **One-hot encoding** (4 features): EFFECT, COMPUTE, REDUCER, ORCHESTRATOR
- **Profile characteristics** (4 features):
  - `async_required`: Node type requires async operations
  - `state_modifying`: Node type modifies state
  - `resource_intensive`: Node type uses significant resources
  - `external_access`: Node type accesses external systems

#### Interaction Features (15 features)
- `same_category`: Whether mixins share the same category
- `hook_overlap`: Number of shared lifecycle hooks
- `hook_conflict`: Binary indicator of lifecycle conflicts
- `dep_overlap`: Number of shared external dependencies
- `both_modify_state`: Binary indicator if both modify state
- `both_resource_intensive`: Binary indicator if both are resource-intensive
- `tag_overlap`: Number of shared compatibility tags
- `async_compatible`: Binary indicator of async compatibility
- `historical_success_rate`: Past success rate from database (0.0-1.0)
- `historical_total_tests`: Normalized count of historical tests
- `historical_avg_compatibility`: Average historical compatibility score
- `category_tag_match`: Strong indicator (same category + shared tags)
- `high_conflict_potential`: Conflict indicator (hooks + state modification)
- `total_dependencies`: Sum of external dependencies
- `involves_data_access`: Binary indicator for data access layer

**Total**: 83 features

## Training Data

### Data Source
- **Database**: PostgreSQL `mixin_compatibility_matrix` table
- **Query**: Fetches all mixin pairs with ≥3 combined success/failure tests
- **Ordering**: By `created_at DESC` (most recent first)

### Sample Requirements
- **Minimum samples**: 50 pairs required to train
- **Test split**: 20% of data reserved for testing
- **Stratification**: Yes (ensures balanced class distribution in splits)

### Label Generation
- **Compatible (1)**: `success_rate > 0.5` (more successes than failures)
- **Incompatible (0)**: `success_rate ≤ 0.5` (more failures than successes)

## Model Performance

### Current Metrics (Last Training: 2025-10-16 14:29:38 UTC)

| Metric | Value |
|--------|-------|
| **Accuracy** | 100.00% (1.0000) |
| **Precision** | 100.00% (1.0000) |
| **Recall** | 100.00% (1.0000) |
| **F1 Score** | 100.00% (1.0000) |
| **Cross-validation Mean** | 95.48% ± 6.94% |
| **Training Samples** | 65 pairs |
| **Test Samples** | 17 pairs |

### Performance Notes
- Perfect accuracy on test set (100%) indicates excellent learning on current data
- Cross-validation accuracy (95.48%) provides more realistic estimate of generalization
- Standard deviation (6.94%) suggests some variability across folds, expected with small dataset
- As dataset grows, expect cross-validation accuracy to stabilize near test accuracy

## Usage

### Load Pre-trained Model

```python
from agents.lib.mixin_learner import MixinLearner

# Initialize learner (auto-loads model from default path)
learner = MixinLearner()

# Check if model is loaded
if learner.is_trained():
    print("Model loaded successfully")
    print(f"Trained on {learner.metrics.training_samples} samples")
```

### Predict Compatibility

```python
# Predict compatibility between two mixins
prediction = learner.predict_compatibility(
    mixin_a="MixinCaching",
    mixin_b="MixinLogging",
    node_type="EFFECT"
)

print(f"Compatible: {prediction.compatible}")
print(f"Confidence: {prediction.confidence:.2%}")
print(f"Explanation: {prediction.explanation}")
```

### Get Mixin Recommendations

```python
# Recommend mixins for a node type
recommendations = learner.recommend_mixins(
    node_type="EFFECT",
    required_capabilities=["caching", "logging", "metrics"],
    existing_mixins=["MixinCaching"],
    max_recommendations=5
)

for mixin_name, confidence, explanation in recommendations:
    print(f"{mixin_name}: {confidence:.2%} - {explanation}")
```

### High-Level Compatibility Manager

```python
from agents.lib.mixin_compatibility import MixinCompatibilityManager

# Initialize manager (uses MixinLearner internally)
manager = MixinCompatibilityManager(enable_ml=True)

# Check compatibility
check = await manager.check_compatibility(
    mixin_a="MixinRetry",
    mixin_b="MixinCircuitBreaker",
    node_type="EFFECT"
)

print(f"Compatibility Level: {check.level.value}")
print(f"Confidence: {check.confidence:.2%}")
print(f"Reasons: {check.reasons}")
print(f"Suggestions: {check.suggestions}")

# Validate entire mixin set
mixin_set = await manager.validate_mixin_set(
    mixins=["MixinCaching", "MixinLogging", "MixinMetrics"],
    node_type="EFFECT"
)

print(f"Overall Compatibility: {mixin_set.overall_compatibility:.2%}")
if mixin_set.warnings:
    print(f"Warnings: {mixin_set.warnings}")
```

## Training New Model

### Prerequisites
1. PostgreSQL database with `mixin_compatibility_matrix` table populated
2. At least 50 mixin pair records with ≥3 tests each
3. Database credentials configured in `CodegenPersistence`

### Training Steps

```python
import asyncio
from agents.lib.mixin_learner import MixinLearner
from agents.lib.persistence import CodegenPersistence

async def train_new_model():
    # Initialize learner
    persistence = CodegenPersistence()
    learner = MixinLearner(persistence=persistence, auto_train=False)

    # Train model
    try:
        metrics = await learner.train_model(
            min_samples=50,         # Minimum training samples required
            test_size=0.2,          # 20% for testing
            cross_val_folds=5       # 5-fold cross-validation
        )

        print("Training completed successfully!")
        print(f"Accuracy: {metrics.accuracy:.2%}")
        print(f"Precision: {metrics.precision:.2%}")
        print(f"Recall: {metrics.recall:.2%}")
        print(f"F1 Score: {metrics.f1_score:.2%}")
        print(f"Cross-validation: {sum(metrics.cross_val_scores)/len(metrics.cross_val_scores):.2%}")

    except ValueError as e:
        print(f"Training failed: {e}")
        print("Ensure sufficient training data exists in database")

# Run training
asyncio.run(train_new_model())
```

### Continuous Learning

The system supports continuous learning from new feedback:

```python
# Record compatibility feedback
await learner.update_from_feedback(
    mixin_a="MixinCaching",
    mixin_b="MixinLogging",
    node_type="EFFECT",
    success=True,
    retrain_threshold=100  # Retrain after 100 new samples
)
```

The model automatically retrains when new samples exceed `retrain_threshold` beyond the original training set size.

## Feature Categories

### 16 Supported Mixins
Infrastructure (5): `MixinCaching`, `MixinLogging`, `MixinMetrics`, `MixinHealthCheck`, `MixinEventBus`
Resilience (4): `MixinRetry`, `MixinCircuitBreaker`, `MixinTimeout`, `MixinRateLimiter`
Business (4): `MixinValidation`, `MixinSecurity`, `MixinAuthorization`, `MixinAudit`
Data Access (3): `MixinTransaction`, `MixinConnection`, `MixinRepository`

### 4 Node Types
- **EFFECT**: External I/O, APIs, side effects (async required, state modifying)
- **COMPUTE**: Pure transforms/algorithms (no async, stateless)
- **REDUCER**: Aggregation, persistence, state (async required, state modifying)
- **ORCHESTRATOR**: Workflow coordination (async required, stateless)

## Dependencies

### Required Python Packages
- `scikit-learn>=1.3.0` - Machine learning algorithms
- `numpy>=1.24.0` - Numerical computing
- `asyncpg>=0.28.0` - PostgreSQL async driver (for training data)

### Optional Dependencies
- `pickle` - Model serialization (standard library)
- `logging` - Logging framework (standard library)

## Regenerating Models

### When to Regenerate
1. **New mixin types added**: Add characteristics to `MixinFeatureExtractor.MIXIN_CHARACTERISTICS`
2. **Significant new training data**: ≥100 new compatibility tests recorded
3. **Model performance degradation**: Cross-validation accuracy drops below 90%
4. **Feature engineering changes**: New features added to extractor

### Regeneration Process

```bash
# 1. Ensure database has sufficient training data
psql -d omniclaude -c "SELECT COUNT(*) FROM mixin_compatibility_matrix WHERE success_count + failure_count >= 3;"

# 2. Run training script
python3 << 'EOF'
import asyncio
from agents.lib.mixin_learner import MixinLearner

async def retrain():
    learner = MixinLearner()
    metrics = await learner.train_model(min_samples=50)
    print(f"New model trained: {metrics.accuracy:.2%} accuracy")

asyncio.run(retrain())
EOF

# 3. Verify new model files
ls -lh agents/models/mixin_compatibility_*.pkl

# 4. Run validation tests
pytest agents/tests/test_mixin_learner.py -v
```

## Related Files

### Core Implementation
- [`agents/lib/mixin_learner.py`](../lib/mixin_learner.py) - ML training and prediction logic (lines 82-838)
- [`agents/lib/mixin_features.py`](../lib/mixin_features.py) - Feature extraction engine (lines 73-656)
- [`agents/lib/mixin_compatibility.py`](../lib/mixin_compatibility.py) - High-level compatibility manager (lines 90-517)

### Database Schema
- `mixin_compatibility_matrix` table - Stores historical compatibility data
  - Columns: `mixin_a`, `mixin_b`, `node_type`, `success_count`, `failure_count`, `compatibility_score`, `conflict_reason`, `resolution_pattern`
  - Primary key: `(mixin_a, mixin_b, node_type)`

### Tests
- `agents/tests/test_mixin_learner.py` - Unit tests for ML system
- `agents/tests/test_mixin_features.py` - Feature extraction tests
- `agents/tests/test_mixin_compatibility.py` - Integration tests

## Performance Optimization

### Caching Strategy
The `MixinLearner` implements two-level caching:

1. **Feature Cache**: Stores extracted feature vectors (limit: 1000 entries)
   - Key: `(mixin_a, mixin_b, node_type)` in canonical order
   - Eviction: FIFO (removes oldest 100 when full)

2. **Prediction Cache**: Stores model predictions (limit: 1000 entries)
   - Key: Same as feature cache
   - Eviction: FIFO (removes oldest 100 when full)
   - Speedup: ~10x faster for repeated predictions

### Memory Usage
- Model size: ~282 KB (in memory after unpickling)
- Feature cache: ~83 floats × 1000 = ~664 KB max
- Prediction cache: ~100 bytes × 1000 = ~100 KB max
- **Total**: ~1.05 MB peak memory usage

## Notes

### Automatic Model Loading
- The `MixinLearner` constructor automatically loads models from `agents/models/` if they exist
- No explicit load call required - just instantiate and use
- Falls back to rule-based predictions if model files are missing

### Confidence Adjustment
The system applies structural confidence adjustments based on mixin characteristics:
- **Boost confidence** (+20%) when structural evidence strongly supports prediction
- **Override prediction** when structural score exceeds ±0.30 threshold
- Ensures model predictions align with architectural best practices

### Fallback Behavior
When ML model is unavailable (not trained or disabled):
- Switches to rule-based compatibility checking
- Uses mixin characteristics for scoring
- Provides conservative recommendations (0.6 confidence)

### Model Versioning
- Models are currently not versioned
- Retraining overwrites existing models
- Consider implementing version tracking if model evolution tracking is needed

### Future Enhancements
- **Transfer learning**: Leverage pre-trained models for new mixin types
- **Online learning**: Update model incrementally without full retraining
- **Explainability**: SHAP values or feature importance for prediction explanations
- **Model versioning**: Track model generations and performance over time
- **A/B testing**: Compare new models against production before deployment

---

**Last Updated**: 2025-10-16
**Model Version**: 1.0
**Target Accuracy**: ≥95% (currently: 100% test, 95.48% cross-validation)
