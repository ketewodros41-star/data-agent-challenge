# kb/domain/ CHANGELOG



## 2026-04-13 — Domain documents added (4 documents)

All documents written from DAB dataset inspection and schema introspection.
Injection tests run before commit. Results recorded in [kb/architecture/injection_tests/results.md](../architecture/injection_tests/results.md).

| File | Injection test question | Result |
|---|---|---|
| agent.md | What are the 6 steps of the execution loop in order? | PASS |
| domain_term_definitions.md | In crmarenapro, what does 'won deal' mean and which column and value identify it? | PASS |
| join_key_glossary.md | How is the Yelp business identifier formatted in MongoDB vs DuckDB, and what is the correct join procedure? | PASS |
| schema.md | What data quality issue affects all ID fields in crmarenapro, and what must you do before any join? | PASS |

**Critical finding recorded during this commit:**
The `stockindex` dataset join (`indexinfo_database` ↔ `indextrade_database`) has no SQL or regex resolution path — the exchange name / symbol semantic gap requires a pre-loaded knowledge mapping. This was caught during KB construction and documented in `join_key_glossary.md` before any agent code was written. See Decision Log.

---

## 2026-04-15 — Domain documents updated (2 documents)

| File | Change | Injection test | Result |
|---|---|---|---|
| dataset_overview.md | Added full dataset registry for all 12 DAB datasets; added exchange-to-symbol mapping table for stockindex; added join key issue summaries per dataset | How many total queries exist in the DAB benchmark and across how many datasets? | PASS |
| unstructured_field_inventory.md | Added extraction patterns for Yelp attributes (ast.literal_eval), googlelocal state column clarification, agnews LLM classification, PATENTS date parsing (dateparser) | What format are PATENTS date fields stored in, and what parsing approach is recommended? | PASS |
| join_key_glossary.md | Added PANCANCER_ATLAS barcode regex extraction, DEPS_DEV_V1 composite key normalisation, music_brainz_20k deduplication rule | Which datasets have clean joins requiring no key transformation? | PASS |
| schema.md | Expanded schema entries for stockmarket dynamic table-per-ticker structure; added googlelocal state column operating status clarification | How is stock price history organised in stocktrade_database, and how do you find which tables exist? | PASS |

---

## Rules for future entries

Every ADDITION must record:
  - Filename, injection test question used, result (PASS only)

Every REMOVAL must record:
  - Filename, reason for removal, date
  - "Failed injection test" is a valid reason — remove immediately

Every UPDATE must record:
  - Filename, what changed, injection test re-run, result

Growth without removal = noise.
Never commit a document that failed its injection test.
Never commit a document without running its injection test.
