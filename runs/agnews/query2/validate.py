import re
from fractions import Fraction

GROUND_TRUTH = 0.14414414414414414
TOL = 1e-4


def extract_numeric_values(text):
    """
    Extract all numeric interpretations from a line:
    - Fractions (e.g., 16/111)
    - Percentages (e.g., 14.4%)
    - Decimals (e.g., 0.144)
    Returns a list of floats.
    """
    values = []

    # --- Fractions ---
    for num, den in re.findall(r'(\d+)\s*/\s*(\d+)', text):
        try:
            values.append(float(Fraction(int(num), int(den))))
        except ZeroDivisionError:
            pass

    # --- Percentages ---
    for pct in re.findall(r'(\d+(?:\.\d+)?)\s*%', text):
        values.append(float(pct) / 100.0)

    # --- Decimals / integers ---
    for num in re.findall(r'\b\d+\.\d+|\b\d+\b', text):
        values.append(float(num))

    return values


def is_correct(candidate, gt=GROUND_TRUTH, tol=TOL):
    """
    Returns True if ANY extracted numeric value matches ground truth.
    """
    values = extract_numeric_values(candidate)
    return any(abs(v - gt) < tol for v in values)

def validate(llm_output: str):
    """
    Validate if the LLM output contains a numeric value that matches the ground truth.
    Returns:
        (True, "OK") if found
        (False, reason) if not
    """
    llm_output = llm_output.strip()
    if is_correct(llm_output):
        return True, "Ground truth matched in LLM output."
    else:
        reason = f"Ground truth '{GROUND_TRUTH}' (tol={TOL}) not found in LLM output: {llm_output}"
        return False, reason