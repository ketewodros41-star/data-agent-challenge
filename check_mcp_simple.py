#!/usr/bin/env python3
"""Simple MCP server check."""

import urllib.request
import json

def check_server(url, name):
    try:
        data = json.dumps({
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/list",
            "params": {}
        }).encode()
        
        req = urllib.request.Request(url, data=data, headers={'Content-Type': 'application/json'})
        with urllib.request.urlopen(req, timeout=5) as response:
            result = json.loads(response.read().decode())
            return len(result.get('result', {}).get('tools', []))
    except:
        return 0

print("MCP Server Status:")
print(f"Google Toolbox (port 5000): {check_server('http://127.0.0.1:5000/mcp', 'Google')} tools")
print(f"DuckDB MCP (port 8001): {check_server('http://127.0.0.1:8001/mcp', 'DuckDB')} tools")

if __name__ == "__main__":
    print("\nTo start servers manually:")
    print("1. Google Toolbox: uv run python agent/mcp_toolbox.py &")
    print("2. DuckDB: uv run python agent/duckdb_mcp_server.py &")
