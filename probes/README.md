# Probes Directory

This directory contains diagnostic tools, health checks, and system probes for monitoring and debugging the Oracle Forge agent system.

## Purpose

The probes directory serves as the toolkit for:
- **System health monitoring** - Checking if components are working
- **Performance diagnostics** - Identifying bottlenecks and issues
- **Integration testing** - Verifying database connections and APIs
- **Debugging tools** - Utilities for troubleshooting problems

## Files Overview

### Health Checks
- **Database connectivity probes** - Test PostgreSQL, MongoDB, SQLite, DuckDB connections
- **MCP server health** - Check if MCP services are running and responsive
- **LLM API connectivity** - Verify API keys and service availability

### Diagnostic Tools
- **Performance profilers** - Measure query execution times
- **Memory monitors** - Track resource usage
- **Error analyzers** - Parse and categorize errors

### Integration Tests
- **End-to-end probes** - Test complete query workflows
- **Database-specific tests** - Verify each database type works
- **MCP tool validation** - Check all tools are accessible

## Using Probes

### Quick Health Check
Run a comprehensive system health check:
```bash
uv run python probes/health_check.py
```

### Database Connectivity
Test specific database connections:
```bash
uv run python probes/test_database.py --type postgresql
uv run python probes/test_database.py --type mongodb
uv run python probes/test_database.py --type sqlite
uv run python probes/test_database.py --type duckdb
```

### MCP Server Status
Check MCP service availability:
```bash
uv run python probes/test_mcp.py --port 5000  # Google Toolbox
uv run python probes/test_mcp.py --port 8001  # DuckDB Server
```

### Performance Diagnostics
Run performance profiling:
```bash
uv run python probes/profile_agent.py --query test_query.json
```

## Probe Categories

### 1. Infrastructure Probes
Check underlying services and dependencies:
- **Docker containers** - PostgreSQL and MongoDB status
- **Network connectivity** - Port availability and latency
- **Resource usage** - CPU, memory, disk space

### 2. Application Probes
Test the agent system components:
- **MCP toolbox** - Tool availability and functionality
- **LLM client** - API connectivity and rate limits
- **Context manager** - Knowledge base loading

### 3. Database Probes
Verify database access and performance:
- **Connection tests** - Can we connect to each database?
- **Query performance** - How fast do queries run?
- **Data integrity** - Is data accessible and correct?

### 4. End-to-End Probes
Test complete workflows:
- **Query execution** - Full question-to-answer pipeline
- **Error handling** - How are errors managed?
- **Performance** - End-to-end timing and resource usage

## Probe Results

### Output Format
Probes return structured results:
```json
{
  "probe_name": "database_connectivity",
  "timestamp": "2025-04-18T20:00:00Z",
  "status": "healthy",
  "details": {
    "postgresql": "connected",
    "mongodb": "connected", 
    "sqlite": "connected",
    "duckdb": "connected"
  },
  "metrics": {
    "connection_time_ms": 45,
    "query_time_ms": 120
  }
}
```

### Status Levels
- **healthy** - Everything working normally
- **warning** - Minor issues, system functional
- **critical** - Major problems, system impaired
- **down** - Service unavailable

## Creating New Probes

### Probe Template
```python
#!/usr/bin/env python3
"""
Probe description and purpose.
"""

import json
import sys
from datetime import datetime
from pathlib import Path

def run_probe():
    """Execute the probe and return results."""
    result = {
        "probe_name": "your_probe_name",
        "timestamp": datetime.now().isoformat(),
        "status": "healthy",  # or "warning", "critical", "down"
        "details": {},
        "metrics": {}
    }
    
    # Your probe logic here
    
    return result

def main():
    result = run_probe()
    print(json.dumps(result, indent=2))
    return 0 if result["status"] == "healthy" else 1

if __name__ == "__main__":
    sys.exit(main())
```

### Best Practices
1. **Be specific** - Focus on one aspect per probe
2. **Return structured data** - Use consistent JSON format
3. **Handle errors gracefully** - Don't crash on failures
4. **Provide useful details** - Include metrics and context
5. **Document usage** - Add clear docstrings and comments

## Integration with Monitoring

### Automated Health Checks
Schedule probes to run regularly:
```bash
# Add to crontab for hourly checks
0 * * * * cd /path/to/data-agent-challenge && uv run python probes/health_check.py
```

### Alerting
Set up alerts based on probe results:
- **Critical status** - Immediate notification
- **Warning status** - Daily summary
- **Performance degradation** - Trend analysis

### Logging
Probe results are logged to:
- **Console output** - For immediate feedback
- **Log files** - For historical analysis
- **Monitoring systems** - For dashboards and alerts

## Troubleshooting with Probes

### Common Issues
1. **Database connection refused**
   - Check Docker containers: `docker ps`
   - Verify network connectivity
   - Confirm configuration settings

2. **MCP server not responding**
   - Check server processes: `ps aux | grep mcp`
   - Test port availability: `curl http://localhost:5000/mcp`
   - Review server logs for errors

3. **Performance degradation**
   - Run performance probes: `uv run python probes/profile_agent.py`
   - Check resource usage: `top`, `df -h`
   - Analyze query patterns and optimization

### Debugging Workflow
1. **Run health check** - Identify problem area
2. **Run specific probes** - Isolate the issue
3. **Analyze results** - Understand root cause
4. **Apply fixes** - Implement solution
5. **Verify resolution** - Re-run probes to confirm

## Maintenance

### Regular Updates
- **Update probe logic** as system evolves
- **Add new probes** for new components
- **Retire obsolete probes** when no longer needed
- **Document changes** in probe comments

### Performance Impact
- **Keep probes lightweight** - Minimize resource usage
- **Run asynchronously** - Don't block main operations
- **Cache results** - Avoid repeated expensive operations
- **Monitor probe performance** - Ensure probes aren't causing issues

Probes are essential for maintaining system health and quickly identifying problems. Use them regularly to ensure your Oracle Forge agent is running optimally.
