"""
Logging Configuration for Debug Pipeline

Implements verbose/silent mode toggle to achieve >80% token reduction
in silent mode while maintaining essential debugging information.
"""

import sys
from enum import Enum
from typing import Optional


class LogLevel(Enum):
    """Logging levels for the debug pipeline."""
    SILENT = "silent"      # Minimal output, essential errors only
    QUIET = "quiet"        # Reduced output, key milestones only  
    NORMAL = "normal"      # Standard output with progress info
    VERBOSE = "verbose"    # Full output with detailed debugging


class DebugLogger:
    """Centralized logging for the debug pipeline with silent mode support."""
    
    def __init__(self, level: LogLevel = LogLevel.NORMAL):
        self.level = level
        self._token_savings = 0
        self._verbose_tokens = 0
        self._silent_tokens = 0
    
    def set_level(self, level: LogLevel):
        """Set the logging level."""
        self.level = level
    
    def is_silent(self) -> bool:
        """Check if currently in silent mode."""
        return self.level == LogLevel.SILENT
    
    def is_quiet(self) -> bool:
        """Check if currently in quiet mode."""
        return self.level in [LogLevel.SILENT, LogLevel.QUIET]
    
    def is_verbose(self) -> bool:
        """Check if currently in verbose mode."""
        return self.level == LogLevel.VERBOSE
    
    def log_phase_start(self, phase_name: str, details: Optional[str] = None):
        """Log phase start with appropriate verbosity."""
        if self.is_silent():
            return
        
        if self.is_quiet():
            print(f"[{phase_name}] Starting...", file=sys.stderr)
        else:
            print(f"\n{'='*80}", file=sys.stderr)
            print(f"[DispatchRunner] {phase_name}", file=sys.stderr)
            if details:
                print(f"[DispatchRunner] {details}", file=sys.stderr)
            print(f"{'='*80}\n", file=sys.stderr)
    
    def log_phase_complete(self, phase_name: str, duration_ms: float, success: bool = True, details: Optional[str] = None):
        """Log phase completion with appropriate verbosity."""
        if self.is_silent():
            return
        
        if self.is_quiet():
            status = "✓" if success else "✗"
            print(f"[{phase_name}] {status} {duration_ms:.0f}ms", file=sys.stderr)
        else:
            status = "✓" if success else "✗"
            print(f"[DispatchRunner] {status} {phase_name} completed in {duration_ms:.0f}ms", file=sys.stderr)
            if details:
                print(f"[DispatchRunner] {details}", file=sys.stderr)
            print("", file=sys.stderr)
    
    def log_progress(self, message: str, details: Optional[str] = None):
        """Log progress messages with appropriate verbosity."""
        if self.is_silent():
            return
        
        if self.is_quiet():
            print(f"[Progress] {message}", file=sys.stderr)
        else:
            print(f"[DispatchRunner] {message}", file=sys.stderr)
            if details and self.is_verbose():
                print(f"[DispatchRunner] {details}", file=sys.stderr)
    
    def log_error(self, message: str, details: Optional[str] = None):
        """Log error messages (always shown)."""
        print(f"[DispatchRunner] ✗ {message}", file=sys.stderr)
        if details and self.is_verbose():
            print(f"[DispatchRunner] {details}", file=sys.stderr)
    
    def log_warning(self, message: str, details: Optional[str] = None):
        """Log warning messages."""
        if self.is_silent():
            return
        
        print(f"[DispatchRunner] ⚠ {message}", file=sys.stderr)
        if details and self.is_verbose():
            print(f"[DispatchRunner] {details}", file=sys.stderr)
    
    def log_info(self, message: str, details: Optional[str] = None):
        """Log informational messages."""
        if self.is_quiet():
            return
        
        print(f"[DispatchRunner] {message}", file=sys.stderr)
        if details and self.is_verbose():
            print(f"[DispatchRunner] {details}", file=sys.stderr)
    
    def log_debug(self, message: str, details: Optional[str] = None):
        """Log debug messages (only in verbose mode)."""
        if not self.is_verbose():
            return
        
        print(f"[DispatchRunner] [DEBUG] {message}", file=sys.stderr)
        if details:
            print(f"[DispatchRunner] [DEBUG] {details}", file=sys.stderr)
    
    def log_startup_banner(self, user_prompt: str, correlation_id: str, workspace_path: str, 
                          enable_context: bool, enable_quorum: bool, enable_interactive: bool, 
                          enable_architect: bool, phase_config: dict):
        """Log startup banner with appropriate verbosity."""
        if self.is_silent():
            return
        
        if self.is_quiet():
            print(f"[Workflow] {user_prompt[:60]}...", file=sys.stderr)
            print(f"[Config] Context:{enable_context} Quorum:{enable_quorum} Interactive:{enable_interactive}", file=sys.stderr)
        else:
            print("\n" + "="*80, file=sys.stderr)
            print("AUTOMATED WORKFLOW INITIATED", file=sys.stderr)
            print("="*80, file=sys.stderr)
            print(f"\nUser Request: {user_prompt[:120]}{'...' if len(user_prompt) > 120 else ''}", file=sys.stderr)
            print(f"Correlation ID: {correlation_id}", file=sys.stderr)
            print(f"Workspace: {workspace_path}", file=sys.stderr)
            print(f"\nWorkflow Configuration:", file=sys.stderr)
            print(f"  - Context Gathering: {'ENABLED' if enable_context else 'DISABLED'}", file=sys.stderr)
            print(f"  - Quorum Validation: {'ENABLED' if enable_quorum else 'DISABLED'}", file=sys.stderr)
            print(f"  - Interactive Mode: {'ENABLED' if enable_interactive else 'DISABLED'}", file=sys.stderr)
            print(f"  - Task Architect: {'ENABLED' if enable_architect else 'DISABLED'}", file=sys.stderr)
            
            if phase_config.get('only_phase') is not None:
                print(f"  - Execution Mode: SINGLE PHASE ({phase_config['only_phase']})", file=sys.stderr)
            elif phase_config.get('stop_after_phase') is not None:
                print(f"  - Execution Mode: STOP AFTER PHASE {phase_config['stop_after_phase']}", file=sys.stderr)
            else:
                print(f"  - Execution Mode: FULL PIPELINE", file=sys.stderr)
            
            print("\n" + "="*80, file=sys.stderr)
            print("BEGINNING EXECUTION", file=sys.stderr)
            print("="*80 + "\n", file=sys.stderr)
            sys.stdout.flush()
    
    def log_quorum_decision(self, decision: str, confidence: float, deficiencies: list):
        """Log quorum decision with appropriate verbosity."""
        if self.is_silent():
            return
        
        if self.is_quiet():
            print(f"[Quorum] {decision} ({confidence:.1%})", file=sys.stderr)
        else:
            print(f"[DispatchRunner] Quorum decision: {decision} (confidence: {confidence:.1%})", file=sys.stderr)
            if deficiencies and not self.is_quiet():
                print(f"[DispatchRunner] Deficiencies found: {len(deficiencies)}", file=sys.stderr)
                for deficiency in deficiencies:
                    print(f"[DispatchRunner]   - {deficiency}", file=sys.stderr)
    
    def log_task_breakdown(self, num_subtasks: int, execution_order: str, reasoning: str):
        """Log task breakdown with appropriate verbosity."""
        if self.is_silent():
            return
        
        if self.is_quiet():
            print(f"[Architect] {num_subtasks} subtasks", file=sys.stderr)
        else:
            print(f"[DispatchRunner] ✓ Breakdown complete: {num_subtasks} subtasks ({execution_order})", file=sys.stderr)
            if self.is_verbose():
                print(f"[DispatchRunner] Reasoning: {reasoning[:150]}...", file=sys.stderr)
    
    def log_execution_summary(self, successful: int, failed: int, total: int):
        """Log execution summary with appropriate verbosity."""
        if self.is_silent():
            return
        
        if self.is_quiet():
            print(f"[Execution] {successful}/{total} succeeded", file=sys.stderr)
        else:
            print(f"[DispatchRunner] ✓ Phase 4 completed ({successful} succeeded, {failed} failed)", file=sys.stderr)
    
    def estimate_token_savings(self, verbose_tokens: int, silent_tokens: int):
        """Estimate token savings from silent mode."""
        if verbose_tokens > 0:
            savings_percent = ((verbose_tokens - silent_tokens) / verbose_tokens) * 100
            return max(0, savings_percent)
        return 0
    
    def get_token_savings_report(self) -> dict:
        """Get token savings report for analytics."""
        return {
            "verbose_tokens": self._verbose_tokens,
            "silent_tokens": self._silent_tokens,
            "savings_percent": self.estimate_token_savings(self._verbose_tokens, self._silent_tokens),
            "mode": self.level.value
        }


# Global logger instance
debug_logger = DebugLogger()


def set_log_level(level: LogLevel):
    """Set the global log level."""
    debug_logger.set_level(level)


def get_logger() -> DebugLogger:
    """Get the global logger instance."""
    return debug_logger
