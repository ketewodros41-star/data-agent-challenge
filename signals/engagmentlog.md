# Signal Corps Engagement Log
## PaLM Team — TRP1 FDE Programme, April 2026
## Members: Kidus Tewodros & Mistire Daniel

---

## WEEK 8
### Daily Slack Posts

| Date | Content Summary | Link |
|------|----------------|------|
| Day 1 — Apr 8 | Team role alignment, daily deliverables, infrastructure decision (no tenai), meeting reminder | Internal Slack — PaLM channel |
| Day 2 — Apr 9 | Databricks 2026 State of AI Agents post, Medium article share, progress update | Internal Slack — PaLM channel |
| Day 3 — Apr 10 | OpenAI data agent writeup shared, Karpathy KB method shared, infrastructure update, tutor guidance noted | Internal Slack — PaLM channel |
| Day 4 — Apr 11 | Team progress update to tutor, all roles delivering, interim submission on track | Internal Slack — PaLM channel |

---

**Day 1 Full Post — Kidus (4:05 AM):**
> Our progress so far: Intelligence Officers focused on
LLM Knowledge Base. Drivers leading Inception Document
and architecture. Signal Corps responsible for
documenting progress and community engagement.
Decision: not using Tenai infrastructure for now.
Clear roles. Clear deliverables. Clear mission.

---

**Day 2 Full Posts — Kidus & Mistire:**

> Oracle Forge x Databricks 2026 — Multi-agent systems
grew 327% in 4 months. Companies using evaluation tools
get 6x more AI projects to production. Our harness
isn't overhead — it's the differentiator.
Full report: https://www.databricks.com/resources/ebook/state-of-ai-agents

> Just made this post on Medium — check it out:
https://medium.com/@ktewodros41/were-building-a-data-agent-that-competes-on-a-uc-berkeley-benchmark-937d6370eee4

---

**Day 3 Full Posts — Mistire (2:12 AM & 4:38 AM):**

> OpenAI shared how they built an internal AI data agent
that turns plain English questions into reliable data
insights. Instead of just generating answers, it finds
the right data, runs queries, checks itself, and
explains results. Worth a read:
https://openai.com/index/inside-our-in-house-data-agent

> This is a good breakdown of Karpathy's idea of LLM
knowledge bases. Instead of RAG pipelines, the idea is
to have the LLM compile raw data into a structured,
evolving wiki that it can reason over. Feels very
relevant to what we're building around knowledge bases.
https://academy.dair.ai/blog/llm-knowledge-bases-karpathy

**Day 3 Infrastructure Update — Yosef (4:11 AM):**
> DataAgentBench repo cloned to shared instance with
all databases downloaded. Resolving directory structure
issue — will reference from individual directories
rather than root. Tutor guidance received and noted.

**Day 3 Tutor Guidance — Temesgen (4:25 AM):**
> Each team member clones org repo inside own
/home/<username> directory. Shared Docker setup
on instance — no separate installations needed.
For DAB evaluation, one Driver runs evaluation
testing for optimal resource usage.

---

**Day 4 Full Post — Kidus (Apr 11):**
> The team is progressing well and on track for
Tuesday's interim submission.
> - Estif and Melkam: Knowledge Base first draft
underway, all three context layers mapped,
source materials locked in
> - Yosef and Bethel: Inception document and
architecture diagram completed, infrastructure
setup moving forward over the weekend
> - Kidus and Mistire: External engagement live —
two X threads, Medium article published, Reddit
post at 867 views with community intelligence
on token optimisation feeding directly into
the architecture
>
> All roles are delivering and the team is aligned
heading into the final push before Tuesday.

---

### X / Twitter Threads

#### Thread 1 — Day 3 Team Setup + Oracle Forge Kickoff
- **Date:** April 9, 2026
- **URL:** https://x.com/Kidus5T99409/status/2042344151518232998
- **Views:** 14
- **Topic:** Team setup, roles locked in, 
production-grade data analytics agent kickoff
- **Notable replies received:**

  **@fabiolauria92 — Fabio Lauria:**
  > "The multi-database approach stands out because 
  that's precisely where most analytics solutions 
  fail. How are you managing real-time consistency 
  across different systems?"
  - Views: 14
  - **Our reply:**
  > "We are managing it by: A smart query planner 
  that understands relationships across heterogeneous 
  databases. Dynamic schema awareness + metadata 
  synchronization. Built-in verification & 
  self-correction loops to avoid bad joins or 
  stale assumptions."

---

#### Thread 2 — Mid-Build Engineering Update
- **Date:** April 9, 2026
- **URL:** https://x.com/Kidus5T99409/status/2042344151518232998
- **Views:** 17
- **Topic:** 3-layer context system, token 
optimisation challenge, DAB benchmark submission
- **Key tweets:**
  - 3-layer context: Schema & Metadata → 
  Institutional Knowledge → Corrections Log
  - Token optimisation as hardest unsolved problem
  - DAB: 54 queries across 4 DB systems
  - Harness built before the agent
- **Notable replies received:**

  **@rivestack:**
  > "multi-db joins with mismatched schemas is 
  exactly where things get messy. curious how 
  you're handling schema normalization or just 
  keeping native types per db and letting the 
  agent figure it out?"
  - Views: 7
  
  - **our reply:**
  - url: https://x.com/Kidus5T99409/status/2042897418534924327?s=20
  > "Great question. We're keeping native types 
  per DB and putting the resolution logic in 
  the agent — specifically in Layer 2 of our 
  context stack. We maintain a join key glossary 
  that maps how the same entity appears 
  differently across systems (e.g. integer in 
  PostgreSQL vs "CUST-00123" string in MongoDB). 
  The agent checks this before attempting any 
  cross-database join. Schema normalisation 
  upfront felt too brittle for DAB's realistic 
  enterprise data — the messiness is the point."

---

### Community Participation

#### Entry 1 — Reddit r/learnmachinelearning
- **Date:** April 10, 2026
- **Platform:** r/learnmachinelearning
- **Username:** u/ktewodros41
- **Post title:** "help Curious if anyone here has 
tackled multi-database schema loading strategies"
- **Direct link:** https://www.reddit.com/r/learnmachinelearning/comments/1shx8ag/help_curious_if_anyone_here_has_tackled/
- **Views:** 867
- **Upvotes:** 1
- **Summary of post:**
  Asked the community about multi-database schema 
  loading strategies — whether to load full schemas 
  upfront or retrieve on demand. Shared our DAB 
  context: 4 database systems, 54.3% leaderboard 
  ceiling, Claude Code + OpenAI architecture synthesis, 
  token optimisation challenge.

- **Responses received:**

  **u/Otherwise_Wave9374:**
  > Schema summaries + on-demand expansion: start 
  with table-level stats and exemplar columns, pull 
  full column lists only for candidate tables after 
  first-pass query plan. Log join-key failures into 
  compact "fixup memory" referenced before next 
  tool call.
  - Link shared: agentixlabs.com

  **u/Sufficient_Might_228:**
  > Lazy loading per sub-query works better — loading 
  full schemas upfront creates context bloat. Start 
  with table names only, fetch column details + sample 
  rows for tables LLM actually selects.

  **u/Foreign_Skill_6628:**
  > Schema-as-a-Database approach: load schemas into 
  DuckDB or Neo4j, use semantic search via MCP server 
  tool calls. Load as a skill in Claude — only 
  activates when invoked, saving KB of space. 
  In production would use Databricks/Snowflake 
  instead of multi-database setup.

- **Our replies:**
  - Acknowledged schema summaries + on-demand 
  expansion as most sustainable approach
  - Agreed execution layer intelligence > expecting 
  frontier model to hold entire DB world in context

---

### Community Intelligence Gathered This Week

| Date | Source | Intel | Impact on Team |
|------|--------|-------|----------------|
| Apr 10 | u/Otherwise_Wave9374 — Reddit | Schema summaries + on-demand expansion: table-level stats first, full columns only for candidate tables after query plan | Directly addresses our token optimisation open question — bring to next mob session as proposed solution |
| Apr 10 | u/Sufficient_Might_228 — Reddit | Lazy loading per sub-query: start table names only, fetch details for selected tables only | Validates lazy loading approach over upfront full schema load |
| Apr 10 | u/Foreign_Skill_6628 — Reddit | Schema-as-a-Database: store schemas in DuckDB/Neo4j, semantic search via MCP, load as Claude skill | Novel approach worth documenting in KB — could reduce context footprint significantly |

---

### Articles Published

#### Kidus & Mistire — Medium Article
- **Title:** We're Building a Data Agent That Competes 
on a UC Berkeley Benchmark. Here's What We've Learned 
in Week 1.
- **Platform:** Medium
- **URL:** https://medium.com/@ktewodros41/were-building-a-data-agent-that-competes-on-a-uc-berkeley-benchmark-937d6370eee4
- **Authors:** Kidus & Mistire — Signal Corps, PaLM Team
- **Published:** April 10, 2026
- **Word count:** ~800
- **Topics covered:**
  - What DAB actually tests vs clean benchmarks
  - Our 3-layer context architecture
  - Why we built the harness first
  - Token optimisation as the unsolved problem
  - Current sprint status
- **X thread link:** 
https://x.com/Kidus5T99409/status/2042344151518232998
- **Notable responses:** Pending

---

### Resource Acquisition

| Resource | Applied | Outcome | Notes |
|----------|---------|---------|-------|
| Cloudflare Workers free tier | Day 1 | TBC — update at next mob session | Required for sandbox Option B |

---
### Week 8 Engagement Summary

**Total external posts:** 6
- 2 X threads 
  (Thread 1 — Memory Architecture: 31 views, 
  Thread 2 — Mid-Build Update: 17 views)
- 1 X thread — Day 3 Team Setup: 14 views
- 1 Reddit post (867 views, 3 substantive responses)
- 1 Medium article published
- 2 X replies to external practitioners
  (@fabiolauria92: 14 views, @rivestack: 7 views)

**Total community comments made:** 6
- 2 replies to X practitioners
  (@fabiolauria92, @rivestack)
- 4 replies in Reddit thread
  (u/Otherwise_Wave9374, u/Sufficient_Might_228 x2,
  u/Foreign_Skill_6628)

**Notable responses received:**
- @fabiolauria92 — external practitioner validated
  that multi-database fragmentation is a real
  SME production pain point, asked specifically
  how we handle real-time consistency across systems
- @rivestack — active practitioner asked about
  schema normalisation vs native types per DB —
  directly touching our join key glossary design
  decision — reply pending before Tuesday
- 3 substantive technical responses on Reddit
  addressing our token optimisation open question:
  schema summaries + on-demand expansion,
  lazy loading per sub-query, and
  Schema-as-a-Database via DuckDB/Neo4j

**Community intelligence that changed team's
technical approach:**

1. Token optimisation — RESOLVED via community
   Three independent practitioners converged on
   the same answer: do not load full schemas
   upfront. Load table names first, expand to
   full columns only for tables selected after
   first-pass query planning. Bringing to next
   mob session as proposed architecture decision.

2. Join key glossary — VALIDATED via @rivestack
   External practitioner independently raised
   schema normalisation vs native types as an
   active engineering debate. Our approach —
   keeping native types per DB with a join key
   glossary in Layer 2 — is the right call.
   Flagging to Estif and Melkam for KB v2
   domain layer documentation.

3. Schema-as-a-Database — NEW approach from
   u/Foreign_Skill_6628: store schemas in
   DuckDB/Neo4j, semantic search via MCP,
   load as Claude skill. Worth exploring for
   KB v2 to reduce context footprint.
   Flagging to Intelligence Officers.



## WEEK 9
*(To be updated)*

### Daily Slack Posts
| Date | Content Summary | Link |
|------|----------------|------|
| Day 1 — Apr 14 | | |
| Day 2 — Apr 15 | | |
| Day 3 — Apr 16 | | |
| Day 4 — Apr 17 | | |
| Day 5 — Apr 18 | | |

### X Threads
#### Thread 3 — Benchmark Thread
- Date:
- URL:
- Views:
- Topic:
- Notable responses:

#### Thread 4 — Final Community Thread / DAB PR Post
- Date:
- URL:
- Views:
- Topic:
- Notable responses:

### Articles
#### Mistire — Article
- Title:
- Platform:
- URL:
- Word count:
- X thread link:
- Notable responses:

---

## COMPLETE PORTFOLIO SUMMARY
*(Final — to be completed by April 18)*

| Date | Platform | Type | URL | Metrics |
|------|----------|------|-----|---------|
| Apr 9 | X | Thread 1 — Memory Architecture | https://x.com/Kidus5T99409/status/2042253616287789267 | 31 views |
| Apr 9–10 | X | Thread 2 — Mid-Build Update | https://x.com/Kidus5T99409/status/2042344151518232998 | 17 views |
| Apr 10 | Reddit | Post + replies | https://www.reddit.com/r/learnmachinelearning/comments/1shx8ag/ | 867 views |
| Apr 10 | Medium | Article | https://medium.com/@ktewodros41/were-building-a-data-agent-that-competes-on-a-uc-berkeley-benchmark-937d6370eee4 | TBC |
| Apr 14 | X | Thread 3 — Benchmark | TBC | TBC |
| Apr 16 | Medium/LinkedIn | Mistire Article | TBC | TBC |
| Apr 17 | X | Thread 4 — Results | TBC | TBC |
| Apr 18 | X | DAB PR Announcement | TBC | TBC |