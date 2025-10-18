"""
Decision Logger for AI Quality Enforcement System

Logs all enforcement decisions to JSONL format for analytics and learning.
Tracks violations, corrections, scores, actions, and user responses.
"""

import json
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional, Any


class DecisionLogger:
    """Log all enforcement decisions for analysis and improvement.

    Captures complete enforcement lifecycle:
    - Violations detected
    - Corrections proposed
    - Scores assigned
    - Actions taken
    - User responses (if available)

    Output format: JSON Lines (JSONL) for efficient streaming and analysis.
    """

    def __init__(self, log_dir: Path):
        """Initialize decision logger.

        Args:
            log_dir: Directory for storing decision logs
        """
        self.log_dir = Path(log_dir).expanduser()
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.decisions_file = self.log_dir / "decisions.jsonl"

    def log_decision(
        self,
        violation: Dict[str, Any],
        correction: Dict[str, Any],
        score: Dict[str, Any],
        action: str,
        user_response: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ):
        """Log a single enforcement decision.

        Args:
            violation: Violation details
                - type: str - Violation category (e.g., 'naming_convention')
                - name: str - Name that violated the rule
                - line: int - Line number
                - severity: str - 'error' or 'warning'
                - rule: str - Rule identifier
                - file_path: str - File where violation occurred

            correction: Correction details
                - old_name: str - Original name
                - new_name: str - Suggested name
                - explanation: str - Why this correction was suggested
                - confidence: float - Confidence in correction (0-1)

            score: Scoring details
                - consensus_score: float - Overall consensus (0-1)
                - confidence: float - Confidence level (0-1)
                - individual_scores: Dict[str, float] - Scores per model

            action: Action taken
                - 'auto_applied': Correction applied automatically
                - 'suggested': Correction suggested to user
                - 'skipped': No action taken (below threshold)

            user_response: Optional user response
                - 'accepted': User accepted the suggestion
                - 'rejected': User rejected the suggestion
                - 'modified': User modified the suggestion

            metadata: Optional additional context
                - duration_ms: Time taken for enforcement
                - cache_hit: Whether result was cached
                - models_used: List of models that participated
        """
        entry = {
            "timestamp": datetime.utcnow().isoformat(),
            "violation": {
                "type": violation.get("type"),
                "name": violation.get("name"),
                "line": violation.get("line"),
                "severity": violation.get("severity"),
                "rule": violation.get("rule"),
                "file_path": violation.get("file_path"),
            },
            "correction": {
                "old_name": correction.get("old_name"),
                "new_name": correction.get("new_name"),
                "explanation": correction.get("explanation"),
                "confidence": correction.get("confidence"),
            },
            "score": {
                "consensus": score.get("consensus_score"),
                "confidence": score.get("confidence"),
                "individual_scores": score.get("individual_scores", {}),
            },
            "action": action,
            "user_response": user_response,
            "metadata": metadata or {},
        }

        # Append to JSONL file (one JSON object per line)
        with open(self.decisions_file, "a") as f:
            f.write(json.dumps(entry) + "\n")

    def log_batch_decisions(self, decisions: list[Dict[str, Any]]):
        """Log multiple decisions in batch.

        Args:
            decisions: List of decision dictionaries with same structure as log_decision args
        """
        with open(self.decisions_file, "a") as f:
            for decision in decisions:
                entry = {"timestamp": datetime.utcnow().isoformat(), **decision}
                f.write(json.dumps(entry) + "\n")

    def get_recent_decisions(self, count: int = 100) -> list[Dict[str, Any]]:
        """Retrieve recent decisions for analysis.

        Args:
            count: Number of recent decisions to retrieve

        Returns:
            List of decision dictionaries in reverse chronological order
        """
        if not self.decisions_file.exists():
            return []

        decisions = []
        with open(self.decisions_file, "r") as f:
            for line in f:
                try:
                    decisions.append(json.loads(line))
                except json.JSONDecodeError:
                    continue  # Skip malformed lines

        # Return most recent entries
        return decisions[-count:] if len(decisions) > count else decisions

    def get_statistics(self) -> Dict[str, Any]:
        """Generate basic statistics from decision log.

        Returns:
            Dictionary with statistics:
            - total_decisions: int
            - actions: Dict[str, int] - Count by action type
            - avg_consensus_score: float
            - user_acceptance_rate: float (if user responses available)
        """
        if not self.decisions_file.exists():
            return {
                "total_decisions": 0,
                "actions": {},
                "avg_consensus_score": 0.0,
                "user_acceptance_rate": 0.0,
            }

        total = 0
        actions = {}
        consensus_scores = []
        user_responses = {"accepted": 0, "rejected": 0, "modified": 0}
        total_responses = 0

        with open(self.decisions_file, "r") as f:
            for line in f:
                try:
                    entry = json.loads(line)
                    total += 1

                    # Count actions
                    action = entry.get("action", "unknown")
                    actions[action] = actions.get(action, 0) + 1

                    # Collect consensus scores
                    score = entry.get("score", {}).get("consensus")
                    if score is not None:
                        consensus_scores.append(score)

                    # Count user responses
                    response = entry.get("user_response")
                    if response in user_responses:
                        user_responses[response] += 1
                        total_responses += 1

                except json.JSONDecodeError:
                    continue

        avg_consensus = sum(consensus_scores) / len(consensus_scores) if consensus_scores else 0.0

        acceptance_rate = user_responses["accepted"] / total_responses if total_responses > 0 else 0.0

        return {
            "total_decisions": total,
            "actions": actions,
            "avg_consensus_score": avg_consensus,
            "user_acceptance_rate": acceptance_rate,
            "user_responses": user_responses,
        }


# Example usage
if __name__ == "__main__":
    # Test the logger
    logger = DecisionLogger(Path("~/.claude/hooks/logs"))

    # Log a sample decision
    logger.log_decision(
        violation={
            "type": "naming_convention",
            "name": "myVar",
            "line": 42,
            "severity": "warning",
            "rule": "snake_case_required",
            "file_path": "src/example.py",
        },
        correction={
            "old_name": "myVar",
            "new_name": "my_var",
            "explanation": "Python convention uses snake_case for variables",
            "confidence": 0.95,
        },
        score={
            "consensus_score": 0.87,
            "confidence": 0.92,
            "individual_scores": {"flash": 0.85, "codestral": 0.89},
        },
        action="auto_applied",
        user_response="accepted",
        metadata={
            "duration_ms": 450,
            "cache_hit": False,
            "models_used": ["flash", "codestral"],
        },
    )

    # Print statistics
    stats = logger.get_statistics()
    print(f"Total decisions: {stats['total_decisions']}")
    print(f"Average consensus: {stats['avg_consensus_score']:.2f}")
    print(f"Acceptance rate: {stats['user_acceptance_rate']:.2%}")
