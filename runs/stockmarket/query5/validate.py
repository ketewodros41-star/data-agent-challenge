import re
from common_scaffold.validate.levenshtein import levenshtein

def validate(llm_output: str):
    """
    Validate:
    - all gt names are present (case-insensitive, exact or ≤5 edits, dynamic window)

    Returns:
        (True, "OK") if all pass
        (False, reason) if not
    """
    ground_truth_names = [
        "Synthesis Energy Systems, Inc",
        "TD Holdings, Inc",
        "TMSR Holding Company Limited",
        "Verb Technology Company, Inc",
        "Sunesis Pharmaceuticals, Inc",
    ]

    llm_output_clean = re.sub(r'\s+', ' ', llm_output).strip().lower()

    for gt_name in ground_truth_names:
        gt_name_clean = gt_name.lower()
        name_len = len(gt_name_clean)

        # exact
        if gt_name_clean in llm_output_clean:
            continue

        # fuzzy
        min_distance = float('inf')
        best_match = ""
        window_range = 10

        for i in range(len(llm_output_clean) - name_len + 1):
            for extra in range(-window_range, window_range + 1):
                start = i
                end = i + name_len + extra
                if end > len(llm_output_clean) or end <= start:
                    continue

                candidate = llm_output_clean[start:end]
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
            reason = f"Name not found within 5 edits: '{gt_name}', closest: '{best_match}' (distance={min_distance})"
            return False, reason

    return True, "All names (exact or ≤5 edits) matched."