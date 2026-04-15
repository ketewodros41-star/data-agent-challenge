# Failure Categories

Known failure modes observed on DAB benchmark queries.
Used by SelfCorrectionLoop to classify errors and select correction strategies.

---

## Category 1: Routing Error
**Description:** Query sent to wrong database (e.g. asking PostgreSQL for review text)
**Symptoms:** Empty result set, table not found
**Correction:** Re-route to correct database based on entity type

## Category 2: Join Key Mismatch
**Description:** Cross-database join on incompatible types (e.g. int vs string)
**Symptoms:** Zero rows after join, type cast error
**Correction:** Apply `normalize_key_value()` from join_key_resolver

## Category 3: Schema Drift
**Description:** Column or table name differs from expected schema
**Symptoms:** `column "X" does not exist`, `collection not found`
**Correction:** Re-introspect schema and regenerate query

## Category 4: Unstructured Field Without Sandbox
**Description:** Trying to aggregate free-text field with SQL
**Symptoms:** Incorrect aggregate, nonsensical result
**Correction:** Set `requires_sandbox = True`, route to sandbox extraction

## Category 5: Ambiguous Entity
**Description:** Entity maps to multiple databases; wrong one chosen
**Symptoms:** Result doesn't match expected magnitude
**Correction:** Query both databases, use the one with more rows or higher confidence

## Category 6: Timeout / Connection Error
**Description:** Database unreachable or query takes too long
**Symptoms:** Connection error, timeout exception
**Correction:** Fall back to alternative database if available; reduce query scope

## Category 7: Aggregation Error
**Description:** Incorrect GROUP BY, missing HAVING, wrong aggregate function
**Symptoms:** Wrong numeric result
**Correction:** Rewrite aggregation logic; validate against sample data
