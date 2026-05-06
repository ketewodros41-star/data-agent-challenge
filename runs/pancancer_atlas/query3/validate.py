import re

def validate(llm_output: str):
    """
    Validate whether the LLM output contains a numeric value that matches
    the ground truth (305.1239198007461) when rounded to 2 decimals,
    or has a valid prefix (305.1 or 305).

    Steps:
    - Extract all numbers from LLM output
    - Round them to 2 decimal places
    - Match against 305.12, 305.1, or 305

    Returns:
        (True, "OK") if match found
        (False, reason) otherwise
    """

    ground_truth = 305.1239198007461
    target_2dp = f"{round(ground_truth, 2):.2f}"  # '305.12'
    target_1dp = f"{round(ground_truth, 1):.1f}"  # '305.1'
    target_int = str(int(ground_truth))          # '305'

    # Extract all number-like patterns from LLM output
    matches = re.findall(r"\d+\.\d+|\d+", llm_output)

    for raw in matches:
        try:
            value = float(raw)
            rounded = f"{round(value, 2):.2f}"
            if rounded in {target_2dp, target_1dp, target_int} or \
               f"{round(value, 1):.1f}" == target_1dp or \
               str(int(value)) == target_int:
                return True, f"Matched value: {raw} -> rounded {rounded}"
        except:
            continue

    reason = f"No value in LLM output matches {target_2dp}, {target_1dp}, or {target_int}"
    return False, reason
