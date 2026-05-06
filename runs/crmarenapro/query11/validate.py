import re

def validate(llm_output: str):
    """
    Validate if LLM output contains the expected product ID.
    Expected: 01tWt000006hV8LIAU
    Returns:
        (True, "OK") if found
        (False, reason) if not
    """
    expected = "01tWt000006hV8LIAU"

    # Clean the output and check for exact match
    llm_output_clean = llm_output.strip()

    # Check for exact ID match (case sensitive for IDs)
    if expected in llm_output_clean:
        return True, f"Found expected product ID: {expected}"

    # Check if any product ID pattern is present (starts with '01t')
    product_pattern = r'01t[A-Za-z0-9]{15}'
    found_ids = re.findall(product_pattern, llm_output_clean)

    if found_ids:
        reason = f"Found product IDs {found_ids}, but expected '{expected}'"
        return False, reason
    else:
        reason = "No product ID found in LLM output"
        return False, reason