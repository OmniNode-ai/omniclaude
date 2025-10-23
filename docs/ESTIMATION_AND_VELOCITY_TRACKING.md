# Estimation & Velocity Tracking System

**Problem**: I'm terrible at estimation (you're right!). Need empirical data to improve.

**Solution**: Track actual time vs estimated time, calculate complexity scores, measure velocity per model.

**Inspired By**: `../omnibase_3/docs/dev_logs/jonah/velocity/`

---

## Architecture Overview

```
┌────────────────────────────────────────────────────────────────┐
│  Task Decomposition (with estimated complexity)                │
│  Example: "Implement Stage 4.5"                                 │
│  ├─ Subtask 1: Create templates (complexity: 3)               │
│  ├─ Subtask 2: Update pipeline (complexity: 5)                │
│  └─ Subtask 3: Write tests (complexity: 2)                    │
│  Total Complexity: 10 story points                             │
└──────────────────────┬─────────────────────────────────────────┘
                       │
                       ↓ (start timer)
┌────────────────────────────────────────────────────────────────┐
│  Execution Tracking (actual time per subtask)                  │
│  Subtask 1: 1.5 hours (estimated: 1.2 hours)  📈 +25%        │
│  Subtask 2: 3.2 hours (estimated: 2.0 hours)  📈 +60%        │
│  Subtask 3: 0.8 hours (estimated: 0.8 hours)  ✅ Accurate    │
│  Total: 5.5 hours (estimated: 4.0 hours)      📈 +37%        │
└──────────────────────┬─────────────────────────────────────────┘
                       │
                       ↓ (calculate velocity)
┌────────────────────────────────────────────────────────────────┐
│  Velocity Calculation                                           │
│  Velocity = Story Points / Actual Hours                         │
│  Velocity = 10 points / 5.5 hours = 1.82 points/hour          │
│                                                                  │
│  Historical Average: 1.65 points/hour                          │
│  Improvement: +10.3% 📈                                        │
└──────────────────────┬─────────────────────────────────────────┘
                       │
                       ↓ (update model scores)
┌────────────────────────────────────────────────────────────────┐
│  Model Performance Scoring                                      │
│  Gemini 2.5 Flash:                                             │
│    - Avg Velocity: 1.92 points/hour                           │
│    - Accuracy: 94% (quality score)                             │
│    - Cost: $0.05/task                                          │
│    - Best for: High complexity tasks (7-10 points)            │
│                                                                  │
│  Llama 3.1 8B:                                                 │
│    - Avg Velocity: 1.58 points/hour                           │
│    - Accuracy: 89% (quality score)                             │
│    - Cost: $0.001/task                                         │
│    - Best for: Medium complexity tasks (3-6 points)           │
└────────────────────────────────────────────────────────────────┘
```

---

## Data Model

### 1. Task with Complexity Scoring

```python
class ModelTaskDecomposition(BaseModel):
    """Task with complexity estimation."""

    task_id: UUID
    task_description: str
    total_complexity: int           # Story points (1-10 scale)
    estimated_hours: float          # Initial guess (will improve over time)

    subtasks: List[SubTask]

    # Metadata
    task_type: str                  # "template_creation", "pipeline_integration", etc.
    domain: str                     # "event_bus", "intelligence", etc.
    created_at: datetime
    created_by: str                 # "claude-sonnet-4", "gemini-2.5-flash", etc.


class SubTask(BaseModel):
    """Individual subtask with complexity."""

    subtask_id: UUID
    description: str
    complexity: int                 # 1-3: Simple, 4-6: Medium, 7-10: Complex
    estimated_hours: float

    # Tracking
    started_at: Optional[datetime]
    completed_at: Optional[datetime]
    actual_hours: Optional[float]
    success: bool = False
    quality_score: Optional[float]  # 0.0-1.0 from validation
```

### 2. Velocity Tracking

```python
class ModelVelocityLog(BaseModel):
    """Velocity log for a completed task."""

    log_id: UUID
    task_id: UUID
    task_type: str
    domain: str

    # Complexity
    total_story_points: int
    subtask_count: int

    # Time tracking
    estimated_hours: float
    actual_hours: float
    estimation_error_pct: float     # (actual - estimated) / estimated * 100

    # Velocity
    velocity: float                 # story_points / actual_hours
    historical_avg_velocity: float
    velocity_improvement_pct: float

    # Model performance
    model_used: str                 # "gemini-2.5-flash", "llama-3.1-8b"
    model_velocity: float           # Velocity for this specific model
    model_accuracy: float           # Quality score avg across subtasks

    # Results
    success_rate: float             # % of subtasks completed successfully
    quality_avg: float              # Avg quality score across subtasks

    created_at: datetime
```

### 3. Model Performance Tracking

```python
class ModelPerformanceScore(BaseModel):
    """Aggregate performance metrics per model."""

    model_name: str
    task_type: str                  # "template_creation", "pipeline_integration", etc.

    # Velocity metrics
    avg_velocity: float             # Avg story points per hour
    velocity_stddev: float          # Consistency measure
    best_velocity: float
    worst_velocity: float

    # Accuracy metrics
    avg_quality_score: float        # 0.0-1.0
    success_rate_pct: float         # % tasks completed successfully

    # Cost metrics
    avg_cost_usd: float
    cost_per_story_point: float     # $$$ per unit of work

    # Complexity affinity
    best_complexity_range: str      # "simple", "medium", "complex"
    complexity_scores: Dict[str, float]  # {"simple": 0.95, "medium": 0.89, "complex": 0.72}

    # Sample size
    total_tasks: int
    total_hours: float
    last_updated: datetime
```

---

## Complexity Scoring System

### Fibonacci Scale (1-10)

**Simple Tasks (1-3 points)**:
- Update existing template (1 point)
- Add single method to class (2 points)
- Write unit test (2 points)
- Update documentation (1 point)

**Medium Tasks (4-6 points)**:
- Create new template file (4 points)
- Implement new pipeline stage (5 points)
- Write integration test (4 points)
- Refactor existing module (5 points)

**Complex Tasks (7-10 points)**:
- Design new architecture component (8 points)
- Implement multi-stage workflow (10 points)
- Full end-to-end feature (9 points)
- Performance optimization (7 points)

### Auto-Scoring with AI

```python
async def estimate_task_complexity(
    task_description: str,
    historical_tasks: List[ModelVelocityLog]
) -> int:
    """Use AI + historical data to estimate complexity."""

    # Find similar tasks
    similar_tasks = await vector_search(
        query=task_description,
        collection="completed_tasks",
        limit=5
    )

    # Extract features
    features = {
        "has_testing": "test" in task_description.lower(),
        "is_new_feature": "new" in task_description.lower(),
        "is_refactoring": "refactor" in task_description.lower(),
        "estimated_lines": estimate_loc_from_description(task_description),
        "similar_avg_complexity": np.mean([t.total_story_points for t in similar_tasks]),
    }

    # AI estimation with context
    prompt = f"""
    Estimate complexity (1-10 story points) for this task:
    {task_description}

    Context from similar completed tasks:
    {format_similar_tasks(similar_tasks)}

    Features:
    {json.dumps(features, indent=2)}

    Provide complexity score (1-10) and reasoning.
    """

    response = await llm.complete(prompt)

    return int(extract_complexity(response))
```

---

## Implementation

### Phase 1: Task Decomposition with Estimation (2 hours)

```python
class TaskDecompositionEngine:
    """Decomposes tasks and estimates complexity."""

    async def decompose_and_estimate(
        self,
        task_description: str
    ) -> ModelTaskDecomposition:
        """Break task into subtasks with complexity scores."""

        # Step 1: Decompose using AI
        subtasks_raw = await self._decompose_task(task_description)

        # Step 2: Estimate complexity per subtask
        subtasks = []
        for st in subtasks_raw:
            complexity = await self.estimate_complexity(st.description)
            estimated_hours = self._complexity_to_hours(complexity)

            subtasks.append(SubTask(
                subtask_id=uuid4(),
                description=st.description,
                complexity=complexity,
                estimated_hours=estimated_hours,
            ))

        # Step 3: Calculate totals
        total_complexity = sum(st.complexity for st in subtasks)
        total_hours = sum(st.estimated_hours for st in subtasks)

        return ModelTaskDecomposition(
            task_id=uuid4(),
            task_description=task_description,
            total_complexity=total_complexity,
            estimated_hours=total_hours,
            subtasks=subtasks,
            task_type=self._classify_task_type(task_description),
            domain=self._extract_domain(task_description),
            created_at=datetime.utcnow(),
            created_by="claude-sonnet-4",  # or whatever model is used
        )

    def _complexity_to_hours(self, complexity: int) -> float:
        """Convert story points to estimated hours."""
        # Use historical velocity to convert points to hours
        avg_velocity = self.get_avg_velocity()  # e.g., 1.65 points/hour

        return complexity / avg_velocity
```

### Phase 2: Execution Tracking (1 hour)

```python
class ExecutionTracker:
    """Tracks actual time spent on subtasks."""

    def __init__(self, task: ModelTaskDecomposition):
        self.task = task
        self.current_subtask: Optional[SubTask] = None
        self.start_time: Optional[datetime] = None

    def start_subtask(self, subtask_id: UUID):
        """Start timer for subtask."""
        subtask = self._find_subtask(subtask_id)
        subtask.started_at = datetime.utcnow()
        self.current_subtask = subtask
        self.start_time = datetime.utcnow()

        logger.info(
            f"Started subtask: {subtask.description} "
            f"(complexity: {subtask.complexity}, "
            f"estimated: {subtask.estimated_hours:.1f}h)"
        )

    def complete_subtask(
        self,
        subtask_id: UUID,
        success: bool = True,
        quality_score: Optional[float] = None
    ):
        """Complete subtask and record actual time."""
        subtask = self._find_subtask(subtask_id)
        subtask.completed_at = datetime.utcnow()
        subtask.success = success
        subtask.quality_score = quality_score

        # Calculate actual time
        if subtask.started_at:
            duration = subtask.completed_at - subtask.started_at
            subtask.actual_hours = duration.total_seconds() / 3600

            # Log estimation accuracy
            if subtask.estimated_hours:
                error_pct = (
                    (subtask.actual_hours - subtask.estimated_hours)
                    / subtask.estimated_hours * 100
                )

                logger.info(
                    f"Completed subtask: {subtask.description}\n"
                    f"  Estimated: {subtask.estimated_hours:.1f}h\n"
                    f"  Actual: {subtask.actual_hours:.1f}h\n"
                    f"  Error: {error_pct:+.1f}%\n"
                    f"  Quality: {quality_score:.2f}" if quality_score else ""
                )

    async def generate_velocity_log(self) -> ModelVelocityLog:
        """Generate velocity log after task completion."""
        total_actual_hours = sum(
            st.actual_hours for st in self.task.subtasks
            if st.actual_hours
        )

        velocity = self.task.total_complexity / total_actual_hours

        # Get historical average
        historical_velocity = await self._get_historical_velocity(
            task_type=self.task.task_type
        )

        velocity_improvement = (
            (velocity - historical_velocity) / historical_velocity * 100
        )

        return ModelVelocityLog(
            log_id=uuid4(),
            task_id=self.task.task_id,
            task_type=self.task.task_type,
            domain=self.task.domain,
            total_story_points=self.task.total_complexity,
            subtask_count=len(self.task.subtasks),
            estimated_hours=self.task.estimated_hours,
            actual_hours=total_actual_hours,
            estimation_error_pct=(
                (total_actual_hours - self.task.estimated_hours)
                / self.task.estimated_hours * 100
            ),
            velocity=velocity,
            historical_avg_velocity=historical_velocity,
            velocity_improvement_pct=velocity_improvement,
            model_used=self.task.created_by,
            success_rate=self._calculate_success_rate(),
            quality_avg=self._calculate_quality_avg(),
            created_at=datetime.utcnow(),
        )
```

### Phase 3: Model Performance Scoring (1 hour)

```python
class ModelPerformanceAnalyzer:
    """Analyzes model performance across tasks."""

    async def update_model_scores(
        self,
        velocity_log: ModelVelocityLog
    ):
        """Update aggregate model performance scores."""

        model_name = velocity_log.model_used
        task_type = velocity_log.task_type

        # Get existing score or create new
        score = await self._get_or_create_score(model_name, task_type)

        # Update velocity metrics
        score.avg_velocity = self._update_average(
            score.avg_velocity,
            velocity_log.velocity,
            score.total_tasks
        )

        # Update accuracy metrics
        score.avg_quality_score = self._update_average(
            score.avg_quality_score,
            velocity_log.quality_avg,
            score.total_tasks
        )

        score.success_rate_pct = self._update_average(
            score.success_rate_pct,
            velocity_log.success_rate,
            score.total_tasks
        )

        # Update cost metrics
        score.cost_per_story_point = (
            velocity_log.model_cost / velocity_log.total_story_points
        )

        # Update complexity affinity
        complexity_category = self._categorize_complexity(
            velocity_log.total_story_points
        )
        score.complexity_scores[complexity_category] = velocity_log.quality_avg

        score.total_tasks += 1
        score.total_hours += velocity_log.actual_hours
        score.last_updated = datetime.utcnow()

        await self._save_score(score)

    async def recommend_model_for_task(
        self,
        task: ModelTaskDecomposition
    ) -> str:
        """Recommend best model for task based on historical performance."""

        # Get all model scores for this task type
        scores = await self._get_scores_by_task_type(task.task_type)

        # Filter by complexity affinity
        complexity_category = self._categorize_complexity(task.total_complexity)

        # Score each model
        model_scores = {}
        for model_name, score in scores.items():
            # Weighted scoring
            quality_weight = 0.4
            velocity_weight = 0.3
            cost_weight = 0.3

            quality_score = score.complexity_scores.get(
                complexity_category, score.avg_quality_score
            )

            normalized_velocity = score.avg_velocity / 2.0  # Normalize to 0-1
            normalized_cost = 1.0 - (score.cost_per_story_point / 0.10)  # Lower cost = higher score

            total_score = (
                quality_weight * quality_score +
                velocity_weight * normalized_velocity +
                cost_weight * normalized_cost
            )

            model_scores[model_name] = total_score

        # Return best model
        best_model = max(model_scores, key=model_scores.get)

        logger.info(
            f"Recommended model for {task.task_description}:\n"
            f"  Model: {best_model}\n"
            f"  Expected velocity: {scores[best_model].avg_velocity:.2f} pts/hr\n"
            f"  Expected quality: {scores[best_model].avg_quality_score:.2f}\n"
            f"  Expected cost: ${scores[best_model].cost_per_story_point:.3f}/pt"
        )

        return best_model
```

---

## Integration with Generation Pipeline

### Add to CLI

```python
# cli/generate_node.py

parser.add_argument(
    "--estimate-only",
    action="store_true",
    help="Only estimate complexity and time, don't generate",
)

parser.add_argument(
    "--track-velocity",
    action="store_true",
    help="Track velocity for this generation (default: true)",
)

# In main()
if args.estimate_only:
    # Decompose task and estimate
    decomposition = await task_engine.decompose_and_estimate(prompt)

    print(f"\nTask Estimation:")
    print(f"  Total Complexity: {decomposition.total_complexity} story points")
    print(f"  Estimated Time: {decomposition.estimated_hours:.1f} hours")
    print(f"\nSubtasks:")
    for st in decomposition.subtasks:
        print(f"  - [{st.complexity}pts] {st.description} ({st.estimated_hours:.1f}h)")

    # Recommend model
    recommended_model = await perf_analyzer.recommend_model_for_task(decomposition)
    print(f"\nRecommended Model: {recommended_model}")

    return

# Track velocity during generation
if args.track_velocity:
    tracker = ExecutionTracker(decomposition)
    # Start/stop tracking for each stage
    tracker.start_subtask(stage_subtask_id)
    # ... execute stage ...
    tracker.complete_subtask(stage_subtask_id, success=True, quality=0.95)

    # Generate velocity log at end
    velocity_log = await tracker.generate_velocity_log()
    await perf_analyzer.update_model_scores(velocity_log)

    print(f"\n📊 Velocity Report:")
    print(f"  Velocity: {velocity_log.velocity:.2f} pts/hr")
    print(f"  Estimation Error: {velocity_log.estimation_error_pct:+.1f}%")
    print(f"  Quality: {velocity_log.quality_avg:.2f}")
```

### Velocity Metrics CLI

```python
# cli/show_velocity.py

"""Show velocity metrics and model performance."""

import asyncio
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent))

from agents.lib.model_performance_analyzer import ModelPerformanceAnalyzer

async def main():
    analyzer = ModelPerformanceAnalyzer()

    # Show overall velocity trend
    print("\n📈 Velocity Trend (Last 30 Days)")
    print("=" * 60)

    velocity_trend = await analyzer.get_velocity_trend(days=30)
    for date, velocity in velocity_trend:
        print(f"  {date}: {velocity:.2f} pts/hr")

    # Show model performance comparison
    print("\n🤖 Model Performance Comparison")
    print("=" * 60)

    scores = await analyzer.get_all_model_scores()
    for model, score in sorted(scores.items(), key=lambda x: x[1].avg_velocity, reverse=True):
        print(f"\n{model}:")
        print(f"  Velocity: {score.avg_velocity:.2f} pts/hr")
        print(f"  Quality: {score.avg_quality_score:.2f}")
        print(f"  Cost/pt: ${score.cost_per_story_point:.3f}")
        print(f"  Best for: {score.best_complexity_range} tasks")
        print(f"  Sample: {score.total_tasks} tasks, {score.total_hours:.1f}h")

    # Show estimation accuracy trend
    print("\n🎯 Estimation Accuracy (Last 20 Tasks)")
    print("=" * 60)

    recent_logs = await analyzer.get_recent_velocity_logs(limit=20)
    avg_error = np.mean([log.estimation_error_pct for log in recent_logs])

    print(f"  Average Error: {avg_error:+.1f}%")
    print(f"  Improving: {'Yes ✅' if avg_error < 20 else 'No ❌'}")

if __name__ == "__main__":
    asyncio.run(main())
```

---

## Example Usage

### Estimate Before Starting

```bash
$ poetry run python cli/generate_node.py --estimate-only \
    "Implement Stage 4.5: Event Bus Integration"

Task Estimation:
  Total Complexity: 10 story points
  Estimated Time: 6.1 hours

Subtasks:
  - [3pts] Create event bus template snippets (1.8h)
  - [5pts] Update Effect node template with EventPublisher (3.0h)
  - [2pts] Write tests for Stage 4.5 (1.2h)

Recommended Model: gemini-2.5-flash
  Expected velocity: 1.92 pts/hr
  Expected quality: 0.94
  Expected cost: $0.026/pt
```

### Generate with Velocity Tracking

```bash
$ poetry run python cli/generate_node.py \
    --track-velocity \
    "Create EFFECT node for PostgreSQL database write operations"

🚀 Generating node from prompt...
📝 Prompt: Create EFFECT node for PostgreSQL database write operations
📁 Output: ./output

[Stage 1] PRD Analysis (started)
  Estimated: 0.8h, Complexity: 2pts
[Stage 1] PRD Analysis (completed) ✅
  Actual: 0.6h (-25% vs estimate)
  Quality: 0.96

[Stage 1.5] Intelligence Gathering (started)
  Estimated: 1.2h, Complexity: 3pts
...

📊 Velocity Report:
  Velocity: 2.15 pts/hr (+12% vs historical avg)
  Estimation Error: +18% (need better estimates!)
  Quality: 0.95
  Model: gemini-2.5-flash
```

### Check Velocity Metrics

```bash
$ poetry run python cli/show_velocity.py

📈 Velocity Trend (Last 30 Days)
============================================================
  2025-01-15: 1.52 pts/hr
  2025-01-18: 1.68 pts/hr  ⬆️ (+10%)
  2025-01-22: 1.92 pts/hr  ⬆️ (+14%)

🤖 Model Performance Comparison
============================================================

gemini-2.5-flash:
  Velocity: 1.92 pts/hr
  Quality: 0.94
  Cost/pt: $0.026
  Best for: complex tasks
  Sample: 45 tasks, 234h

llama-3.1-8b:
  Velocity: 1.58 pts/hr
  Quality: 0.89
  Cost/pt: $0.0005
  Best for: medium tasks
  Sample: 23 tasks, 145h

🎯 Estimation Accuracy (Last 20 Tasks)
============================================================
  Average Error: +23% (need to improve estimates!)
  Improving: No ❌ (but will improve with more data)
```

---

## Benefits

1. **Better Estimates Over Time**: Learn from actual performance
2. **Model Selection**: Choose best model for task type and complexity
3. **Velocity Tracking**: Measure improvement over time
4. **Cost Optimization**: Know $/story point for each model
5. **Realistic Planning**: Stop terrible estimates! Use empirical data

---

## Implementation Timeline

**Day 1 (4 hours)**: Task decomposition engine + complexity scoring
**Day 2 (4 hours)**: Execution tracking + velocity calculation
**Day 3 (4 hours)**: Model performance scoring + CLI tools
**Total**: 12 hours to full velocity tracking system

**Fast Follow** to MVP (Week 1.5): Add after event bus integration is working

---

**Status**: Design Complete - Ready for Implementation
**Next Action**: Review design, then implement Day 1 (task decomposition)
