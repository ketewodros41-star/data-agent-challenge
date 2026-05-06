import re

def validate(llm_output: str):
    """
    Validate if LLM output contains the expected issue ID.
    Expected: a03Wt00000JqnHwIAJ
    Returns:
        (True, "OK") if found
        (False, reason) if not
    """
    expected = "a03Wt00000JqnHwIAJ"

    # Clean the output and check for exact match
    llm_output_clean = llm_output.strip()

    # Check for exact ID match (case sensitive for IDs)
    if expected in llm_output_clean:
        return True, f"Found expected agent ID: {expected}"

    # Check if any issue ID pattern is present (starts with 'a03')
    issue_pattern = r'a03[A-Za-z0-9]{15}'
    found_ids = re.findall(issue_pattern, llm_output_clean)

    if found_ids:
        reason = f"Found issue IDs {found_ids}, but expected '{expected}'"
        
        return False, reason
    else:
        reason = "No issue ID found in LLM output"
        
        return False, reason