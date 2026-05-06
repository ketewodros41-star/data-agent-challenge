import re
from common_scaffold.validate.levenshtein import levenshtein

def normalize(text: str) -> str:
    # Lowercase and collapse multiple whitespaces
    return re.sub(r'\s+', ' ', text.lower().strip())

def fuzzy_match(name: str, text: str, max_distance: int = 3) -> bool:
    name_len = len(name)
    for i in range(0, len(text) - name_len + 1):
        window = text[i:i + name_len + 3]  # add small buffer
        if levenshtein(window, name) <= max_distance:
            return True
    return False

def validate(llm_output: str):
    """
    Fuzzy validate histological type names in LLM output with max 3-character difference.
    Case-insensitive and spacing-normalized.
    """

    ground_truth_names = [
        "Infiltrating Lobular Carcinoma",
        "Mixed Histology (please specify)",
        "Other specify",
    ]

    llm_output_norm = normalize(llm_output)

    for name in ground_truth_names:
        name_norm = normalize(name)
        if not fuzzy_match(name_norm, llm_output_norm):
            reason = f"Not matched (fuzzy) within 3 chars: '{name}'"
            return False, reason

    return True, "All histological types matched (fuzzy)."
