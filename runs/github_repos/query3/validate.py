import re

def validate(llm_output: str):
    """
    Check if the number 1077 appears in the LLM output.

    The match should be exact (as a complete number, not part of another number),
    and can be anywhere in the text.

    Returns:
        (True, "OK") if 1077 is found
        (False, reason) otherwise
    """
    matches = re.findall(r"\b1077\b", llm_output)
    if matches:
        return True, "Found 1077 in LLM output."
    else:
        reason = "Number 1077 not found in LLM output."
        return False, reason

