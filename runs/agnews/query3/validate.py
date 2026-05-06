import re

GROUND_TRUTH = 336.6363636363636
TOL = 1e-2


def extract_numeric_values(text):
    """
    Extract all numeric values from a candidate answer.
    Supports:
      - integers
      - decimals
    Returns a list of floats.
    """
    values = []

    # Match integers and decimals (including standalone numbers like "370" or "336.63")
    for num in re.findall(r'\b\d+\.\d+|\b\d+\b', text):
        try:
            values.append(float(num))
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
    llm_output = llm_output.strip()
    if is_correct(llm_output):
        return True, "Ground truth numeric value found in LLM output."
    else:
        reason = f"Ground truth numeric value '{GROUND_TRUTH}' (tol={TOL}) not found in LLM output: {llm_output}"
        return False, reason