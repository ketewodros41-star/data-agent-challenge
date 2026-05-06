# Utils Directory

This directory contains utility functions and helper modules that support the agent system.

## Files Overview

### Core Utilities
- **`dab_output.py`** - DAB (Data Agent Benchmark) format output handling
- **Helper modules** - Various utility functions for data processing and formatting

## How Utils Are Used

### DAB Output Handling
The `dab_output.py` module handles:
- **Result formatting** - Converting agent results to DAB format
- **Query artifact management** - Managing query execution artifacts
- **Output validation** - Ensuring output meets DAB requirements

### Common Patterns
- **Data transformation** - Converting between different data formats
- **File operations** - Reading and writing query results
- **Validation helpers** - Checking data integrity and format compliance

## Adding New Utilities

When adding new utility modules:

1. **Choose descriptive names** - Use clear, purpose-driven names
2. **Document functions** - Add docstrings and examples
3. **Handle errors gracefully** - Provide meaningful error messages
4. **Write tests** - Add unit tests in the appropriate test directory
5. **Update imports** - Ensure modules are properly imported where needed

## Best Practices

- **Keep functions focused** - Each function should do one thing well
- **Use type hints** - Improve code readability and IDE support
- **Handle edge cases** - Consider empty data, malformed input, etc.
- **Log appropriately** - Add logging for debugging and monitoring
- **Follow project conventions** - Use the same coding style as the rest of the project

## Dependencies

Utils may depend on:
- **Standard library** - os, json, pathlib, etc.
- **Project modules** - agent components, kb modules
- **Third-party libraries** - pandas, numpy (if needed)

## Testing

Test utilities with:
```bash
uv run python -m pytest utils/tests/
# Or test specific modules
uv run python utils/test_dab_output.py
```
