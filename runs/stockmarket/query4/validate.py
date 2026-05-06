import re
from common_scaffold.validate.levenshtein import levenshtein

def validate(llm_output: str):
    """
    Validate that:
    - Each GT name appears in LLM output (case-insensitive, exact or <=5 edits)
    - Use dynamic window length around GT name length for matching

    Returns:
        (True, "OK") if all pass
        (False, reason) if not
    """
    gt_names = [
        "MFA Financial, Inc",
        "Argo Group International Holdings, Ltd",
        "HDFC Bank Limited Common Stock",
        "Albany International Corporation Common Stock",
        "DTE Energy Company"
    ]

    llm_output_clean = re.sub(r'\s+', ' ', llm_output).strip().lower()

    for gt_name in gt_names:
        gt_name_clean = gt_name.lower()
        gt_len = len(gt_name_clean)

        # First: exact match
        if gt_name_clean in llm_output_clean:
            continue

        # Else: fuzzy match within a window
        min_distance = float('inf')
        best_match = ""
        window_range = 10  # allow ±10 chars around GT length

        for i in range(len(llm_output_clean) - gt_len + 1):
            for extra in range(-window_range, window_range + 1):
                start = i
                end = i + gt_len + extra
                if end > len(llm_output_clean) or end <= start:
                    continue
                candidate = llm_output_clean[start:end]

                # Remove digits to avoid interference
                candidate = re.sub(r'\b\d+([.,]\d+)?\b', '', candidate)
                candidate = re.sub(r'\s+', ' ', candidate).strip()
                if not candidate:
                    continue

                dist = levenshtein(gt_name_clean, candidate)
                if dist < min_distance:
                    min_distance = dist
                    best_match = candidate
                    if min_distance == 0:
                        break
            if min_distance == 0:
                break

        if min_distance <= 5:
            pass
        else:
            reason = (
                f"Name not found within 5 edits: '{gt_name}', "
                f"closest: '{best_match}' (distance={min_distance})"
            )
            return False, reason

    return True, "All names matched (exact or ≤5 edits)."