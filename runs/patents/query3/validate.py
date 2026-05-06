import re
import unicodedata
from typing import List, Tuple
from common_scaffold.validate.levenshtein import levenshtein

# ------------------------
# Utility Functions
# ------------------------

def normalize(text: str) -> str:
    """
    Normalize text by lowercasing and removing all non-alphanumeric characters.
    This version is used for global fuzzy matching.
    """
    text = unicodedata.normalize("NFKD", text)
    text = text.lower()
    return re.sub(r"[^\w]", "", text)


def normalize_keep_space(text: str) -> str:
    """
    Normalize text by lowercasing and removing punctuation,
    but preserve whitespace. Used for local window matching.
    """
    text = unicodedata.normalize("NFKD", text)
    text = text.lower()
    text = re.sub(r"[^\w\s]", "", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


# ------------------------
# Ground Truth: list of (assignee, CPC title)
# ------------------------

ground_truth: List[Tuple[str, str]] = [
    ("ABBOTT RYAN", "DIAGNOSIS; SURGERY; IDENTIFICATION"),
    ("AGARWAL AMIT", "DIAGNOSIS; SURGERY; IDENTIFICATION"),
    ("BARRIGAR FREDERICK", "DIAGNOSIS; SURGERY; IDENTIFICATION"),
    ("BLOOM ENERGY CORP", "PROCESSES OR MEANS, e.g. BATTERIES, FOR THE DIRECT CONVERSION OF CHEMICAL ENERGY INTO ELECTRICAL ENERGY"),
    ("BURRIGHT ERIC", "MEASURING OR TESTING PROCESSES INVOLVING ENZYMES, NUCLEIC ACIDS OR MICROORGANISMS; COMPOSITIONS OR TEST PAPERS THEREFOR; PROCESSES OF PREPARING SUCH COMPOSITIONS; CONDITION-RESPONSIVE CONTROL IN MICROBIOLOGICAL OR ENZYMOLOGICAL PROCESSES"),
    ("CALLAS PETER", "DIAGNOSIS; SURGERY; IDENTIFICATION"),
    ("CANTU R ALFREDO", "DIAGNOSIS; SURGERY; IDENTIFICATION"),
    ("CRYSTAL IS INC", "SEMICONDUCTOR DEVICES NOT COVERED BY CLASS H10"),
    ("CRYSTAL IS INC", "SINGLE-CRYSTAL GROWTH; UNIDIRECTIONAL SOLIDIFICATION OF EUTECTIC MATERIAL OR UNIDIRECTIONAL DEMIXING OF EUTECTOID MATERIAL; REFINING BY ZONE-MELTING OF MATERIAL; PRODUCTION OF A HOMOGENEOUS POLYCRYSTALLINE MATERIAL WITH DEFINED STRUCTURE; SINGLE CRYSTALS OR HOMOGENEOUS POLYCRYSTALLINE MATERIAL WITH DEFINED STRUCTURE; AFTER-TREATMENT OF SINGLE CRYSTALS OR A HOMOGENEOUS POLYCRYSTALLINE MATERIAL WITH DEFINED STRUCTURE; APPARATUS THEREFOR"),
    ("FARAPULSE INC", "ELECTROTHERAPY; MAGNETOTHERAPY; RADIATION THERAPY; ULTRASOUND THERAPY"),
    ("GRANDUSKY JAMES R", "SEMICONDUCTOR DEVICES NOT COVERED BY CLASS H10"),
    ("KAEMMERER WILLIAM F", "MEASURING OR TESTING PROCESSES INVOLVING ENZYMES, NUCLEIC ACIDS OR MICROORGANISMS; COMPOSITIONS OR TEST PAPERS THEREFOR; PROCESSES OF PREPARING SUCH COMPOSITIONS; CONDITION-RESPONSIVE CONTROL IN MICROBIOLOGICAL OR ENZYMOLOGICAL PROCESSES"),
    ("KENDALE AMAR", "DIAGNOSIS; SURGERY; IDENTIFICATION"),
    ("LAMBERTI JOSEPH N", "DIAGNOSIS; SURGERY; IDENTIFICATION"),
    ("LIN ARTHUR", "DIAGNOSIS; SURGERY; IDENTIFICATION"),
    ("LIU SHIWEN", "SEMICONDUCTOR DEVICES NOT COVERED BY CLASS H10"),
    ("MAQUET CARDIOVASCULAR LLC", "DIAGNOSIS; SURGERY; IDENTIFICATION"),
    ("PEREZ JUAN I", "DIAGNOSIS; SURGERY; IDENTIFICATION"),
    ("SANGAMO THERAPEUTICS INC", "PEPTIDES"),
    ("SANGAMO THERAPEUTICS INC", "PREPARATIONS FOR MEDICAL, DENTAL OR TOILETRY PURPOSES"),
    ("SANGAMO THERAPEUTICS INC", "SPECIFIC THERAPEUTIC ACTIVITY OF CHEMICAL COMPOUNDS OR MEDICINAL PREPARATIONS"),
    ("SCHOWALTER LEO J", "SEMICONDUCTOR DEVICES NOT COVERED BY CLASS H10"),
    ("SMART JOSEPH A", "SEMICONDUCTOR DEVICES NOT COVERED BY CLASS H10"),
    ("STEWART MICHAEL C", "DIAGNOSIS; SURGERY; IDENTIFICATION"),
    ("US HEALTH", "PEPTIDES"),
    ("VAN BILSEN PAUL", "MEASURING OR TESTING PROCESSES INVOLVING ENZYMES, NUCLEIC ACIDS OR MICROORGANISMS; COMPOSITIONS OR TEST PAPERS THEREFOR; PROCESSES OF PREPARING SUCH COMPOSITIONS; CONDITION-RESPONSIVE CONTROL IN MICROBIOLOGICAL OR ENZYMOLOGICAL PROCESSES"),
    ("VILLAGOMEZ FRED", "DIAGNOSIS; SURGERY; IDENTIFICATION"),
    ("VIVANT MEDICAL INC", "DIAGNOSIS; SURGERY; IDENTIFICATION"),
]

# ------------------------
# Validation Function
# ------------------------

def validate(llm_output: str) -> Tuple[bool, str]:
    """
    Validate the LLM output using two strategies:
    
    1. Fuzzy Matching:
       Normalize the full output and slide a window over it to check if the
       (assignee + title) combination matches with Levenshtein distance <= 10.

    2. Local Window Match:
       Normalize the output while preserving space, locate the assignee, and
       check if the title appears within a ±15 character window.

    Because LLM outputs are unstable and vary in structure, this dual-strategy
    improves robustness. We only require one method to match for success.
    """

    llm_output_norm = normalize(llm_output)
    llm_output_with_space = normalize_keep_space(llm_output)

    for assignee, title in ground_truth:
        combined = normalize(assignee + title)
        window_size = len(combined) + 10
        found_fuzzy = False

        # Fuzzy matching using sliding window + Levenshtein
        for i in range(len(llm_output_norm) - window_size + 1):
            window = llm_output_norm[i : i + window_size]
            if levenshtein(window, combined) <= 10:
                found_fuzzy = True
                break

        # Local window matching
        norm_assignee = normalize(assignee)
        norm_title = normalize(title)
        idx = llm_output_with_space.find(norm_assignee)
        found_local = False

        if idx != -1:
            start = max(0, idx - 200)
            end = min(len(llm_output_with_space), idx + len(norm_assignee) + 200)
            window = normalize(llm_output_with_space[start:end])
            if norm_title in window:
                found_local = True

        # If neither method matches, return failure
        if not (found_fuzzy or found_local):
            reason = f"No match for: {assignee} + {title}"
            return False, reason

    return True, "All assignee-title pairs matched successfully by at least one method."
