def validate(llm_output: str):
    """
    Validate LLM output for query1:
    - All names from ground truth must appear (case-sensitive, exact).
    - Names must appear in the same order as in ground truth.
    Returns:
        (True, "OK") if valid
        (False, reason) if invalid
    """
    ground_truth = [
        "Widows Peak Salon",
        "City Textile",
        "Nobel Textile Co",
        "San Soo Dang",
        "Nova Fabrics"
    ]

    last_index = -1
    for name in ground_truth:
        idx = llm_output.find(name)
        if idx == -1:
            reason = f"Missing name in LLM output: {name}"
            
            return False, reason

        if idx < last_index:
            reason = f"Name out of order: {name}"
            
            return False, reason

        last_index = idx

    return True, "All names are present and in correct order."
