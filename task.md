# Implementation Plan: Oracle Forge Data Agent

## Overview

This implementation plan creates a production-grade data analytics agent system for the DataAgentBench (DAB) benchmark. The system implements a three-layer context architecture (schema/metadata, institutional knowledge, interaction memory), self-correcting execution engine, and comprehensive evaluation harness. The agent handles PostgreSQL, MongoDB, SQLite, and DuckDB databases, resolves ill-formatted join keys, extracts structured data from unstructured text, and applies domain knowledge to disambiguate business terms.

The implementation follows a 2-week sprint timeline (Week 8-9) with specific milestones: infrastructure setup (Days 1-2), core agent build with 2+ databases (Days 3-5), context engineering depth (Week 9 Days 1-2), adversarial testing (Days 3-4), and final submission (Day 5).

## Tasks

- [ ] 1. Infrastructure and Project Setup
  - Set up project structure with agent/, kb/, tests/, and evaluation/ directories
  - Configure Python environment with dependencies (Hypothesis, pytest, MCP SDK)
  - Create MCP Toolbox configuration (tools.yaml) for 4 database types
  - Set up test databases (PostgreSQL, MongoDB, SQLite, DuckDB) with sample data
  - Configure Tailscale mesh networking and tmux sessions on tenai-infra
  - Initialize git worktrees for experimental branches
  - _Requirements: 9.1, 9.2, 13.1, 13.2_

- [ ] 2. Knowledge Base Foundation (Karpathy Method)
  - [ ] 2.1 Create Knowledge Base directory structure
    - Create kb/architecture/, kb/domain/, kb/evaluation/, kb/corrections/ directories
    - Add CHANGELOG.md to each directory
    - _Requirements: 8.1_
  
  - [ ] 2.2 Implement injection test framework
    - Write injection test runner that loads document into fresh LLM context
    - Implement document verification logic
    - Create test question generator for each document type
    - _Requirements: 2.6, 8.4_
  
  - [ ] 2.3 Create initial domain knowledge documents
    - Write dab_schemas.md documenting DAB dataset schemas (max 400 words)
    - Write join_key_glossary.md with ID format variations across databases
    - Write unstructured_fields.md identifying free-text fields requiring extraction
    - Write business_terms.md with domain terminology definitions
    - Verify each document via injection test
    - _Requirements: 6.1, 6.2, 8.2, 8.7_
  
  - [ ] 2.4 Create architecture knowledge documents
    - Write claude_code_memory.md documenting three-layer memory pattern
    - Write openai_context_layers.md documenting six-layer context design
    - Write tool_scoping.md documenting MCP tool usage patterns
    - Verify each document via injection test
    - _Requirements: 8.6_

- [ ] 3. Context Manager (Three-Layer Architecture)
  - [ ] 3.1 Implement Layer 1: Schema and Metadata
    - Create SchemaInfo, TableSchema, ColumnSchema data models
    - Implement schema introspection for PostgreSQL, MongoDB, SQLite, DuckDB
    - Build schema cache with foreign key relationship tracking
    - Write schema loader that populates Layer 1 at initialization
    - _Requirements: 2.1_
  
  - [ ] 3.2 Implement Layer 2: Institutional Knowledge
    - Create InstitutionalKnowledge, JoinKeyMapping, UnstructuredFieldInfo data models
    - Implement Knowledge Base document loader
    - Build business term resolver
    - Implement join key glossary lookup
    - Create unstructured field inventory accessor
    - _Requirements: 2.2, 4.1, 5.1, 6.1_
  
  - [ ] 3.3 Implement Layer 3: Interaction Memory
    - Create InteractionMemory, CorrectionEntry, QueryPattern data models
    - Implement append-only correction log (event sourcing pattern)
    - Build correction similarity search
    - Implement successful pattern tracker
    - _Requirements: 2.3, 3.6_
  
  - [ ] 3.4 Implement Context Manager orchestration
    - Create ContextManager class coordinating all three layers
    - Implement load_all_layers() for session initialization
    - Implement context update after query execution
    - Build ContextBundle assembly logic
    - _Requirements: 2.4, 2.5_
  
  - [ ]* 3.5 Write property tests for Context Manager
    - **Property 5: Schema Layer Completeness**
    - **Validates: Requirements 2.1**
    - **Property 6: Institutional Knowledge Accessibility**
    - **Validates: Requirements 2.2**
    - **Property 7: Interaction Memory Persistence**
    - **Validates: Requirements 2.3**
    - **Property 8: Context Loading Completeness**
    - **Validates: Requirements 2.4, 6.5**
    - **Property 9: Memory Update After Execution**
    - **Validates: Requirements 2.5, 3.6**
  
  - [ ]* 3.6 Write unit tests for Context Manager
    - Test Layer 1 schema loading for each database type
    - Test Layer 2 business term resolution
    - Test Layer 3 correction logging and retrieval
    - Test context bundle assembly
    - Test edge cases (empty Layer 3, missing schema, invalid KB document)
    - _Requirements: 2.1, 2.2, 2.3_

- [ ] 4. MCP Toolbox Integration
  - [ ] 4.1 Implement MCPToolbox hybrid client
    - Create MCPToolbox class with hybrid routing:
      - PostgreSQL / MongoDB / SQLite → HTTP calls to Google MCP Toolbox binary (localhost:5000)
      - DuckDB → direct duckdb Python driver (not supported by Google MCP Toolbox)
    - Implement call_tool() routing to HTTP or direct driver based on source type
    - Implement verify_connections() — toolbox health check for HTTP sources, direct connect for DuckDB
    - Implement list_tools() calling GET /v1/tools on the running binary
    - DuckDB connection pool (direct driver only)
    - _Requirements: 9.3, 9.4_

  - [ ] 4.2 Configure and verify Google MCP Toolbox binary
    - Download toolbox binary (googleapis/mcp-toolbox, v0.30.0+)
    - Rename mcp/tools,yaml → mcp/tools.yaml (fix filename typo)
    - Verify tools.yaml uses correct Google MCP Toolbox multi-document YAML format (kind: source / kind: tool)
    - Start binary: ./toolbox --config mcp/tools.yaml
    - Verify all non-DuckDB sources accessible: curl http://localhost:5000/v1/tools
    - Add toolbox startup to setup_dab.sh
    - _Requirements: 9.1, 9.2, 9.6_

  - [ ] 4.3 Add toolbox startup to infrastructure
    - Add ./toolbox --config mcp/tools.yaml to setup_dab.sh
    - Document binary download and startup in README
    - Add TOOLBOX_URL env var (default http://localhost:5000) to .env.example
    - _Requirements: 9.1, 9.5_

  - [ ]* 4.4 Write unit tests for MCP Toolbox
    - Test HTTP routing for PostgreSQL / MongoDB / SQLite tools (mock urllib)
    - Test direct duckdb driver for DuckDB tools (mock duckdb.connect)
    - Test verify_connections() for both routing paths
    - Test toolbox binary unreachable returns failure result
    - Test DuckDB connection pooling
    - _Requirements: 9.3, 9.5_

- [-] 5. Query Router (Multi-Database Routing and Decomposition)
  - [ ] 5.1 Implement query analysis
    - Create QueryRouter class
    - Implement entity type extraction from natural language queries
    - Build database matching logic using Layer 1 schema
    - Implement join operation detection
    - _Requirements: 1.1_
  
  - [ ] 5.2 Implement query decomposition
    - Create QueryPlan, SubQuery, JoinOp data models
    - Implement multi-database query decomposition
    - Build execution order determination based on dependencies
    - Create join strategy selector
    - _Requirements: 1.2_
  
  - [ ] 5.3 Implement dialect detection
    - Build dialect mapper (SQL vs MongoDB aggregation)
    - Implement query type classifier
    - Create dialect-specific query templates
    - _Requirements: 1.3_
  
  - [ ]* 5.4 Write property tests for Query Router
    - **Property 1: Query Routing Correctness**
    - **Validates: Requirements 1.1**
    - **Property 2: Multi-Database Query Decomposition**
    - **Validates: Requirements 1.2**
  
  - [ ]* 5.5 Write unit tests for Query Router
    - Test single-database query routing
    - Test multi-database query decomposition
    - Test execution order determination
    - Test join strategy selection
    - Test edge cases (query mentioning unavailable database, ambiguous entity types)
    - _Requirements: 1.1, 1.2_

- [ ] 6. Execution Engine (Query Execution and Result Merging)
  - [ ] 6.1 Implement dialect translation
    - Create ExecutionEngine class
    - Implement SQL dialect translator (PostgreSQL, SQLite, DuckDB variations)
    - Implement MongoDB aggregation pipeline generator
    - Build dialect-specific function mapping (date functions, string operations)
    - _Requirements: 1.3_
  
  - [ ] 6.2 Implement query execution
    - Build query executor using MCP Toolbox
    - Implement result set handling
    - Create execution trace logging
    - Build timeout handling
    - _Requirements: 1.3_
  
  - [ ] 6.3 Implement result merging
    - Create result merger for multi-database queries
    - Implement join operation execution
    - Build data type preservation logic
    - Implement null value handling
    - Create referential integrity violation detection
    - _Requirements: 1.4_
  
  - [ ] 6.4 Implement result validation
    - Create result validator checking format and data types
    - Implement schema conformance checking
    - Build data quality checker (nulls, duplicates, integrity violations)
    - _Requirements: 16.1, 16.2, 16.3_
  
  - [ ] 6.5 Implement format transformation for join keys
    - Create FormatTransform data model
    - Implement transformation functions (integer to string with prefix, string extraction, case normalization)
    - Build transformation applicator
    - Implement referential integrity preservation check
    - _Requirements: 4.3, 4.4, 4.6_
  
  - [ ]* 6.6 Write property tests for Execution Engine
    - **Property 3: Dialect Translation Correctness**
    - **Validates: Requirements 1.3**
    - **Property 4: Result Merging Preserves Data Integrity**
    - **Validates: Requirements 1.4**
    - **Property 17: Format Transformation Support**
    - **Validates: Requirements 4.4**
    - **Property 19: Transformation Referential Integrity**
    - **Validates: Requirements 4.6**
    - **Property 50: Data Type Validation**
    - **Validates: Requirements 16.2**
    - **Property 51: Data Quality Checking**
    - **Validates: Requirements 16.3**
  
  - [ ]* 6.7 Write unit tests for Execution Engine
    - Test dialect translation for each database type
    - Test result merging with various join types
    - Test format transformation for join keys
    - Test result validation
    - Test edge cases (empty results, null values, type mismatches)
    - _Requirements: 1.3, 1.4, 4.3, 16.1_

- [ ] 7. Checkpoint - Core Agent Functional
  - Ensure all tests pass for Context Manager, MCP Toolbox, Query Router, and Execution Engine
  - Verify agent can execute single-database queries against PostgreSQL and MongoDB
  - Test multi-database query decomposition and execution
  - Ask the user if questions arise

- [ ] 8. Self-Correction Loop (Failure Detection and Recovery)
  - [ ] 8.1 Implement failure detection
    - Create SelfCorrectionLoop class
    - Implement error capture from query execution
    - Build failure type classifier (syntax, join key mismatch, wrong DB type, data quality, extraction failure)
    - Create FailureInfo data model
    - _Requirements: 3.1, 3.2_
  
  - [ ] 8.2 Implement failure diagnosis
    - Build root cause analyzer
    - Implement error message pattern matching
    - Create Layer 3 similarity search for past failures
    - Build Layer 2 join key glossary consultation
    - Create Diagnosis data model
    - _Requirements: 3.2, 3.3_
  
  - [ ] 8.3 Implement correction strategies
    - Create CorrectionStrategy data model
    - Implement query regeneration for syntax errors
    - Implement format transformation for join key mismatches
    - Implement database re-routing for wrong DB type
    - Implement data quality rule application
    - Implement alternative extraction method selection
    - _Requirements: 3.3, 3.4, 4.3_
  
  - [ ] 8.4 Implement retry logic
    - Build retry orchestrator with max 3 attempts
    - Implement correction application
    - Create transparent error recovery (no user-visible errors on success)
    - Build structured error generation after retry exhaustion
    - Implement correction logging to Layer 3
    - _Requirements: 3.5, 3.6, 3.7_
  
  - [ ]* 8.5 Write property tests for Self-Correction Loop
    - **Property 10: Error Capture Completeness**
    - **Validates: Requirements 3.1**
    - **Property 11: Failure Diagnosis Coverage**
    - **Validates: Requirements 3.2**
    - **Property 12: Join Key Format Resolution**
    - **Validates: Requirements 3.3, 4.3**
    - **Property 13: Query Regeneration on Syntax Error**
    - **Validates: Requirements 3.4**
    - **Property 14: Transparent Error Recovery**
    - **Validates: Requirements 3.5**
    - **Property 15: Structured Error After Retry Exhaustion**
    - **Validates: Requirements 3.7**
    - **Property 18: Join Failure Learning**
    - **Validates: Requirements 4.5**
  
  - [ ]* 8.6 Write unit tests for Self-Correction Loop
    - Test failure detection for each error category
    - Test diagnosis logic
    - Test correction strategy generation
    - Test retry logic with various failure scenarios
    - Test correction logging to Layer 3
    - Test edge cases (max retries exceeded, ambiguous errors)
    - _Requirements: 3.1, 3.2, 3.3, 3.6_

- [ ] 9. Sandbox (Isolated Code Execution)
  - [ ] 9.1 Implement sandbox environment
    - Create Sandbox class
    - Implement code validation checking for prohibited operations
    - Build Docker container configuration for local deployment
    - Implement resource limit enforcement (execution time, memory, network)
    - Create SandboxResult data model
    - _Requirements: 10.1, 10.3, 10.4_
  
  - [ ] 9.2 Implement code execution
    - Build code executor with timeout handling
    - Implement execution trace logging
    - Create structured error generation
    - Build result extraction and validation
    - _Requirements: 10.2, 10.6_
  
  - [ ] 9.3 Implement unstructured text extraction
    - Create extraction method library (sentiment, entity, keyword count, date extraction)
    - Implement extraction code generator
    - Build extraction result validator
    - Integrate with Document Intelligence Refinery pipeline (Week 3)
    - _Requirements: 5.2, 5.3, 5.4_
  
  - [ ]* 9.4 Write property tests for Sandbox
    - **Property 36: Sandbox Execution Routing**
    - **Validates: Requirements 10.1**
    - **Property 37: Sandbox Result Structure**
    - **Validates: Requirements 10.2**
    - **Property 38: Sandbox Resource Limit Enforcement**
    - **Validates: Requirements 10.3**
    - **Property 39: Sandbox Code Validation**
    - **Validates: Requirements 10.4**
    - **Property 40: Sandbox Error Structure**
    - **Validates: Requirements 10.6**
  
  - [ ]* 9.5 Write unit tests for Sandbox
    - Test code validation with prohibited operations
    - Test resource limit enforcement
    - Test extraction methods
    - Test error handling
    - Test edge cases (timeout, memory limit, invalid code)
    - _Requirements: 10.1, 10.3, 10.4_

- [ ] 10. Oracle Forge Agent (Primary Orchestrator)
  - [ ] 10.1 Implement agent core
    - Create OracleForgeAgent class
    - Implement process_query() accepting DAB format
    - Build component orchestration (Context Manager, Query Router, Execution Engine)
    - Implement session state management
    - Create QueryResult data model
    - _Requirements: 11.1_
  
  - [ ] 10.2 Implement answer generation
    - Build answer synthesizer from query results
    - Implement confidence score calculation
    - Create query trace assembly
    - Build DAB result format generator
    - _Requirements: 11.2, 16.5_
  
  - [ ] 10.3 Implement multi-turn interaction
    - Build session context loading
    - Implement interaction memory updates
    - Create user correction handler
    - _Requirements: 2.4, 2.5_
  
  - [ ]* 10.4 Write property tests for Oracle Forge Agent
    - **Property 41: DAB Query Format Acceptance**
    - **Validates: Requirements 11.1**
    - **Property 42: DAB Result Format Compliance**
    - **Validates: Requirements 11.2**
    - **Property 53: Confidence Score Inclusion**
    - **Validates: Requirements 16.5**
  
  - [ ]* 10.5 Write unit tests for Oracle Forge Agent
    - Test query processing end-to-end
    - Test answer generation
    - Test confidence score calculation
    - Test session management
    - Test edge cases (invalid query format, empty results)
    - _Requirements: 11.1, 11.2_

- [ ] 11. Evaluation Harness (Tracing and Scoring)
  - [ ] 11.1 Implement tool call tracing
    - Create EvaluationHarness class
    - Implement ToolCallEvent, QueryEvent data models (event sourcing pattern)
    - Build tool call tracer with timestamp, parameters, results
    - Implement execution time tracking
    - _Requirements: 7.1_
  
  - [ ] 11.2 Implement query outcome recording
    - Build outcome recorder comparing against ground truth
    - Implement Levenshtein distance fuzzy matching
    - Create outcome validator
    - _Requirements: 7.2, 16.6_
  
  - [ ] 11.3 Implement scoring
    - Build Pass@1 score calculator
    - Implement score log generator
    - Create category-level improvement tracker
    - Build score progression logger
    - _Requirements: 7.3, 7.6, 15.2, 15.3, 15.5_
  
  - [ ] 11.4 Implement regression testing
    - Build regression suite runner
    - Implement regression detector comparing baseline vs current
    - Create RegressionResult data model
    - Build held-out test set manager
    - _Requirements: 7.7, 15.1_
  
  - [ ] 11.5 Implement trace parsing and formatting
    - Build trace parser producing structured format
    - Implement pretty printer with indentation and syntax highlighting
    - Create JSON export functionality
    - Implement error extraction from traces
    - _Requirements: 17.1, 17.3, 17.5, 17.6_
  
  - [ ] 11.6 Implement DAB results export
    - Create DAB submission schema generator
    - Build results JSON exporter
    - Implement trial aggregation (5 trials per query)
    - _Requirements: 11.4_
  
  - [ ]* 11.7 Write property tests for Evaluation Harness
    - **Property 25: Tool Call Tracing Completeness**
    - **Validates: Requirements 7.1**
    - **Property 26: Query Outcome Recording**
    - **Validates: Requirements 7.2**
    - **Property 27: Pass@1 Score Calculation**
    - **Validates: Requirements 7.3**
    - **Property 28: Event Sourcing Trace Format**
    - **Validates: Requirements 7.4**
    - **Property 29: Result Validation Before Return**
    - **Validates: Requirements 7.5, 16.1**
    - **Property 30: Score Log Maintenance**
    - **Validates: Requirements 7.6, 15.2**
    - **Property 31: Regression Testing Support**
    - **Validates: Requirements 7.7**
    - **Property 54: Levenshtein Distance Comparison**
    - **Validates: Requirements 16.6**
    - **Property 55: Trace Parsing Completeness**
    - **Validates: Requirements 17.1**
    - **Property 56: Pretty Printer Readability**
    - **Validates: Requirements 17.3**
    - **Property 57: Trace Round-Trip Preservation**
    - **Validates: Requirements 17.4**
    - **Property 58: Error Extraction from Traces**
    - **Validates: Requirements 17.5**
    - **Property 59: Trace JSON Export**
    - **Validates: Requirements 17.6**
  
  - [ ]* 11.8 Write unit tests for Evaluation Harness
    - Test tool call tracing
    - Test outcome recording
    - Test Pass@1 calculation
    - Test trace parsing and formatting
    - Test DAB results export
    - Test edge cases (empty traces, malformed results)
    - _Requirements: 7.1, 7.2, 7.3, 17.1_

- [ ] 12. Checkpoint - Full System Integration
  - Ensure all tests pass for all components
  - Verify agent can execute multi-database queries with self-correction
  - Test end-to-end query processing with tracing
  - Verify DAB format compliance
  - Ask the user if questions arise

- [ ] 13. Adversarial Testing and Improvement
  - [ ] 13.1 Create adversarial probe library
    - Create AdversarialProbe data model
    - Write minimum 15 probes across 3+ failure categories
    - Document probes: query text, failure category, expected failure mode
    - Cover categories: multi-DB routing, join key mismatch, text extraction, domain knowledge
    - _Requirements: 12.1, 12.2, 12.3_
  
  - [ ] 13.2 Execute adversarial probes
    - Run all probes against agent
    - Document observed failures
    - Identify root causes
    - _Requirements: 12.3_
  
  - [ ] 13.3 Implement fixes for probe failures
    - Apply fixes to agent components
    - Update Knowledge Base with corrections
    - Document fixes in probe library
    - _Requirements: 12.4_
  
  - [ ] 13.4 Verify improvements
    - Re-run probes after fixes
    - Measure post-fix scores
    - Track improvement in probe library
    - Run regression suite to ensure no regressions
    - _Requirements: 12.5, 12.6_
  
  - [ ]* 13.5 Write property tests for adversarial probes
    - **Property 44: Adversarial Probe Documentation Completeness**
    - **Validates: Requirements 12.3**
    - **Property 45: Probe Score Tracking**
    - **Validates: Requirements 12.5**
    - **Property 46: Probe Library Regression Execution**
    - **Validates: Requirements 12.6**

- [ ] 14. Knowledge Base Refinement
  - [ ] 14.1 Expand domain knowledge
    - Add corrections from adversarial probe failures to corrections log
    - Expand join key glossary with discovered format patterns
    - Update unstructured field inventory with extraction methods
    - Add business term definitions discovered during testing
    - _Requirements: 8.8, 15.4_
  
  - [ ] 14.2 Verify all KB documents
    - Run injection tests on all documents
    - Remove or revise documents failing injection tests
    - Update CHANGELOG.md in each directory
    - _Requirements: 8.3, 8.4_
  
  - [ ] 14.3 Measure KB impact
    - Run evaluation harness before and after KB updates
    - Verify changed agent behavior on repeated queries
    - Document improvement in score log
    - _Requirements: 15.4, 15.5_
  
  - [ ]* 14.4 Write property tests for Knowledge Base
    - **Property 32: Document Word Limit Compliance**
    - **Validates: Requirements 8.2**
    - **Property 33: Correction Log Format Compliance**
    - **Validates: Requirements 8.8**
    - **Property 48: Correction Behavioral Impact**
    - **Validates: Requirements 15.4**

- [ ] 15. DAB Benchmark Execution
  - [ ] 15.1 Prepare DAB dataset
    - Download official DAB datasets (54 queries, 12 datasets)
    - Load datasets into test databases
    - Verify ground truth results
    - _Requirements: 11.3_
  
  - [ ] 15.2 Execute baseline run
    - Run agent against all 54 DAB queries (1 trial each)
    - Record baseline Pass@1 score
    - Generate baseline score log entry
    - _Requirements: 15.1_
  
  - [ ] 15.3 Execute full benchmark
    - Run agent against all 54 DAB queries (5 trials each)
    - Record all tool calls and execution times
    - Generate comprehensive trace logs
    - Calculate final Pass@1 score
    - _Requirements: 11.3, 11.5_
  
  - [ ] 15.4 Analyze results
    - Identify queries with low success rates
    - Categorize failures by type
    - Document improvement from baseline to final
    - _Requirements: 15.3, 15.5_
  
  - [ ] 15.5 Generate DAB submission
    - Export results in DAB JSON format
    - Create AGENT.md documenting architecture
    - Document key design decisions, what worked, what didn't
    - _Requirements: 11.4, 20.2, 20.3_

- [ ] 16. Shared Utility Library
  - [ ] 16.1 Create utility modules
    - Implement multi-pass retrieval module
    - Implement schema introspection module
    - Implement join key resolution module
    - _Requirements: 19.1, 19.2_
  
  - [ ] 16.2 Document utility modules
    - Write function documentation for each module
    - Create usage examples
    - Write test cases
    - Document in Knowledge Base
    - _Requirements: 19.3, 19.5_
  
  - [ ]* 16.3 Write property tests for utility modules
    - **Property 60: Utility Module Documentation Completeness**
    - **Validates: Requirements 19.3**
    - **Property 61: Utility Module Knowledge Base Documentation**
    - **Validates: Requirements 19.5**
  
  - [ ]* 16.4 Write unit tests for utility modules
    - Test multi-pass retrieval
    - Test schema introspection
    - Test join key resolution
    - _Requirements: 19.4_

- [ ] 17. Deployment and Infrastructure
  - [ ] 17.1 Deploy to tenai-infra
    - Set up agent on shared server
    - Configure Tailscale mesh networking
    - Create tmux sessions for team access
    - Set up Gemini CLI conductor
    - _Requirements: 13.1, 13.2, 13.3, 13.5_
  
  - [ ] 17.2 Configure sandbox deployment
    - Choose deployment option (local Docker or Cloudflare Workers)
    - Deploy sandbox environment
    - Verify resource limits and security constraints
    - _Requirements: 10.5_
  
  - [ ] 17.3 Set up continuous testing
    - Configure pre-commit hooks for unit tests
    - Set up CI/CD pipeline for full test suite
    - Configure nightly builds for extended testing
    - _Requirements: Testing Strategy_

- [ ] 18. AI-DLC Documentation
  - [ ] 18.1 Create Inception document
    - Write press release paragraph
    - Write honest FAQ
    - Document key decisions
    - Define definition of done
    - _Requirements: 14.2_
  
  - [ ] 18.2 Create Operations document
    - Document what was built
    - Document what changed from plan
    - Include harness scores (baseline and final)
    - Plan next sprint
    - _Requirements: 14.6_
  
  - [ ] 18.3 Record phase gate approvals
    - Document Inception approval with date and approvers
    - Document Construction completion
    - Record hardest questions asked
    - _Requirements: 14.7_

- [ ] 19. External Engagement (Signal Corps)
  - [ ] 19.1 Create community participation log
    - Set up log documenting all external engagements
    - Track X posts, LinkedIn articles, community responses
    - _Requirements: 18.3_
  
  - [ ] 19.2 Post technical content
    - Post 2+ technical threads per week on X
    - Publish 1+ substantive article per Signal Corps member (600+ words)
    - Engage with data agent and Claude Code architecture discussions
    - _Requirements: 18.1, 18.2_
  
  - [ ] 19.3 Announce DAB submission
    - Post about benchmark submission on X
    - Link to repository and results
    - Share key findings and architecture insights
    - _Requirements: 18.4, 20.6_
  
  - [ ] 19.4 Maintain internal communication
    - Post daily Slack updates: what shipped, what is stuck, what is next
    - Report community intelligence at weekly mob sessions
    - _Requirements: 18.5, 18.6_

- [ ] 20. Final Submission
  - [ ] 20.1 Prepare submission materials
    - Finalize results JSON with all 54 queries and 5 trials each
    - Complete AGENT.md with architecture overview
    - Verify DAB submission schema compliance
    - _Requirements: 20.1, 20.2_
  
  - [ ] 20.2 Submit to DataAgentBench
    - Create GitHub pull request to ucbepic/DataAgentBench
    - Use title format: "[Team Name] — TRP1 FDE Programme, April 2026"
    - Include Pass@1 score, trial count, and architecture summary in description
    - _Requirements: 20.1, 20.4, 20.5_
  
  - [ ] 20.3 Final verification
    - Verify all definition-of-done items are complete
    - Run final regression suite
    - Confirm measurable improvement from baseline
    - _Requirements: 14.5, 15.6_

- [ ] 21. Final Checkpoint - Submission Complete
  - Ensure all tests pass
  - Verify DAB submission is accepted
  - Confirm all deliverables are complete
  - Document lessons learned
  - Ask the user if questions arise

## Notes

- Tasks marked with `*` are optional testing tasks and can be skipped for faster MVP
- Each task references specific requirements for traceability
- Checkpoints ensure incremental validation at major milestones
- Property tests validate universal correctness properties from the design document
- Unit tests validate specific examples and edge cases
- The implementation follows a 2-week sprint timeline with specific milestones
- Week 8 focus: Infrastructure, core agent, 2+ database types working
- Week 9 focus: Context engineering depth, adversarial testing, submission
- All components integrate via MCP Toolbox for standardized database access
- Knowledge Base follows Karpathy method with injection tests and 400-word limit
- Evaluation harness uses event sourcing pattern from Week 5 Ledger system
- Self-correction loop implements transparent error recovery with max 3 retries
- Adversarial probes systematically expose and fix failure modes
- Final submission includes results JSON, AGENT.md, and GitHub PR to DAB repository