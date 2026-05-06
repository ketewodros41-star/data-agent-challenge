import re
from difflib import SequenceMatcher

GROUND_TRUTH_VARIANTS = [
    "Zo gaat het leven aan je voor (Hillich fjoer | Heilig vuur)",
    "Zo gaat het leven aan je voor",
    "Zo gaat het leven aan je voor - Hillich fjoer | Heilig vuur",
    "006-Zo gaat het leven aan je voor",
    "Syb van der Ploeg - Zo gaat het leven aan je voor",
]
THRESHOLD = 0.75

def normalize(text: str) -> str:
    text = text.lower()
    # remove content inside parentheses
    text = re.sub(r"\([^)]*\)", "", text)
    # remove artist prefixes like "artist - title"
    text = re.sub(r"^.*?\s-\s", "", text)
    # remove non-alphanumeric characters
    text = re.sub(r"[^a-z0-9\s]", "", text)
    # collapse whitespace
    text = re.sub(r"\s+", " ", text).strip()
    return text

def similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, a, b).ratio()

def fuzzy_match(
    ground_truth_variants,
    cand,
    threshold=THRESHOLD
):
    gt_norm = [normalize(g) for g in ground_truth_variants]

    best = None
    best_score = 0.0

    cand_norm = normalize(cand)
    for gt in gt_norm:
        score = similarity(gt, cand_norm)
        if score > best_score:
            best_score = score
            best = cand

    if best_score >= threshold:
        return best, best_score
    return None, best_score

def validate(llm_output: str):
    llm_output = llm_output.strip()
    match, score = fuzzy_match(GROUND_TRUTH_VARIANTS, llm_output)
    if match:
        return True, f"Fuzzy match found: '{match}' with score {score:.2f}"
    else:
        reason = f"No fuzzy match ({GROUND_TRUTH_VARIANTS[1]}) found in {llm_output}. Best score: {score:.2f}"
        return False, reason
