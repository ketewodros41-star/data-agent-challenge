import re

def validate(llm_output: str):
    """
    Validate if LLM output contains the expected knowledge article ID.
    Expected: ka0Wt000000EnwvIAC
    Returns:
        (True, "OK") if found
        (False, reason) if not
    """
    expected = "ka0Wt000000EnwvIAC"

    # Clean the output and check for exact match
    llm_output_clean = llm_output.strip()

    # Check for exact ID match (case sensitive for IDs)
    if expected in llm_output_clean:
        return True, f"Found expected agent ID: {expected}"

    # Check if any knowledge article ID pattern is present (starts with 'ka0')
    ka_pattern = r'ka0[A-Za-z0-9]{15}'
    found_ids = re.findall(ka_pattern, llm_output_clean)

    if found_ids:
        reason = f"Found knowledge article IDs {found_ids}, but expected '{expected}'"
        
        return False, reason
    else:
        reason = "No knowledge article ID found in LLM output"
        
        return False, reason