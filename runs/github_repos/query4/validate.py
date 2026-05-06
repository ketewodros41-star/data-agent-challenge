import re
from common_scaffold.validate.levenshtein import levenshtein

def validate(llm_output: str):
    """
    Validate whether all repo_names appear in LLM output,
    using case-insensitive fuzzy matching (<= 3 char differences).
    """
    ground_truth = [
        "apple/swift",
        "twbs/bootstrap",
        "Microsoft/vscode",
        "facebook/react",
        "tensorflow/tensorflow"
    ]

    llm_output_lower = llm_output.lower()

    for name in ground_truth:
        target = name.lower()
        window_size = len(target) + 3  # allow 3-character fuzzy match
        found = False
        for i in range(len(llm_output_lower) - window_size + 1):
            window = llm_output_lower[i : i + window_size]
            if levenshtein(window, target) <= 3:
                found = True
                break
        if not found:
            reason = f"Could not match: '{name}'"
            return False, reason

    return True, "All repo names matched with fuzzy tolerance."
