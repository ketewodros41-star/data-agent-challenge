# DAB Dataset Overview

KB v2 — Domain Knowledge Base. Inject this document at agent session start.
Each dataset entry describes: databases, types, join mechanism, and primary challenge.

> What databases exist, what domain they cover, and which hard requirements apply.

## DAB Overview
- **Total queries:** 54 across 12 datasets
- **Database systems:** PostgreSQL, MongoDB, SQLite, DuckDB
---

## 1. yelp

| Database | Type | Key collections/tables |
|---|---|---|
| yelp_db | MongoDB | business, checkin |
| user_database | DuckDB | review, tip, user |

**Join key:** `business_id` (MongoDB) ↔ `business_ref` (DuckDB). These are NOT the same string. MongoDB uses prefix `businessid_N`; DuckDB uses `businessref_N`. Strip prefix and match integer suffix.

**Primary challenges:** ill-formatted join key, unstructured `description` field for location parsing, nested `attributes` dict for service info, `hours` dict for operating schedule.

**Domain notes:**
- `is_open=1` means currently open; `is_open=0` means closed.
- `elite` field in user table is a comma-separated string of years (e.g. "2015,2016,2017").
- `attributes` is a Python dict stored as string — parse with `ast.literal_eval` or `json.loads` after cleanup.
- Location (city, state) is NOT a structured column — it lives inside the `description` text field of the `business` collection.

---

## 2. googlelocal

| Database | Type | Key tables |
|---|---|---|
| review_database | SQLite | review |
| googlelocal_db | PostgreSQL | business_description |

**Join key:** `gmap_id` — exact match across both databases. No format mismatch.

**Primary challenges:** unstructured `description` field for business category/attribute extraction, `MISC` dict field for service details, `hours` list field.

**Domain notes:**
- `state` in business_description is business *operating status* ("OPEN", "CLOSED", "TEMPORARILY_CLOSED"), NOT a US state abbreviation.
- US geographic state must be inferred from `description` text.
- `rating` in review is integer 1–5.

---

## 3. music_brainz_20k

| Database | Type | Key tables |
|---|---|---|
| tracks_database | SQLite | tracks |
| sales_database | DuckDB | sales |

**Join key:** `track_id` (integer, exact match across both tables).

**Primary challenges:** entity resolution — the `tracks` table contains duplicates. Multiple `track_id`s can represent the same real-world track. Dedup by comparing `title`, `artist`, `album`, `year`. Do NOT use exact string equality; use fuzzy/semantic comparison.

**Domain notes:**
- Sales countries: USA, UK, Canada, Germany, France only.
- Sales stores: iTunes, Spotify, Apple Music, Amazon Music, Google Play only.
- `year` field in tracks may be formatted inconsistently (e.g., "2005", "2005-01-01", null).
- `length` field is in seconds or formatted string — normalise before numeric comparison.

---

## 4. stockmarket

| Database | Type | Key tables |
|---|---|---|
| stockinfo_database | SQLite | stockinfo |
| stocktrade_database | DuckDB | one table per ticker symbol |

**Join key:** `Symbol` (stockinfo) ↔ table name in stocktrade_database. Each stock's price history is its own DuckDB table named by ticker.

**Primary challenges:** dynamic table discovery (must enumerate tables in stocktrade_database to find relevant tickers), domain code lookups.

**Domain notes — Listing Exchange Codes:**
- A = NYSE MKT
- N = New York Stock Exchange (NYSE)
- P = NYSE ARCA
- Z = BATS Global Markets
- V = Investors' Exchange (IEXG)
- Q = NASDAQ Global Select Market

**Domain notes — Financial Status Codes:**
- D = Deficient (does not meet listing standards)
- E = Delinquent (late filings)
- Q = Bankrupt
- N = Normal (blank or N = no issue)

**Domain notes — ETF field:** "Y" = is an ETF; "N" = is a stock.

---

## 5. stockindex

| Database | Type | Key tables |
|---|---|---|
| indexinfo_database | SQLite | index_info |
| indextrade_database | DuckDB | index_trade |

**Join key:** Requires semantic mapping. `Exchange` (full name, e.g. "Tokyo Stock Exchange") in SQLite ↔ `Index` (abbreviated symbol, e.g. "N225") in DuckDB. No direct foreign key — must map by knowledge.

**Key exchange-to-index mappings:**
| Exchange | Index Symbol |
|---|---|
| New York Stock Exchange / NYSE | ^NYA |
| NASDAQ | ^IXIC |
| Tokyo Stock Exchange | N225 |
| Hong Kong Stock Exchange | HSI |
| Shanghai Stock Exchange | 000001.SS |
| London Stock Exchange | ^FTSE |
| Frankfurt Stock Exchange / Deutsche Börse | ^GDAXI |
| Euronext Paris | ^FCHI |
| Toronto Stock Exchange | ^GSPTSE |
| Australian Securities Exchange | ^AXJO |

**Domain notes:**
- "Up day" = Close > Open for that day.
- "Down day" = Close < Open for that day.
- "Average intraday volatility" = mean of (High − Low) / Open across days.
- Region is NOT a column — infer from exchange geography.

---

## 6. crmarenapro

| Database | Type | Key tables |
|---|---|---|
| core_crm | SQLite | User, Account, Contact |
| sales_pipeline | DuckDB | Contract, Lead, Opportunity, OpportunityLineItem, Quote, QuoteLineItem |
| activities | DuckDB | Activity records (calls, tasks, events) |
| product_catalog | SQLite | Product2, PricebookEntry, Pricebook2, ProductCategory, Order, OrderItem |
| territory | SQLite | Territory2, UserTerritory2Association |
| support_tickets | PostgreSQL (crm_support) | Case, CaseHistory__c, Issue__c, LiveChatTranscript |
| email_database | PostgreSQL (crm_support) | EmailMessage — same DB as support_tickets |
| knowledge_base | PostgreSQL (crm_support) | Knowledge__kav — same DB as support_tickets |

**Join key:** `Id` fields link across tables (AccountId, ContactId, OwnerId, OpportunityId, etc.). **WARNING: ~25% of Id-like fields include a leading `#` character** (e.g., `#001Wt00000PFj4zIAD` instead of `001Wt00000PFj4zIAD`). Strip `#` before joining.

**Additional corruption:** ~20% of text fields have trailing whitespace. Strip before comparison. Affected fields: Id, AccountId, ContactId, Name, FirstName, LastName, Email, Subject, Status.

**Domain notes:**
- Opportunity `StageName` values follow Salesforce conventions: Prospecting → Qualification → Needs Analysis → Value Proposition → Id. Decision Makers → Perception Analysis → Proposal/Price Quote → Negotiation/Review → Closed Won / Closed Lost.
- A "won deal" = `StageName = 'Closed Won'`.
- `ContractTerm` is in months.
- Lead `IsConverted = True` means the lead became an Opportunity.

---

## 7. agnews

| Database | Type | Key tables |
|---|---|---|
| articles_db | MongoDB | articles |
| metadata_database | SQLite | authors, article_metadata |

**Join key:** `article_id` (integer) — exact match.

**Primary challenges:** category classification requires NLP on `title` + `description` text (no `category` column in articles). Domain knowledge: there are exactly **4 categories**: World, Sports, Business, Science/Technology.

**Domain notes:**
- Articles do not have a category column — infer from content using LLM.
- Author–article relationship lives in `article_metadata` table.
- Region/publication info is in `article_metadata`.

---

## 8. bookreview

| Database | Type | Key tables |
|---|---|---|
| bookreview_db | PostgreSQL | books_info |
| review_database | SQLite | review |

**Join key:** `book_id` (books_info, PostgreSQL) ↔ `purchase_id` (review, SQLite). Field names differ AND values may require fuzzy matching. Use fuzzy join, not exact equality.

**Primary challenges:** `description`, `categories`, `features` in books_info are stored as string representations of Python lists/dicts — parse with `ast.literal_eval`. `details` field also contains structured data as a string.

**Domain notes:**
- `rating_number` = total count of ratings (not the average rating score).
- `categories` field is stored as string like `"['Books', 'Mystery']"` — requires parsing.

---

## 9. PATENTS

| Database | Type | Key tables |
|---|---|---|
| publication_database | SQLite | publicationinfo |
| patent_CPCDefinition | (PostgreSQL or SQLite — check db_config) | cpc_definition |

**Join key:** `cpc` field in `publicationinfo` (CPC classification codes) ↔ `symbol` in `cpc_definition`. Match code prefix (CPC codes are hierarchical, e.g. "A61K 31/00").

**Primary challenges:** all date fields (`publication_date`, `filing_date`, `grant_date`, `priority_date`) are stored as **natural language strings** (e.g. "March 15th, 2020") — must parse before date arithmetic. `Patents_info` field is a free-text NL summary containing `application_number`, `publication_number`, `assignee_harmonized`, `country_code` — requires extraction.

**Domain notes:**
- `claims_localized_html` and `description_localized_html` are HTML — strip tags before text analysis.
- `pct_number` is only populated for PCT (international) applications.
- `family_id` groups related patents (continuations, divisionals, national phase entries of same PCT).

---

## 10. DEPS_DEV_V1

| Database | Type | Key tables |
|---|---|---|
| package_database | SQLite | packageinfo |
| project_database | (DuckDB or SQLite) | project_packageversion, project_info |

**Join key:** (`System`, `Name`, `Version`) — composite key matching packageinfo ↔ project_packageversion. Then `ProjectName` links project_packageversion ↔ project_info.

**Primary challenges:** `Licenses`, `Links`, `Advisories`, `VersionInfo`, `Hashes`, `Registries`, `UpstreamIdentifiers` are stored as **JSON-like strings** — parse before use. `UpstreamPublishedAt` is a Unix timestamp in milliseconds (divide by 1000 for seconds).

**Domain notes:**
- `System` values: NPM, Maven, PyPI, Go, Cargo, NuGet, etc.
- `Project_Information` in project_info contains GitHub stars, fork count, and description as natural language text — extract with regex or LLM.
- `DependenciesProcessed = False` or `DependencyError = True` means dependency data is unreliable for that package.

---

## 11. GITHUB_REPOS

| Database | Type | Key tables |
|---|---|---|
| metadata_database | SQLite | languages, licenses, repos |
| artifacts_database | DuckDB | contents, commits, files (check actual table names) |

**Join key:** `repo_name` in format `owner/repo` — exact string match across all tables.

**Primary challenges:** `language_description` in languages table is natural language describing multiple languages with byte counts — parse to extract primary language. `repo_data_description` in contents is NL metadata — extract structured attributes.

**Domain notes:**
- Primary language of a repo = language with most bytes (described in `language_description` text).
- `license` values follow SPDX identifiers: `mit`, `apache-2.0`, `gpl-2.0`, etc.

---

## 12. PANCANCER_ATLAS

| Database | Type | Key tables |
|---|---|---|
| pancancer_clinical | PostgreSQL | clinical_info |
| molecular_database | SQLite | Mutation_Data, (RNA expression table — check db_config) |

**Join key:** `Patient_description` in clinical_info (NL field containing patient barcode/UUID) ↔ `ParticipantBarcode` in molecular tables. Extract barcode from `Patient_description` text before joining.

**Primary challenges:** `Patient_description` is NL text — extract `ParticipantBarcode` using regex (format: TCGA-XX-XXXX). clinical_info has 100+ columns.

**Domain notes:**
- Cancer type abbreviations: LGG = Brain Lower Grade Glioma; BRCA = Breast Invasive Carcinoma; GBM = Glioblastoma; LUAD = Lung Adenocarcinoma; LUSC = Lung Squamous Cell Carcinoma.
- Gene expression: use log10(normalised_count + 1) transformation before computing averages.
- Chi-square formula: χ² = Σ (O_ij − E_ij)² / E_ij, where E_ij = (row_total × col_total) / grand_total.
- `Hugo_Symbol` = standard gene name (e.g. TP53, EGFR, CDH1).
- Variant classifications: Missense_Mutation, Nonsense_Mutation, Frame_Shift_Del, Frame_Shift_Ins, Splice_Site, Silent.
