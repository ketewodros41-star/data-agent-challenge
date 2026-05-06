"""
Tests for PlannerFallback and LoopDetector functionality.
"""

import pytest
from agent.planner_fallback import PlannerFallback, LoopDetector
from agent.loop_detector import normalize_params


class TestLoopDetector:
    """Test the LoopDetector class."""
    
    def test_normalize_params_basic(self):
        """Test basic parameter normalization."""
        # Test JSON normalization
        params1 = {"limit": 50, "state": "Indiana"}
        params2 = {"limit": 100, "state": "Indiana.*"}
        
        norm1 = normalize_params(params1)
        norm2 = normalize_params(params2)
        
        # Both should normalize to the same pattern
        assert "limit n" in norm1
        assert "limit n" in norm2
        assert "indiana" in norm1.lower()
        assert "indiana" in norm2.lower()
    
    def test_normalize_params_variations(self):
        """Test various parameter format variations."""
        test_cases = [
            ({"query": "SELECT * FROM table WHERE state = 'Indiana'"}, "select.*from.*table.*where.*state.*=.*indiana"),
            ({"sql": "SELECT * FROM table LIMIT 100"}, "select.*from.*table.*limit n"),
            ({"filter": {"state": "Indiana"}}, "filter.*state.*indiana"),
        ]
        
        for params, expected_pattern in test_cases:
            normalized = normalize_params(params)
            assert expected_pattern in normalized.lower()
    
    def test_loop_detector_basic(self):
        """Test basic loop detection."""
        detector = LoopDetector(window_size=5, max_repeats=2)
        
        # Record some calls
        detector.record_tool_call("query_db", {"limit": 50})
        detector.record_tool_call("query_db", {"limit": 100})
        detector.record_tool_call("query_db", {"limit": 25})
        
        # Should not detect loop yet
        assert not detector.is_looping()
        
        # Add more similar calls
        detector.record_tool_call("query_db", {"limit": 75})
        detector.record_tool_call("query_db", {"limit": 200})
        
        # Should detect loop now (query_db with limit N repeated > 2 times)
        assert detector.is_looping()
    
    def test_loop_detector_normalized(self):
        """Test loop detection with normalized parameters."""
        detector = LoopDetector(window_size=5, max_repeats=2)
        
        # Record calls with different but semantically similar parameters
        detector.record_tool_call("query_db", {"state": "Indiana"})
        detector.record_tool_call("query_db", {"state": "Indiana.*"})
        detector.record_tool_call("query_db", {"state": "Indianapolis"})
        
        # Should detect loop due to normalization
        assert detector.is_looping()
        
        summary = detector.get_loop_summary()
        assert summary["is_looping"] is True
        assert len(summary["loops_detected"]) > 0


class TestPlannerFallback:
    """Test the PlannerFallback class."""
    
    def test_validate_env_references(self):
        """Test environment reference validation."""
        fallback = PlannerFallback()
        
        code = """
        import pandas as pd
        df1 = pd.DataFrame(env['data_1'])
        df2 = pd.DataFrame(env["data_2"])
        result = df1.merge(df2)
        """
        
        env = {"data_1": [{"id": 1}]}
        missing = fallback.validate_env_references(code, env)
        
        assert "data_2" in missing
        assert "data_1" not in missing
    
    def test_safe_execute_python_env_missing_keys(self):
        """Test safe execution with missing environment keys."""
        fallback = PlannerFallback()
        
        code = """
        import pandas as pd
        df1 = pd.DataFrame(env['data_1'])
        df2 = pd.DataFrame(env["data_2"])
        """
        
        env = {"data_1": [{"id": 1}]}
        
        # This should add missing key to env
        result_env = fallback.safe_execute_python_env(code, env)
        
        assert "data_2" in result_env
        assert result_env["data_2"] == []  # Should be filled with empty list
        assert result_env["data_1"] == [{"id": 1}]  # Original should remain
    
    def test_loop_integration(self):
        """Test loop detection integration."""
        fallback = PlannerFallback(window_size=3, max_repeats=2)
        
        # Record some tool calls
        fallback.record_tool_call("query_db", {"limit": 50})
        fallback.record_tool_call("query_db", {"limit": 100})
        
        assert not fallback.is_looping()
        
        # Add similar call
        fallback.record_tool_call("query_db", {"limit": 25})
        
        assert fallback.is_looping()
        
        summary = fallback.get_loop_summary()
        assert summary["is_looping"] is True
        assert summary["total_calls"] == 3


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
