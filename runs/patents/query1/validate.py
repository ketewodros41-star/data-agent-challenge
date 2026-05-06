def validate(llm_output: str):
    """
    Validate that all CPC codes in ground truth appear in the LLM output.

    - Case-insensitive
    - No proximity constraint
    - Each code must appear at least once

    Returns:
        (True, "OK") if all CPC codes are present
        (False, reason) if any are missing
    """
    ground_truth = [
        "A22B", "A23J", "A23P", "A24D", "A24F", "A41G", "A47F", "A61P", "A62B", "A62D",
        "A63H", "B08B", "B09B", "B09C", "B24B", "B27C", "B27G", "B28D", "B30B", "B60H",
        "B60P", "B63G", "B65G", "C01D", "C01G", "C21B", "C25B", "E02D", "E04G", "E21D",
        "E21F", "F16M", "F17B", "F24D", "F25J", "F26B", "G01H", "G01L", "G05G", "G06J",
        "G06N", "G06T", "G06V", "G08G", "G16B", "G16C", "G16H", "G21F", "H02B", "H02G"
    ]

    llm_lower = llm_output.lower()

    for code in ground_truth:
        if code.lower() not in llm_lower:
            reason = f"Missing CPC code: {code}"
            
            return False, reason

    return True, "All CPC codes present in LLM output."
