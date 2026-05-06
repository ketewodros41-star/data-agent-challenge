import re

def validate(llm_output: str):
    """
    Validate if LLM output contains the expected state abbreviation.
    Expected: MI
    Returns:
        (True, "OK") if found
        (False, reason) if not
    """
    expected = "MI"

    # Common US state abbreviations for reference
    us_states = [
        "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "FL", "GA",
        "HI", "ID", "IL", "IN", "IA", "KS", "KY", "LA", "ME", "MD",
        "MA", "MI", "MN", "MS", "MO", "MT", "NE", "NV", "NH", "NJ",
        "NM", "NY", "NC", "ND", "OH", "OK", "OR", "PA", "RI", "SC",
        "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV", "WI", "WY"
    ]

    # Clean the output and check for exact match
    llm_output_clean = llm_output.strip()

    # Check for exact state match (case insensitive)
    if expected.upper() in llm_output_clean.upper():
        return True, f"Found expected state: {expected}"

    # Check if any valid state abbreviation is mentioned
    found_states = []
    for state in us_states:
        if re.search(r'\b' + state + r'\b', llm_output_clean, re.IGNORECASE):
            found_states.append(state)

    if found_states:
        reason = f"Found states {found_states}, but expected '{expected}'"
        
        return False, reason
    else:
        reason = "No state abbreviation found in LLM output"
        
        return False, reason