def validate(llm_output: str):
    gt = "Africa"
    if gt.lower() in llm_output.lower():
        return True, "Ground truth found in LLM output."
    else:
        reason = f"Ground truth '{gt}' not found in LLM output: {llm_output}"
        return False, reason

        