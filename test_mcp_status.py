#!/usr/bin/env python3
"""Simple test to check MCP server status."""

import json
import urllib.request
import urllib.error

def test_mcp_server(url, name):
    """Test MCP server connectivity."""
    print(f"\nTesting {name} at {url}")
    try:
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/list",
            "params": {}
        }
        
        data = json.dumps(payload).encode('utf-8')
        req = urllib.request.Request(url, data=data, headers={'Content-Type': 'application/json'})
        
        with urllib.request.urlopen(req, timeout=5) as response:
            result = json.loads(response.read().decode('utf-8'))
            
        if 'result' in result:
            tools = result['result'].get('tools', [])
            print(f"  SUCCESS: {len(tools)} tools available")
            return True
        else:
            print(f"  ERROR: Invalid response format")
            return False
            
    except urllib.error.URLError as e:
        print(f"  ERROR: Cannot connect - {e.reason}")
        return False
    except Exception as e:
        print(f"  ERROR: {e}")
        return False

def main():
    print("MCP Server Status Check")
    print("=" * 40)
    
    # Test Google Toolbox (port 5000)
    google_ok = test_mcp_server("http://127.0.0.1:5000/mcp", "Google Toolbox")
    
    # Test DuckDB (port 8001)
    duckdb_ok = test_mcp_server("http://127.0.0.1:8001/mcp", "DuckDB MCP")
    
    print(f"\nSummary:")
    print(f"Google Toolbox: {'WORKING' if google_ok else 'NOT WORKING'}")
    print(f"DuckDB MCP: {'WORKING' if duckdb_ok else 'NOT WORKING'}")
    
    if google_ok:
        print("\nPostgreSQL connection should be working through Google Toolbox!")
    else:
        print("\nGoogle Toolbox is not running - need to start it")

if __name__ == "__main__":
    main()
