import re

def validate(llm_output: str):
    """
    Validate if LLM output contains the expected stage name.
    Expected: Negotiation
    Valid stages: ('Qualification', 'Discovery', 'Quote', 'Negotiation', 'Closed')
    Returns:
        (True, "OK") if found
        (False, reason) if not
    """
    expected = "Negotiation"
    valid_stages = ["Qualification", "Discovery", "Quote", "Negotiation", "Closed"]

    # Clean the output and check for exact match
    llm_output_clean = llm_output.strip()

    # Check for exact stage match (case insensitive)
    if expected.lower() in llm_output_clean.lower():
        return True, f"Found expected agent ID: {expected}"

    # Check if any valid stage is mentioned
    found_stages = []
    for stage in valid_stages:
        if stage.lower() in llm_output_clean.lower():
            found_stages.append(stage)

    if found_stages:
        reason = f"Found stages {found_stages}, but expected '{expected}'"
        return False, reason
    else:
        reason = "No valid stage name found in LLM output"
        return False, reason