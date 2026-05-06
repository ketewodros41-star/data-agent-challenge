"""
Regression test for DuckDB schema inspection failure and planner fallback issues.

Tests the specific failure scenario:
1. DuckDB schema inspection unavailable
2. Planner fallback into repeated Mongo probes
3. Loop detection prevents repetitive queries
4. Safe environment handling prevents KeyError
"""

import pytest
from unittest.mock import Mock, MagicMock
from agent.agentic_loop import AgenticLoop, AGENTIC_TOOLS
from agent.llm_client import LLMClient, LLMToolCall
from agent.loop_detector import LoopDetector
from agent.planner_fallback import PlannerFallback


class TestDuckDBFallbackRegression:
    """Regression test for DuckDB fallback and loop prevention."""
    
    def setup_method(self):
        """Set up test fixtures."""
        self.mock_toolbox = Mock()
        self.mock_client = Mock(spec=LLMClient)
        self.mock_sandbox = Mock()
        
        # Mock database configs with DuckDB
        self.db_configs = {
            "user_database": {"type": "duckdb"},
            "yelp_db": {"type": "mongodb"}
        }
        
        # Mock toolbox tool source map
        self.mock_toolbox._tool_source_map = {
            "find_yelp_businesses": "mongo_main",
            "sqlite_duckdb_query": "sqlite_user"
        }
        
        # Mock toolbox call_tool to simulate failures
        def mock_call_tool(tool_name, params):
            result = Mock()
            if tool_name == "sqlite_duckdb_query" and "SHOW TABLES" in str(params):
                result.success = True
                result.data = [{"name": "review"}, {"name": "user"}]
            elif tool_name == "find_yelp_businesses":
                result.success = True
                result.data = [{"business_id": "businessid_1", "name": "Test Business"}]
            else:
                result.success = False
                result.error = f"Tool {tool_name} not available"
            return result
        
        self.mock_toolbox.call_tool.side_effect = mock_call_tool
        
        self.loop = AgenticLoop(
            toolbox=self.mock_toolbox,
            db_configs=self.db_configs,
            client=self.mock_client,
            schema_context="",
            kb_context="",
            max_iterations=5,
            sandbox_client=self.mock_sandbox
        )
    
    def test_duckdb_schema_discovery_fallback(self):
        """Test that DuckDB schema discovery uses fallback queries."""
        # Test _resolve_list_tool for DuckDB
        list_tool = self.loop._resolve_list_tool("user_database", "duckdb")
        assert list_tool is not None  # Should return a tool name
        
        # Test _tool_list_db with DuckDB fallback
        result, success = self.loop._tool_list_db({"database": "user_database"}, ["user_database"])
        
        assert success is True
        assert "Discovered tables" in result or "Schema for" in result
    
    def test_loop_detection_prevents_repetitive_mongo_queries(self):
        """Test that loop detection stops repetitive Mongo queries."""
        # Simulate repetitive Mongo queries
        mongo_params = {"database": "yelp_db", "query": "business", "query_type": "mongo"}
        
        # Record several similar calls
        for i in range(4):
            self.loop._loop_detector.record_tool_call("query_db", {
                "database": "yelp_db", 
                "query_type": "mongo", 
                "query": f"business.*limit {i*10}"
            })
        
        # Should detect loop
        assert self.loop._loop_detector.is_looping()
        
        # Should prevent execution
        result, success = self.loop._tool_query_db(mongo_params, ["yelp_db"], 1)
        assert success is False
        assert "Loop detected" in result
    
    def test_safe_execute_python_prevents_keyerror(self):
        """Test that safe execute_python prevents KeyError for missing env keys."""
        code = """
import pandas as pd
df1 = pd.DataFrame(env['data_1'])
df2 = pd.DataFrame(env["data_2"])
result = df1.merge(df2)
"""
        
        env = {"data_1": [{"id": 1}]}  # data_2 is missing
        
        planner = PlannerFallback()
        safe_env = planner.safe_execute_python_env(code, env)
        
        assert "data_2" in safe_env
        assert safe_env["data_2"] == []  # Should be filled with empty list
        assert safe_env["data_1"] == [{"id": 1}]  # Original should remain
    
    def test_duckdb_fallback_with_known_tables(self):
        """Test fallback to known tables when schema discovery fails."""
        # Mock toolbox to return failure for all tools
        def mock_call_tool_fail(tool_name, params):
            result = Mock()
            result.success = False
            result.error = "Tool unavailable"
            return result
        
        self.mock_toolbox.call_tool.side_effect = mock_call_tool_fail
        
        # Test list_db fallback
        result, success = self.loop._tool_list_db({"database": "user_database"}, ["user_database"])
        
        assert success is False  # Should still fail but provide helpful info
        assert "Known tables" in result or "Try querying" in result
    
    def test_normalized_loop_detection(self):
        """Test that loop detection uses normalization for semantic matches."""
        detector = LoopDetector(window_size=5, max_repeats=2)
        
        # Record semantically similar queries
        queries = [
            {"database": "yelp_db", "query": "business.*limit 50"},
            {"database": "yelp_db", "query": "business.*limit 100"},
            {"database": "yelp_db", "query": "business.*limit 25"},
        ]
        
        for query in queries:
            detector.record_tool_call("query_db", query)
        
        # Should detect loop due to normalization
        assert detector.is_looping()
        
        summary = detector.get_loop_summary()
        assert summary["is_looping"] is True
        assert len(summary["loops_detected"]) > 0
    
    def test_integration_scenario(self):
        """Test the complete failure scenario integration."""
        # Mock LLM responses to simulate the problematic behavior
        mock_responses = [
            # First response: try to list DuckDB schema
            Mock(tool_calls=[LLMToolCall(name="list_db", input={"database": "user_database"})]),
            # Second response: fall back to Mongo queries (repetitive)
            Mock(tool_calls=[LLMToolCall(name="query_db", input={
                "database": "yelp_db", 
                "query": '{"name": "Indiana"}', 
                "query_type": "mongo"
            })]),
            # Third response: another similar Mongo query
            Mock(tool_calls=[LLMToolCall(name="query_db", input={
                "database": "yelp_db", 
                "query": '{"name": "Indiana.*"}', 
                "query_type": "mongo"
            })]),
            # Fourth response: yet another similar Mongo query (should trigger loop detection)
            Mock(tool_calls=[LLMToolCall(name="query_db", input={
                "database": "yelp_db", 
                "query": '{"name": "Indianapolis"}', 
                "query_type": "mongo"
            })]),
        ]
        
        self.mock_client.create_with_tools.side_effect = [
            Mock(tool_calls=mock_responses[0].tool_calls),  # First call
            Mock(tool_calls=mock_responses[1].tool_calls),  # Second call
            Mock(tool_calls=mock_responses[2].tool_calls),  # Third call
            Mock(tool_calls=mock_responses[3].tool_calls),  # Fourth call
        ]
        
        # Mock the tool execution results
        list_result, list_success = self.loop._tool_list_db({"database": "user_database"}, ["user_database"])
        query_result, query_success = self.loop._tool_query_db(
            {"database": "yelp_db", "query": "test", "query_type": "mongo"}, 
            ["yelp_db"], 
            1
        )
        
        # Verify DuckDB schema discovery provides helpful fallback
        assert list_success is True or "Known tables" in list_result
        
        # Verify loop detection would trigger after repetitive queries
        for i in range(3):
            self.loop._loop_detector.record_tool_call("query_db", {
                "database": "yelp_db", 
                "query_type": "mongo", 
                "query": f"business.*indiana.*limit {i*10}"
            })
        
        assert self.loop._loop_detector.is_looping()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
