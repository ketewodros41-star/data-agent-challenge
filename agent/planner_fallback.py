"""
PlannerFallback - Handles fallback execution with safe environment management.

Provides safe_execute_python_env with proper missing key handling
and loop detection integration.
"""

import json
import logging
from typing import Any, Dict, List, Optional

from agent.loop_detector import LoopDetector

# Set up logging
logger = logging.getLogger(__name__)


class PlannerFallback:
    """
    Fallback planner with safe environment management and loop detection.
    """
    
    def __init__(self, window_size: int = 10, max_repeats: int = 3):
        """
        Initialize PlannerFallback.
        
        Args:
            window_size: Window size for loop detection
            max_repeats: Maximum allowed repetitions
        """
        self.loop_detector = LoopDetector(window_size, max_repeats)
    
    def validate_env_references(self, code: str, env: Dict[str, Any]) -> List[str]:
        """
        Validate that all environment references in code exist in env.
        
        Args:
            code: Python code to check
            env: Environment dictionary
            
        Returns:
            List of missing environment keys
        """
        missing = []
        
        # Simple pattern to find env['key'] or env["key"] references
        import re
        pattern = r"env\[(?:['\"]([^'\"]+)['\"]|[\"']([^'\"]+)[\"']\)"
        matches = re.findall(pattern, code)
        
        for match in matches:
            key = match[0] if match[0] else match[1]
            if key not in env:
                missing.append(key)
        
        return missing
    
    def safe_execute_python_env(self, code: str, env: Dict[str, Any]) -> Dict[str, Any]:
        """
        Safely execute Python code with environment, handling missing keys.
        
        Args:
            code: Python code to execute
            env: Environment dictionary
            
        Returns:
            Updated environment dictionary
        """
        missing = self.validate_env_references(code, env)
        
        if missing:
            logger.warning(
                f"execute_python references missing env keys: {missing}. "
                f"Filling with empty list to prevent KeyError."
            )
            
            # 🔥 THIS IS THE CRITICAL FIX - actually mutate the env
            for key in missing:
                env[key] = []  # Fill missing keys with empty list
        
        return env
    
    def record_tool_call(self, tool_name: str, params: Any) -> None:
        """
        Record a tool call for loop detection.
        
        Args:
            tool_name: Name of the tool called
            params: Parameters passed to the tool
        """
        self.loop_detector.record_tool_call(tool_name, params)
    
    def is_looping(self) -> bool:
        """
        Check if the agent is currently in a loop.
        
        Returns:
            True if loop detected, False otherwise
        """
        return self.loop_detector.is_looping()
    
    def get_loop_summary(self) -> Dict[str, Any]:
        """
        Get summary of loop detection analysis.
        
        Returns:
            Dictionary with loop analysis details
        """
        return self.loop_detector.get_loop_summary()
    
    def reset_loop_detection(self) -> None:
        """Reset the loop detector."""
        self.loop_detector.reset()
