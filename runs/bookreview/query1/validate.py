def validate(llm_output: str):
    """
    Validate if ground truth '2020' is present in LLM output.
    Returns:
        (True, "OK") if found
        (False, reason) if not
    """
    gt = "2020"

    if gt in llm_output:
        return True, "Ground truth found in LLM output."
    else:
        reason = f"Ground truth '{gt}' not found in LLM output."
        return False, reason
