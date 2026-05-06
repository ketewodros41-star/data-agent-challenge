# Knowledge Base (KB)

This directory contains all knowledge and documentation that the agent uses to answer questions effectively.

## Directory Structure

### `domain/` - Domain Knowledge
- **`dataset_overview.md`** - Overview of all datasets and their characteristics
- **`schema.md`** - Database schemas and table relationships
- **`join_key_glossary.md`** - How to join data across different databases
- **`domain_term_definitions.md`** - Definitions of domain-specific terms
- **`sql_query_conventions.md`** - SQL patterns and conventions for each database type
- **`unstructured_field_inventory.md`** - How to handle text and unstructured data

### `architecture/` - System Architecture
- **`context_layer.md`** - How context layers work in the agent
- **`memory_system.md`** - Memory and context management
- **`tool_scoping.md`** - How tools are selected and used
- **`self_correcting_execution.md`** - Error handling and self-correction

### `evaluation/` - Evaluation Methodology
- **`dab_format.md`** - Data Agent Benchmark format requirements
- **`failure_categories.md`** - Types of failures and how to categorize them
- **`scoring_method.md`** - How performance is scored and evaluated

### `agent/` - Agent Behavior
- **`AGENT.md`** - Main agent behavior guidelines
- **Domain knowledge files** - Specific knowledge about datasets and domains

## How the Agent Uses This Knowledge

1. **Context Manager** loads relevant KB files based on the dataset
2. **Layer 1**: Schema and basic database information
3. **Layer 2**: Domain knowledge and query patterns
4. **Layer 3**: On-demand docs triggered by question keywords
5. **Layer 4**: Similar corrections from previous runs

## Adding New Knowledge

### For New Datasets
1. Add dataset overview to `domain/dataset_overview.md`
2. Create schema documentation in `domain/schema.md`
3. Add join key information to `domain/join_key_glossary.md`
4. Define domain-specific terms in `domain/domain_term_definitions.md`

### For New Query Patterns
1. Add SQL conventions to `domain/sql_query_conventions.md`
2. Document unstructured field handling in `domain/unstructured_field_inventory.md`
3. Update agent behavior guidelines in `agent/AGENT.md`

## Knowledge Loading Process

The agent loads knowledge in layers:
- **Static loading** at startup from core files
- **Dynamic loading** based on dataset and question keywords
- **Correction learning** from previous failures and successes

## Best Practices

- Keep descriptions concise but comprehensive
- Use examples to illustrate complex concepts
- Cross-reference related concepts across files
- Update knowledge when databases or schemas change
- Test knowledge changes with relevant queries

## File Naming Conventions

- Use lowercase with underscores: `dataset_overview.md`
- Be descriptive: `sql_query_conventions.md` not `sql.md`
- Group related concepts: `domain/`, `architecture/`, `evaluation/`
