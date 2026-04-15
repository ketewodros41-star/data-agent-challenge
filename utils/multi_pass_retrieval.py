"""
multi_pass_retrieval — Multi-pass Discovery and Retrieval.
──────────────────────────────────────────────────────────

1. Table Discovery (MultiPassRetriever):
   Narrows from all 12 DAB datasets → relevant databases → relevant tables
   before the agent attempts any query. Implements the discovery-first
   discipline from the OpenAI data agent (prevents overconfident selection).

2. Document Retrieval (retrieve):
   Selects the most relevant KB documents for a given query using
   keyword overlap and Jaccard-style scoring.

Usage:
    from utils.multi_pass_retrieval import MultiPassRetriever, retrieve

    # Discovery
    retriever = MultiPassRetriever()
    result = retriever.retrieve("Which customers had declining repeat purchases in Q3?")

    # KB Retrieval
    docs = retrieve("schema.md", full_kb_documents)
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, List, Optional, Tuple

from agent.models.models import Document


# ── dataset routing index ─────────────────────────────────────────────────
# Keyword signals that route a query to a specific dataset.
# Extend as Drivers discover new routing patterns.

DATASET_INDEX: dict[str, dict] = {
    "agnews": {
        "keywords": ["news", "article", "category", "topic", "headline", "ag news"],
        "db_types":  ["mongodb", "sqlite"],
        "domain":    "news classification",
    },
    "bookreview": {
        "keywords": ["book", "review", "rating", "reader", "author", "genre", "isbn"],
        "db_types":  ["postgresql", "sqlite"],
        "domain":    "book reviews",
    },
    "crmarenapro": {
        "keywords": ["customer", "crm", "ticket", "support", "purchase", "order",
                     "account", "churn", "repeat", "sales", "deal", "contact"],
        "db_types":  ["duckdb", "postgresql", "sqlite"],
        "domain":    "CRM / sales",
    },
    "deps_dev_v1": {
        "keywords": ["dependency", "package", "npm", "pypi", "version", "library",
                     "maven", "cargo", "ecosystem"],
        "db_types":  ["duckdb", "sqlite"],
        "domain":    "software dependencies",
    },
    "github_repos": {
        "keywords": ["github", "repo", "repository", "star", "fork", "commit",
                     "pull request", "issue", "contributor", "language"],
        "db_types":  ["duckdb", "sqlite"],
        "domain":    "open-source repositories",
    },
    "googlelocal": {
        "keywords": ["local", "place", "business", "review", "rating", "restaurant",
                     "google", "location", "category", "map"],
        "db_types":  ["postgresql", "sqlite"],
        "domain":    "local business reviews",
    },
    "music_brainz_20k": {
        "keywords": ["music", "artist", "album", "release", "track", "song",
                     "label", "genre", "brainz", "recording"],
        "db_types":  ["duckdb", "sqlite"],
        "domain":    "music metadata",
    },
    "pancancer_atlas": {
        "keywords": ["cancer", "tumor", "patient", "gene", "mutation", "clinical",
                     "survival", "sample", "tcga", "atlas"],
        "db_types":  ["duckdb", "postgresql"],
        "domain":    "cancer genomics",
    },
    "patents": {
        "keywords": ["patent", "inventor", "claim", "filing", "ipc", "cpc",
                     "assignee", "citation", "application"],
        "db_types":  ["postgresql", "sqlite"],
        "domain":    "patent data",
    },
    "stockindex": {
        "keywords": ["index", "sp500", "nasdaq", "dow", "ftse", "nikkei",
                     "benchmark", "market cap", "index return"],
        "db_types":  ["duckdb", "sqlite"],
        "domain":    "stock indices",
    },
    "stockmarket": {
        "keywords": ["stock", "equity", "price", "volume", "ticker", "close",
                     "open", "high", "low", "dividend", "market", "share"],
        "db_types":  ["duckdb", "sqlite"],
        "domain":    "stock market",
    },
    "yelp": {
        "keywords": ["yelp", "restaurant", "cafe", "review", "rating", "cuisine",
                     "checkin", "tip", "useful", "cool", "funny", "star"],
        "db_types":  ["duckdb", "mongodb"],
        "domain":    "restaurant/business reviews",
    },
}

# ── table-level keyword index ─────────────────────────────────────────────
# Maps (dataset, table_name) → keywords. Populated from KB v2.
# Drivers extend this as they discover table contents.

TABLE_INDEX: dict[tuple[str, str], list[str]] = {
    ("bookreview",    "books_info"):       ["book", "title", "author", "isbn", "genre", "year"],
    ("bookreview",    "review_query"):     ["review", "rating", "user", "text", "date"],
    ("crmarenapro",   "orders"):           ["order", "purchase", "amount", "date", "customer"],
    ("crmarenapro",   "customers"):        ["customer", "name", "email", "segment", "churn"],
    ("crmarenapro",   "tickets"):          ["ticket", "support", "issue", "status", "priority"],
    ("crmarenapro",   "deals"):            ["deal", "value", "stage", "close date", "sales"],
    ("agnews",        "articles"):         ["article", "headline", "body", "category"],
    ("agnews",        "categories"):       ["category", "label", "topic"],
    ("yelp",          "business"):         ["business", "name", "city", "state", "rating", "category"],
    ("yelp",          "review"):           ["review", "text", "stars", "date", "useful", "funny"],
    ("yelp",          "user"):             ["user", "name", "review_count", "yelping_since"],
    ("yelp",          "checkin"):          ["checkin", "date", "business"],
    ("yelp",          "tip"):              ["tip", "text", "date", "business"],
    ("googlelocal",   "places"):           ["place", "name", "address", "category", "rating"],
    ("googlelocal",   "reviews"):          ["review", "text", "rating", "user", "date"],
    ("stockmarket",   "prices"):           ["price", "open", "close", "high", "low", "volume", "date"],
    ("stockindex",    "index_values"):     ["index", "value", "date", "return"],
    ("music_brainz_20k", "releases"):     ["release", "album", "title", "date", "label"],
    ("music_brainz_20k", "artists"):      ["artist", "name", "country", "genre"],
    ("pancancer_atlas",  "clinical"):      ["patient", "survival", "age", "stage", "tumor"],
    ("pancancer_atlas",  "mutations"):     ["gene", "mutation", "variant", "cancer_type"],
    ("github_repos",  "repos"):            ["repo", "star", "fork", "language", "owner"],
    ("github_repos",  "commits"):          ["commit", "sha", "author", "date", "message"],
    ("patents",       "publications"):     ["patent", "title", "abstract", "filing_date", "assignee"],
    ("patents",       "citations"):        ["citation", "patent_id", "cited_patent"],
    ("deps_dev_v1",   "packages"):         ["package", "name", "version", "ecosystem"],
    ("deps_dev_v1",   "dependencies"):     ["dependency", "depends_on", "version_range"],
}


@dataclass
class RetrievalResult:
    datasets:    list[str]
    tables:      list[dict]   # [{"dataset", "table", "db_type", "score", "matched_keywords"}]
    columns:     list[dict]   # [{"dataset", "table", "columns"}]
    explanation: str
    warnings:    list[str] = field(default_factory=list)


class MultiPassRetriever:
    """
    Discovery-first table selection for the Oracle Forge agent.
    """

    def retrieve(
        self,
        query: str,
        top_datasets: int = 3,
        top_tables: int = 5,
        min_table_score: float = 0.1,
    ) -> RetrievalResult:
        tokens = _tokenise(query)
        warnings = []

        # Pass 1: dataset routing
        dataset_scores = _score_datasets(tokens)
        if not dataset_scores:
            warnings.append("Pass 1: No dataset matched query tokens. Returning all datasets.")
            selected_datasets = list(DATASET_INDEX.keys())
        else:
            selected_datasets = [d for d, _ in dataset_scores[:top_datasets]]

        # Pass 2: table ranking
        table_candidates = _score_tables(tokens, selected_datasets)
        table_candidates = [t for t in table_candidates if t["score"] >= min_table_score]
        table_candidates = table_candidates[:top_tables]

        if not table_candidates:
            warnings.append("Pass 2: No tables scored above threshold.")

        # Pass 3: column filtering
        columns = _filter_columns(tokens, table_candidates)

        explanation = _build_explanation(query, dataset_scores, table_candidates)

        return RetrievalResult(
            datasets=selected_datasets,
            tables=table_candidates,
            columns=columns,
            explanation=explanation,
            warnings=warnings,
        )

    def explain(self, query: str) -> str:
        return self.retrieve(query).explanation


# ── KB Document Retrieval Functions ──────────────────────────────────────────

def retrieve(
    query: str,
    documents: List[Document],
    top_k: int = 5,
    min_score: float = 0.1,
) -> List[Document]:
    """
    Return the top_k most relevant KB documents based on keyword overlap.
    """
    if not documents:
        return []

    scored = _keyword_score_docs(query, documents)
    filtered = [(doc, score) for doc, score in scored if score >= min_score]
    filtered.sort(key=lambda x: x[1], reverse=True)

    return [doc for doc, _ in filtered[:top_k]]


def retrieve_with_scores(
    query: str,
    documents: List[Document],
    top_k: int = 5,
) -> List[Tuple[Document, float]]:
    scored = _keyword_score_docs(query, documents)
    scored.sort(key=lambda x: x[1], reverse=True)
    return scored[:top_k]


# ── Utilities & Scoring ──────────────────────────────────────────────────────

def _keyword_score_docs(
    query: str, documents: List[Document]
) -> List[Tuple[Document, float]]:
    query_tokens = set(_tokenise(query))
    results = []
    for doc in documents:
        doc_tokens = set(_tokenise(doc.content))
        if not doc_tokens:
            results.append((doc, 0.0))
            continue
        overlap = query_tokens & doc_tokens
        # Jaccard-style score: overlap / union
        score = len(overlap) / len(query_tokens | doc_tokens)
        results.append((doc, score))
    return results


def _tokenise(text: str) -> list[str]:
    """Lowercase, split on non-alphanumeric, drop short tokens + add bigrams."""
    q = text.lower()
    words = re.findall(r'\b[a-z0-9]{2,}\b', q)  # min 2 chars
    bigrams = [f"{words[i]} {words[i+1]}" for i in range(len(words)-1)]
    return words + bigrams


def _score_datasets(tokens: list[str]) -> list[tuple[str, float]]:
    scores = {}
    for dataset, meta in DATASET_INDEX.items():
        kws = set(meta["keywords"])
        hits = sum(1 for t in tokens if t in kws)
        if hits:
            scores[dataset] = hits / len(kws)
    return sorted(scores.items(), key=lambda x: -x[1])


def _score_tables(tokens: list[str], datasets: list[str]) -> list[dict]:
    candidates = []
    for (dataset, table), kws in TABLE_INDEX.items():
        if dataset not in datasets:
            continue
        kw_set = set(kws)
        matched = [t for t in tokens if t in kw_set]
        score = len(matched) / max(len(kw_set), 1)
        db_type = _infer_db_type(dataset, table)
        candidates.append({
            "dataset":          dataset,
            "table":            table,
            "db_type":          db_type,
            "score":            round(score, 3),
            "matched_keywords": list(set(matched)),
        })
    return sorted(candidates, key=lambda x: -x["score"])


def _filter_columns(tokens: list[str], tables: list[dict]) -> list[dict]:
    result = []
    for t in tables:
        kws = TABLE_INDEX.get((t["dataset"], t["table"]), [])
        matched_cols = [k for k in kws if any(tok in k for tok in tokens)]
        result.append({
            "dataset": t["dataset"],
            "table":   t["table"],
            "columns": matched_cols or ["*"],
        })
    return result


def _infer_db_type(dataset: str, table: str) -> str:
    types = DATASET_INDEX.get(dataset, {}).get("db_types", ["unknown"])
    return types[0]


def _build_explanation(
    query: str,
    dataset_scores: list[tuple[str, float]],
    tables: list[dict],
) -> str:
    lines = [f"Query: \"{query}\"", "", "Pass 1 — Dataset routing:"]
    for ds, sc in dataset_scores[:3]:
        lines.append(f"  {ds:25s}  score={sc:.3f}  domain={DATASET_INDEX[ds]['domain']}")
    lines += ["", "Pass 2 — Table ranking:"]
    for t in tables:
        kws = ", ".join(t["matched_keywords"][:5]) or "—"
        lines.append(f"  {t['dataset']}.{t['table']:30s}  score={t['score']:.3f}  "
                     f"db={t['db_type']}  matched=[{kws}]")
    lines += ["", "Pass 3 — Column filtering: see RetrievalResult.columns"]
    return "\n".join(lines)
