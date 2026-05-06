"""
LoopDetector - Detects repetitive tool calls with normalized parameter comparison.

Detects loops by comparing normalized tool calls and parameters,
not just exact string matches.
"""

import json
import re
from typing import Any, Dict, List, Tuple


def normalize_params(params: Any) -> str:
    """
    Normalize parameters for loop detection comparison.
    
    Handles:
    - JSON serialization with sorted keys
    - Regex pattern variations
    - Geographic name normalization
    - Number normalization
    """
    try:
        s = json.dumps(params, sort_keys=True)
    except Exception:
        s = str(params)

    # Remove regex variations
    s = re.sub(r'\.\*', '', s)  # Remove .* patterns
    s = re.sub(r'\bi\b', '', s)  # Remove case flags
    s = re.sub(r'Indiana\w*', 'Indiana', s)  # Normalize Indiana variations
    s = re.sub(r'limit\s*\d+', 'limit N', s)  # Normalize limits
    s = re.sub(r'\d+', 'N', s)  # Normalize all numbers

    return s.lower().strip()


class LoopDetector:
    """
    Detects when the agent is stuck in a loop by analyzing tool call history.
    
    Uses normalized parameter comparison to catch semantic loops, not just exact matches.
    """
    
    def __init__(self, window_size: int = 10, max_repeats: int = 3):
        """
        Initialize LoopDetector.
        
        Args:
            window_size: How many recent calls to analyze
            max_repeats: Maximum allowed repetitions of normalized calls
        """
        self.window_size = window_size
        self.max_repeats = max_repeats
        self.history: List[Tuple[str, str]] = []  # (tool_name, normalized_params)
    
    def record_tool_call(self, tool_name: str, params: Any) -> None:
        """
        Record a tool call for loop detection.
        
        Args:
            tool_name: Name of the tool called
            params: Parameters passed to the tool
        """
        normalized = normalize_params(params)
        self.history.append((tool_name, normalized))
    
    def is_looping(self) -> bool:
        """
        Check if the agent is in a loop.
        
        Returns:
            True if loop detected, False otherwise
        """
        if len(self.history) < self.window_size:
            return False
        
        recent = self.history[-self.window_size:]
        counts: Dict[Tuple[str, str], int] = {}
        
        for tool, norm in recent:
            key = (tool, norm)
            counts[key] = counts.get(key, 0) + 1
        
        return any(count >= self.max_repeats for count in counts.values())
    
    def get_loop_summary(self) -> Dict[str, Any]:
        """
        Get summary of detected loops for debugging.
        
        Returns:
            Dictionary with loop analysis details
        """
        if len(self.history) < self.window_size:
            return {"status": "insufficient_data", "window_size": self.window_size}
        
        recent = self.history[-self.window_size:]
        counts: Dict[Tuple[str, str], int] = {}
        
        for tool, norm in recent:
            key = (tool, norm)
            counts[key] = counts.get(key, 0) + 1
        
        loops = {str(key): count for key, count in counts.items() if count >= self.max_repeats}
        
        return {
            "status": "analyzed",
            "window_size": self.window_size,
            "max_repeats": self.max_repeats,
            "total_calls": len(self.history),
            "recent_calls": len(recent),
            "loops_detected": loops,
            "is_looping": len(loops) > 0
        }
    
    def reset(self) -> None:
        """Reset the detector history."""
        self.history.clear()
