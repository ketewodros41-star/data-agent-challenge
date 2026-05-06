import re

def validate(llm_output: str):
    """
    Validate if LLM output contains the expected agent ID.
    Expected: 005Wt000003NDqDIAW
    Returns:
        (True, "OK") if found
        (False, reason) if not
    """
    expected = "005Wt000003NDqDIAW"

    # Clean the output and check for exact match
    llm_output_clean = llm_output.strip()

    # Check for exact ID match (case sensitive for IDs)
    if expected in llm_output_clean:
        return True, f"Found expected agent ID: {expected}"

    # Check if any agent ID pattern is present (starts with '005')
    agent_pattern = r'005[A-Za-z0-9]{15}'
    found_ids = re.findall(agent_pattern, llm_output_clean)

    if found_ids:
        reason = f"Found agent IDs {found_ids}, but expected '{expected}'"
        return False, reason
    else:
        reason = "No agent ID found in LLM output"
        return False, reason