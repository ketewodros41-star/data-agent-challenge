def validate(llm_output: str):
    """
    Validate if LLM output contains the expected BANT factor(s).
    Expected: Authority
    Returns:
        (True, "OK") if found
        (False, reason) if not
    """
    expected = "Authority"

    # Clean the output and check for exact match
    llm_output_clean = llm_output.strip()

    # Check for exact word match (case insensitive)
    if expected.lower() in llm_output_clean.lower():
        return True, f"Found expected BANT factor: {expected}"

    # Check if any of the BANT factors are mentioned
    bant_factors = ["Budget", "Authority", "Need", "Timeline"]
    found_factors = []
    for factor in bant_factors:
        if factor.lower() in llm_output_clean.lower():
            found_factors.append(factor)

    if found_factors:
        reason = f"Found BANT factors {found_factors}, but expected '{expected}'"
        return False, reason
    else:
        reason = "No BANT factors found in LLM output"
        return False, reason