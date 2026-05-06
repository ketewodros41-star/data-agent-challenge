import re
from common_scaffold.validate.levenshtein import levenshtein

def validate(llm_output: str):
    """
    Validate if target string 'SwiftAndroid/swift' appears in LLM output,
    allowing up to 3 character differences and ignoring case.
    """
    ground_truth = "SwiftAndroid/swift"
    target = ground_truth.lower()
    llm_output_lower = llm_output.lower()

    window_size = len(target) + 3  # allow 3-character fuzzy match
    for i in range(len(llm_output_lower) - window_size + 1):
        window = llm_output_lower[i : i + window_size]
        dist = levenshtein(window, target)
        if dist <= 3:
            return True, f"Fuzzy matched: '{window}' with distance {dist}"

    reason = f"No fuzzy match found for '{target}' within 3-character distance"
    return False, reason
