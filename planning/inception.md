# **AI-DLC Inception Document**

**Sprint:** Oracle Forge

**Team:** PaLM  
**Product:** DAB multi-database data agent

## **Press release**

Team Palm has built a benchmark-ready data agent for DataAgentBench that answers realistic enterprise-style data questions across multiple database systems, beginning with PostgreSQL and extending to SQLite, MongoDB, and DuckDB through MCP Toolbox. The agent uses three context layers: schema and metadata knowledge, domain and institutional knowledge, and interaction memory from corrections—to improve query planning, recover from execution failures, and return answers with query traces and confidence. This matters because DAB tests the hard parts of production data work: multi-database routing, ill-formatted join keys, unstructured text extraction, and domain ambiguity, and our agent is designed to handle those conditions in a measurable, reproducible way. By the end of the sprint, the team can demonstrate a live agent on the shared server, show how context and correction improve answers, produce benchmark results with query traces, and package the work in a form another engineer can inspect, rerun, and understand.

## **Honest FAQ  user**

### **Q1. What does this agent do?** It answers DAB benchmark questions by selecting the right databases, generating and executing queries, combining results across systems when needed, and returning an answer with a trace of how it got there.

### **Q2. What kinds of questions can it answer?** It is designed for enterprise-style analytics questions that may require joining data across PostgreSQL, SQLite, MongoDB, and DuckDB, resolving mismatched IDs, extracting facts from text fields, and applying domain definitions from the Knowledge Base.

### **Q3. What can it not do yet?** It does not guarantee perfect performance on all 54 DAB queries at the start of the sprint, and early versions may support only two database types before the full four-database setup is complete. It may also fail on queries that require missing domain definitions or unimplemented repair logic until those are added through the corrections loop.

## **Honest FAQ — technical**

### **Q1. What could go wrong?** The biggest risks are failed database setup, incorrect MCP tool configuration, brittle query execution across heterogeneous databases, and false confidence from local fixes that are not validated by the harness or regression suite.

### **Q2. What is the hardest technical problem in this sprint?** The hardest problem is not raw query generation; it is building a self-correcting system that can identify whether a failure comes from wrong routing, wrong join-key format, missing context, bad text transformation, or database-specific execution issues, then recover in a measurable way.

### **Q3. What dependencies does this sprint rely on?** This sprint depends on DAB datasets loading successfully, MCP Toolbox exposing the required database tools, a functioning sandbox for code execution, model/API access for repeated evaluation runs, and a maintained Knowledge Base that is injection-tested before use.

## **Key decisions**

### **Decision 1** — Build thin end-to-end before broad feature expansion

**Chosen option:** Establish a narrow but complete path from question → tool use → execution → result → trace before optimizing breadth.   
**Reason:** End-to-end visibility reveals integration failures earlier than wide but incomplete parallel development.The challenge submission requires our own project structure with `agent/`, `kb/`, `eval/`, `probes/`, `planning/`, `utils/`, `signal/`, and `results/`, while DAB is used as the benchmark dependency and external submission target.

### **Decision 2** — Treat evidence as part of the product

**Chosen option:** Build the evaluation harness and trace logging: logs, traceability, failure capture, and score tracking from the beginning, not after the agent works.  
**Reason:** The challenge evaluates engineering discipline and measurable improvement, not just apparent functionality. The sprint requires measurable improvement, regression detection, and benchmark-quality evidence, so traces and scoring must exist before optimization begins.

### **Decision 3** — Keep context engineering explicit

**Chosen option:** Implement context in named layers rather than implicit prompt sprawl. **Reason:** The challenge specifically values schema context, domain knowledge, and correction memory as real system capabilities.

### **Decision 4** — Use MCP Toolbox as the primary database access layer

**Chosen option:** All database execution goes through MCP tools defined in \`tools.yaml\`, not database-specific drivers inside the agent.  
**Reason**:This standardizes access across PostgreSQL, MongoDB, SQLite, and DuckDB and keeps the execution layer cleaner.

## **Definition of done**

1. **AI-DLC gate discipline is followed.** The team has reviewed this Inception in a mob session, asked hard questions, and recorded approval before Construction began.  
2. **Shared infrastructure is usable.** Team Palm’s shared working environment is available to the team, including the agreed infrastructure and collaborative session workflow.  
3. **DataAgentBench is installed and the first PostgreSQL dataset is loaded**, and the Yelp validation query runs successfully through the provided benchmark setup.  
4. **MCP Toolbox is configured and exposes working tools** for at least PostgreSQL and one additional DAB database type, with tools defined through `tools.yaml`.  
5. **A first working agent runs on the team server** and accepts `{question, available_databases, schema_info}` and returns `{answer, query_trace, confidence}` on at least one DAB query path.  
6. **All three context layers are implemented**: schema/metadata knowledge, domain/institutional knowledge, and corrections memory, with KB v1, v2, and v3 committed in the required structure.  
7. **The evaluation harness records full traces and computes pass@1**, using a held-out test set and a score log with at least two data points showing baseline and later performance.  
8. **The adversarial probe library contains at least 15 probes across at least 3 DAB failure categories**, and each probe records the observed failure and the fix that worked.  
9. **Corrections loop is active.** Observed failures are recorded in structured form and are used to improve later behavior.  
10. **Repository is reproducible and legible.** Another engineer can inspect the repo, understand the architecture, and follow the documented setup path.  
11. **Benchmark submission artifacts exist.** The team produces benchmark result artifacts and the required architecture/agent description for submission.

## Approval Record

### Mob Session Approval

- **Date: 2026-04-13**  
- **Attendees:**   
  1. Bethel Yohannes  
  2. Estifanos Teklay  
  3. Kidus Tewodros  
  4. Melkam Berhane  
  5.  Mistire Daniel  
  6. Yosef Zewdu  
- **Hardest question asked:** How do we use the MCP Toolbox, and how is the sandbox used within the system?  
- **Answer:** The Google MCP Toolbox allows the agent to discover and access multiple databases (PostgreSQL, MongoDB, and SQLite) as standardized tools—while using a custom wrapper for DuckDB whereas the sandbox executes data transformation code outside the LLM context against the databases, runs validation, and returns structured results.  
- **Decision:** Approved 
