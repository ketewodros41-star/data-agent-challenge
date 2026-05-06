import re

GROUND_TRUTH = 1059.46
TOL = 1e-2


def extract_numeric_values(text):
    """
    Extract all numeric values from a candidate answer.
    Handles:
      - integers
      - decimals
      - currency formats like $1059.46 or 1059.46 USD
    Returns a list of floats.
    """
    values = []

    # Match numbers like 1059.46, 601.44, 0, etc.
    for match in re.findall(r'\$?\b\d+(?:\.\d+)?\b', text):
        try:
            values.append(float(match.replace("$", "")))
        except ValueError:
            pass

    return values


def is_correct(candidate, gt=GROUND_TRUTH, tol=TOL):
    """
    Returns True if ANY extracted numeric value matches the ground truth.
    """
    values = extract_numeric_values(candidate)
    return any(abs(v - gt) < tol for v in values)

def validate(llm_output: str):
    if is_correct(llm_output):
        return True, "Ground truth found in LLM output."
    else:
        reason = f"Ground truth '{GROUND_TRUTH}' not found in LLM output: {llm_output}"
        return False, reason