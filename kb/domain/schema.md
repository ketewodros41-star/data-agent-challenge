# DAB Full Schema Reference

Complete field-level schema for all 12 DAB datasets.
Inject this document when the agent needs to know exact column names, types, or table structure.
Each dataset section includes: databases, DB engine, tables/collections, all fields with types and notes.

---

## 1. yelp

### yelp_db — MongoDB

#### Collection: `business`
| Field | Type | Notes |
|---|---|---|
| _id | ObjectId | MongoDB internal |
| business_id | str | Format: `businessid_N` — see join key glossary |
| name | str | Business name |
| review_count | int | Total reviews |
| is_open | int | 1 = open, 0 = closed |
| attributes | dict or null | Nested dict: WiFi, parking, credit cards, etc. Key values are strings e.g. `"True"/"False"/"free"` |
| hours | dict or null | Day name → hours string e.g. `{"Monday": "9:0-22:0"}` |
| description | str | NL text — location (city, state) embedded here |

#### Collection: `checkin`
| Field | Type | Notes |
|---|---|---|
| _id | ObjectId | MongoDB internal |
| business_id | str | Format: `businessid_N` — links to business collection |
| date | list[str] | List of ISO timestamp strings — count length for check-in count |

---

### user_database — DuckDB

#### Table: `review`
| Field | Type | Notes |
|---|---|---|
| review_id | str | Unique |
| user_id | str or null | Links to user table |
| business_ref | str | Format: `businessref_N` — links to MongoDB business_id (see join key glossary) |
| rating | int | 1–5 |
| useful | int | Useful votes received |
| funny | int | Funny votes received |
| cool | int | Cool votes received |
| text | str | Review text |
| date | str | Review date string |

#### Table: `tip`
| Field | Type | Notes |
|---|---|---|
| user_id | str or null | |
| business_ref | str | Format: `businessref_N` |
| text | str | Tip content |
| date | str | |
| compliment_count | int | |

#### Table: `user`
| Field | Type | Notes |
|---|---|---|
| user_id | str | Unique |
| name | str | |
| review_count | int | |
| yelping_since | str | Registration date |
| useful | int | Total useful votes received |
| funny | int | |
| cool | int | |
| elite | str | Comma-separated year strings e.g. `"2015,2016"` — parse by splitting |

---

## 2. googlelocal

### review_database — SQLite

#### Table: `review`
| Field | Type | Notes |
|---|---|---|
| name | str | Reviewer name |
| time | str | Timestamp string |
| rating | int | 1–5 |
| text | str | Review text |
| gmap_id | str | Join key — exact match to googlelocal_db |

---

### googlelocal_db — PostgreSQL

#### Table: `business_description`
| Field | Type | Notes |
|---|---|---|
| name | str | Business name |
| gmap_id | str | Join key — exact match to review_database |
| description | str | NL text — business category and US state embedded here |
| num_of_reviews | int | Total review count |
| hours | list/str | Operating hours — stored as list or string |
| MISC | dict/str | JSON-like dict of amenities (e.g. `{"Service options": {...}}`) |
| state | str | **Operating status**: OPEN, CLOSED, TEMPORARILY_CLOSED — NOT a US geographic state |

---

## 3. music_brainz_20k

### tracks_database — SQLite

#### Table: `tracks`
| Field | Type | Notes |
|---|---|---|
| track_id | int | Join key to sales_database (exact) — but may not be unique per real-world song |
| source_id | int | Source of the record |
| source_track_id | str | Original ID from source — not unique |
| title | str | Track title — use for dedup with fuzzy matching |
| artist | str | Artist name — use for dedup |
| album | str | Album name |
| year | str | Year — format inconsistent (e.g. "2005", "2005-01-01", null) |
| length | str | Track length in seconds or formatted string |
| language | str | Language of the track |

---

### sales_database — DuckDB

#### Table: `sales`
| Field | Type | Notes |
|---|---|---|
| sale_id | int | Unique sale record |
| track_id | int | Links to tracks_database.tracks.track_id |
| country | str | USA / UK / Canada / Germany / France only |
| store | str | iTunes / Spotify / Apple Music / Amazon Music / Google Play only |

---

## 4. stockmarket

### stockinfo_database — SQLite

#### Table: `stockinfo`
| Field | Type | Notes |
|---|---|---|
| Nasdaq Traded | str | "Y"/"N" |
| Symbol | str | Ticker symbol — used as table name in stocktrade_database |
| Listing Exchange | str | A/N/P/Z/V/Q — see domain terms for meaning |
| Market Category | str | Market tier classification |
| ETF | str | "Y" = ETF, "N" = stock |
| Round Lot Size | float | Standard trading unit |
| Test Issue | str | "Y"/"N" |
| Financial Status | str or null | D/E/Q/N/null — see domain terms |
| NextShares | str | |
| Company Description | str | Company name and description text |

---

### stocktrade_database — DuckDB

**One table per ticker symbol. Table name = ticker symbol (e.g. `AAPL`, `MSFT`).**
Query `SHOW TABLES` to enumerate.

#### Per-ticker table schema
| Field | Type | Notes |
|---|---|---|
| Date | str | Trading date |
| Open | float | Opening price |
| High | float | Day high |
| Low | float | Day low |
| Close | float | Closing price |
| Adj Close | float | Adjusted closing price |
| Volume | int | Shares traded |

---

## 5. stockindex

### indexinfo_database — SQLite

#### Table: `index_info`
| Field | Type | Notes |
|---|---|---|
| Exchange | str | Full exchange name e.g. "Tokyo Stock Exchange" |
| Currency | str | Trading currency |

---

### indextrade_database — DuckDB

#### Table: `index_trade`
| Field | Type | Notes |
|---|---|---|
| Index | str | Abbreviated index symbol e.g. "N225", "HSI" — see join key glossary for mapping to Exchange |
| Date | str | Trading date |
| Open | float | |
| High | float | |
| Low | float | |
| Close | float | |
| Adj Close | float | |
| CloseUSD | float | Closing price converted to USD |

---

## 6. crmarenapro (6 databases)

**CRITICAL: All ID fields may have leading `#` and trailing whitespace. Normalise before any join.**

### core_crm — SQLite

#### Table: `User`
| Field | Type | Notes |
|---|---|---|
| Id | str | Primary key — may have `#` prefix |
| FirstName | str | |
| LastName | str | |
| Email | str | |
| Phone | str | |
| Username | str | |
| Alias | str | |
| LanguageLocaleKey | str | |
| EmailEncodingKey | str | |
| TimeZoneSidKey | str | |
| LocaleSidKey | str | |

#### Table: `Account`
| Field | Type | Notes |
|---|---|---|
| Id | str | Primary key — may have `#` prefix |
| Name | str | May have trailing whitespace |
| Phone | str | |
| Industry | str | |
| Description | str | |
| NumberOfEmployees | int | |
| ShippingState | str | US state of account address |

#### Table: `Contact`
| Field | Type | Notes |
|---|---|---|
| Id | str | Primary key |
| FirstName | str | |
| LastName | str | |
| Email | str | |
| AccountId | str | FK to Account.Id — may have `#` prefix |

---

### sales_pipeline — DuckDB

#### Table: `Contract`
| Field | Type | Notes |
|---|---|---|
| Id | str | |
| AccountId | str | FK to Account |
| Status | str | "Draft"/"Activated"/"Expired" |
| StartDate | str | |
| CustomerSignedDate | str | |
| CompanySignedDate | str | |
| Description | str | |
| ContractTerm | int | Duration in months |

#### Table: `Lead`
| Field | Type | Notes |
|---|---|---|
| Id | str | |
| FirstName, LastName | str | |
| Email, Phone | str | |
| Company | str | |
| Status | str | Lead status |
| ConvertedContactId | str | |
| ConvertedAccountId | str | |
| Title | str | |
| CreatedDate | str | |
| ConvertedDate | str | |
| IsConverted | bool | True = lead became Opportunity |
| OwnerId | str | FK to User |

#### Table: `Opportunity`
| Field | Type | Notes |
|---|---|---|
| Id | str | |
| ContractID__c | str | FK to Contract |
| AccountId | str | FK to Account |
| ContactId | str | FK to Contact |
| OwnerId | str | FK to User |
| Probability | float | Win probability % |
| Amount | float | Deal value ("revenue") |
| StageName | str | Pipeline stage — see domain terms |
| Name | str | Opportunity name |
| Description | str | |
| CreatedDate | str | |
| CloseDate | str | Expected close date |

#### Table: `OpportunityLineItem`
| Field | Type | Notes |
|---|---|---|
| Id | str | |
| OpportunityId | str | FK to Opportunity |
| Product2Id | str | FK to Product2 |
| PricebookEntryId | str | |
| Quantity | float | |
| TotalPrice | float | |

#### Table: `Quote`
| Field | Type | Notes |
|---|---|---|
| Id | str | |
| OpportunityId | str | |
| AccountId | str | |
| ContactId | str | |
| Name | str | |
| Description | str | |
| Status | str | |
| CreatedDate | str | |
| ExpirationDate | str | |

#### Table: `QuoteLineItem`
| Field | Type | Notes |
|---|---|---|
| Id | str | |
| QuoteId | str | |
| OpportunityLineItemId | str | |
| Product2Id | str | |
| PricebookEntryId | str | |
| Quantity | float | |
| UnitPrice | float | |
| Discount | float | |
| TotalPrice | float | |

---

### crm_support — PostgreSQL

#### Table: `Case`
| Field | Type | Notes |
|---|---|---|
| id | str | |
| priority | str | |
| subject | str | May have `#` / trailing whitespace |
| description | str | |
| status | str | "Open"/"Closed"/"Resolved"/"Escalated" |
| contactid | str | FK to Contact |
| createddate | str | |
| closeddate | str | |
| orderitemid__c | str | |
| issueid__c | str | FK to issue__c |
| accountid | str | FK to Account |
| ownerid | str | FK to User |

#### Table: `knowledge__kav`
| Field | Type | Notes |
|---|---|---|
| id | str | |
| title | str | |
| faq_answer__c | str | |
| summary | str | |
| urlname | str | |

#### Table: `issue__c`
| Field | Type | Notes |
|---|---|---|
| id | str | |
| name | str | |
| description__c | str | |

#### Table: `casehistory__c`
| Field | Type | Notes |
|---|---|---|
| id | str | |
| caseid__c | str | |
| oldvalue__c | str | |
| newvalue__c | str | |
| createddate | str | |
| field__c | str | |

#### Table: `emailmessage`
| Field | Type | Notes |
|---|---|---|
| id | str | |
| subject | str | |
| textbody | str | Email body text |
| parentid | str | FK to Case |
| fromaddress | str | |
| toids | str | |
| messagedate | str | |
| relatedtoid | str | |

#### Table: `livechattranscript`
| Field | Type | Notes |
|---|---|---|
| id | str | |
| caseid | str | |
| accountid | str | |
| ownerid | str | |
| body | str | Chat transcript text |
| endtime | str | |
| livechatvisitorid | str | |
| contactid | str | |

---

### products_orders — SQLite

#### Table: `ProductCategory`
`Id, Name, CatalogId`

#### Table: `Product2`
`Id, Name, Description, IsActive, External_ID__c`

#### Table: `ProductCategoryProduct`
`Id, ProductCategoryId, ProductId`

#### Table: `Pricebook2`
`Id, Name, Description, IsActive, ValidFrom, ValidTo`

#### Table: `PricebookEntry`
`Id, Pricebook2Id, Product2Id, UnitPrice`

#### Table: `Order`
`Id, AccountId, Status, EffectiveDate, Pricebook2Id, OwnerId`

#### Table: `OrderItem`
`Id, OrderId, Product2Id, Quantity, UnitPrice, PriceBookEntryId`

---

### activities — DuckDB

#### Table: `Event`
`Id, WhatId, OwnerId, StartDateTime, Subject, Description, DurationInMinutes, Location, IsAllDayEvent`

#### Table: `Task`
`Id, WhatId, OwnerId, Priority, Status, ActivityDate, Subject, Description`

#### Table: `VoiceCallTranscript__c`
`Id, OpportunityId__c, LeadId__c, Body__c, CreatedDate, EndTime__c`

---

### territory — SQLite

#### Table: `Territory2`
`Id, Name, Description`

#### Table: `UserTerritory2Association`
`Id, UserId, Territory2Id`

---

## 7. agnews

### articles_db — MongoDB

#### Collection: `articles`
| Field | Type | Notes |
|---|---|---|
| _id | ObjectId | |
| article_id | int | Join key — exact match to metadata_database |
| title | str | Use for category classification |
| description | str | Use for category classification |

---

### metadata_database — SQLite

#### Table: `authors`
| Field | Type | Notes |
|---|---|---|
| author_id | int | |
| name | str | Full author name |

#### Table: `article_metadata`
*(check actual columns with `PRAGMA table_info(article_metadata)` — contains article_id, author_id, region, publication_date at minimum)*

---

## 8. bookreview

### bookreview_db — PostgreSQL

#### Table: `books_info`
| Field | Type | Notes |
|---|---|---|
| title | str | Book title |
| subtitle | str | |
| author | str | Author(s) |
| rating_number | int | **Count** of ratings — NOT average score |
| features | str | Python-repr list/dict string — parse with `ast.literal_eval()` |
| description | str | Python-repr list string — parse with `ast.literal_eval()` |
| price | float | |
| store | str | |
| categories | str | Python-repr list string e.g. `"['Books', 'Mystery']"` — parse before filtering |
| details | str | Python-repr dict string — contains publisher, ISBN, page count, etc. |
| book_id | str | Join key — fuzzy match to review.purchase_id |

---

### review_database — SQLite

#### Table: `review`
| Field | Type | Notes |
|---|---|---|
| purchase_id | str | Join key — fuzzy match to books_info.book_id |
| rating | float | Rating given by reviewer
| title | str |  Review title 
| text | str | text
| review_time | str |  Timestamp when review was posted
| helpful_vote | int |  Number of helpful votes received
| verified_purchase | bool | Whether purchase was verified


---

## 9. PATENTS

### publication_database — SQLite

#### Table: `publicationinfo`
| Field | Type | Notes |
|---|---|---|
| Patents_info | str | NL summary — contains application_number, publication_number, assignee_harmonized, country_code |
| kind_code | str | e.g. "A1" = published application, "B2" = granted patent |
| application_kind | str | e.g. "utility patent application" |
| pct_number | str | PCT number if international application; null otherwise |
| family_id | str | Groups related patents |
| title_localized | str | Patent title |
| abstract_localized | str | Abstract text |
| claims_localized_html | str | HTML — strip tags before NLP |
| description_localized_html | str | HTML — strip tags before NLP |
| publication_date | str | NL date string e.g. "March 15th, 2020" — parse with dateparser |
| filing_date | str | NL date string |
| grant_date | str | NL date string — null if not yet granted |
| priority_date | str | NL date string |
| priority_claim | str | List of priority applications |
| inventor_harmonized | str | Harmonised inventor list |
| examiner | str | Patent examiner(s) |
| cpc | str | CPC classification code(s) — join to patent_CPCDefinition |
| citation | str | Citation list |

---

### patent_CPCDefinition — (PostgreSQL)

#### Table: `cpc_definition`
| Field | Type | Notes |
|---|---|---|
| symbol | str | CPC code e.g. "A61K 31/00" — join key from publicationinfo.cpc |
| titleFull | str | Full human-readable title of the CPC class |
| applicationReferences | str | Informative references to related applications |
| breakdownCode | bool | Indicates whether the symbol is a breakdown code | 
| childGroups | str | JSON-like list of child CPC symbols at the next level | 
| children | str | Additional JSON-like child references |
| dateRevised |str | Revision date (e.g., “January 5th, 2021”) |
| definition | str | Full definition of the CPC symbol |
| glossary | str | Glossary terms and explanations for the symbol |
| informativeReferences | str | Additional informative references | 
| ipcConcordant | str | IPC concordance mapping for the CPC symbol | 
| level | int | Hierarchical level of the CPC symbol (e.g., 1 to 5) | 
| limitingReferences | str | Scope-limiting references | 
| notAllocatable | bool | Indicates whether this symbol can be assigned to a patent.  
| parents | str | JSON-like list of parent CPC symbols in the hierarchy | 
| precedenceLimitingReferences | str | Precedence-limiting references |  
| residualReferences | str | Residual references for related but distinct subject matter | 
| rules | str | Rules for interpreting and applying the CPC symbol.  
| scopeLimitingReferences | str | Scope-limiting references for the symbol |
| status | str | Status of the CPC symbol (e.g., “active”, “deleted”) |
| synonyms | str |  Synonyms for the CPC symbol |  
| titleFull | str | Full descriptive title of the CPC symbol |
| titlePart | str | Ab


---

## 10. DEPS_DEV_V1

### package_database — SQLite

#### Table: `packageinfo`
| Field | Type | Notes |
|---|---|---|
| System | str | NPM / Maven / PyPI / Go / Cargo / NuGet / etc. — part of composite join key |
| Name | str | Package name — part of composite join key |
| Version | str | Version string — part of composite join key |
| Licenses | str | JSON-like array string — parse with `json.loads()` |
| Links | str | JSON-like list of {type, url} objects |
| Advisories | str | JSON-like list — non-empty means has security advisory |
| VersionInfo | str | JSON-like object — `IsRelease` bool, `Ordinal` int |
| Hashes | str | JSON-like list |
| DependenciesProcessed | bool | |
| DependencyError | bool | |
| UpstreamPublishedAt | float | Unix timestamp in **milliseconds** — divide by 1000 |
| Registries | str | JSON-like list |
| SLSAProvenance | float | |
| UpstreamIdentifiers | str | JSON-like list |
| Purl | float | |

---

### project_database — DuckDB

#### Table: `project_packageversion`
| Field | Type | Notes |
|---|---|---|
| System | str | Composite join key ← packageinfo |
| Name | str | Composite join key ← packageinfo |
| Version | str | Composite join key ← packageinfo |
| ProjectType | str | e.g. "GITHUB" |
| ProjectName | str | `owner/repo` format — join key → project_info |
| RelationProvenance | str | |
| RelationType | str | |

#### Table: `project_info`
| Field | Type | Notes |
|---|---|---|
| Project_Information | str | NL text — contains GitHub stars count, fork count, description; extract with regex |
| Licenses | str | JSON-like array |
| Description | str | Project description |
| Homepage | str | URL |
| OSSFuzz | float | |

---

## 11. GITHUB_REPOS

### metadata_database — SQLite

#### Table: `languages`
| Field | Type | Notes |
|---|---|---|
| repo_name | str | `owner/repo` — join key across all tables |
| language_description | str | NL text listing languages with byte counts — extract primary language by highest bytes |

#### Table: `licenses`
| Field | Type | Notes |
|---|---|---|
| repo_name | str | Join key |
| license | str | SPDX identifier: `mit`, `apache-2.0`, `gpl-2.0`, etc. |

#### Table: `repos`
| Field | Type | Notes |
|---|---|---|
| repo_name | str | Join key |
| watch_count | int | GitHub watchers count |

---

### artifacts_database — DuckDB

#### Table: `contents`
| Field | Type | Notes |
|---|---|---|
| id | str | Blob identifier |
| content | str | File content text (may be truncated for large/binary files) |
| sample_repo_name | str | `owner/repo` — join key |
| sample_ref | str | Branch or commit SHA |
| sample_path | str | File path within repo |
| sample_symlink_target | str | Symlink target if applicable |
| repo_data_description | str | NL metadata derived from size, binary, copies, mode fields |

#### Table: `commits`
| Field | Type | Notes |
|---|---|---|
| commit | str | SHA |
| tree | str | Tree SHA |
| parent | str | Parent commit SHA(s) — JSON-like for merge commits |
| author | str | JSON-like {name, email, timestamp} |
| committer | str | JSON-like {name, email, timestamp} |
| subject | str | Commit message subject line |
| message | str | Full commit message |
| trailer | str | JSON-like additional metadata |
| difference | str | JSON-like file changes |
| difference_truncated | bool | |
| repo_name | str | `owner/repo` |
| encoding | str | |

#### Table: `files`
| Field | Type | Notes |
|---|---|---|
| repo_name | str | Join key |
| ref | str | Branch or commit SHA |
| path | str | File path |
| mode | int | File mode |
| id | str | Blob identifier |
| symlink_target | str | |

---

## 12. PANCANCER_ATLAS

### pancancer_clinical — PostgreSQL

#### Table: `clinical_info`
Over 100 columns. Key columns confirmed:

| Field | Type | Notes |
|---|---|---|
| Patient_description | str | NL text — extract ParticipantBarcode with regex `TCGA-[A-Z0-9]{2}-[A-Z0-9]{4}` |
| *(cancer type column)* | str | Contains TCGA cancer type abbreviation (LGG, BRCA, GBM, etc.) — verify column name |
| *(vital_status column)* | str | "Alive"/"Dead" |
| *(survival columns)* | float | Days to death or last follow-up |
| *(gender column)* | str | |

*Run `SELECT column_name FROM information_schema.columns WHERE table_name = 'clinical_info'` to get full column list.*

---

### molecular_database — SQLite

#### Table: `Mutation_Data`
| Field | Type | Notes |
|---|---|---|
| ParticipantBarcode | str | Patient ID — join key to clinical_info (extract from Patient_description) |
| Tumor_SampleBarcode | str | |
| Tumor_AliquotBarcode | str | |
| Normal_SampleBarcode | str | |
| Normal_AliquotBarcode | str | |
| Normal_SampleTypeLetterCode | str | |
| Hugo_Symbol | str | Gene name e.g. TP53, EGFR, CDH1 |
| HGVSp_Short | str | Protein mutation annotation |
| Variant_Classification | str | Missense_Mutation / Nonsense_Mutation / Frame_Shift_Del / Frame_Shift_Ins / Splice_Site / Silent |
| HGVSc | str | Coding DNA mutation annotation |
| CENTERS | str | Sequencing centre |
| FILTER | str | "PASS" = reliable mutation call |

#### Table: `RNASeq_Expression`
| Field | Type | Notes |
|---|---|---|
| ParticipantBarcode | str | Patient ID — join key |
| SampleBarcode | str | |
| AliquotBarcode | str | |
| SampleTypeLetterCode | str | |
| SampleType | str | Sample type description |
| Symbol | str | Gene symbol |
| Entrez | str | Entrez gene ID |
| normalized_count | float | RNA expression — use `log10(normalized_count + 1)` before averaging |

---

## Quick reference: database engine per dataset

| Dataset | DB 1 | DB 2 | DB 3+ |
|---|---|---|---|
| yelp | MongoDB | DuckDB | — |
| googlelocal | SQLite | PostgreSQL | — |
| music_brainz_20k | SQLite | DuckDB | — |
| stockmarket | SQLite | DuckDB | — |
| stockindex | SQLite | DuckDB | — |
| crmarenapro | SQLite (×3) | DuckDB (×2) | PostgreSQL (×1) |
| agnews | MongoDB | SQLite | — |
| bookreview | PostgreSQL | SQLite | — |
| PATENTS | SQLite | PostgreSQL or SQLite | — |
| DEPS_DEV_V1 | SQLite | DuckDB | — |
| GITHUB_REPOS | SQLite | DuckDB | — |
| PANCANCER_ATLAS | PostgreSQL | SQLite | — |

## SQL dialect quick notes

| Engine | Key differences |
|---|---|
| PostgreSQL | Full SQL; `ILIKE` for case-insensitive; `tsvector` for full-text; `json_extract_path` |
| SQLite | No `ILIKE` — use `LOWER(x) LIKE`; no `QUALIFY` clause; limited window functions |
| DuckDB | Full analytical SQL; `QUALIFY` supported; `LIST_AGG`, `STRUCT`; `SHOW TABLES` |
| MongoDB | Use `.find()`, `.aggregate()`; no SQL; `$match`, `$group`, `$lookup`, `$unwind` |
