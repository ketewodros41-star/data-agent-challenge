import { MongoClient } from 'mongodb';
import pg from 'pg';

const { Client: PgClient } = pg;
const DB_TIMEOUT_MS = 10000;

/**
 * Oracle Forge — Code Execution Sandbox
 *
 * Cloudflare Worker that validates and executes code plans sent by the data agent.
 *
 * Endpoints:
 *   GET  /health   → service liveness check
 *   POST /execute  → validate + execute code, return structured result
 *   POST /validate → syntax-only check, no execution
 *
 * Request shape for /execute:
 *   {
 *     code_plan: string, // JSON-encoded structured operation for transform/extract/merge/validate
 *     trace_id: string,
 *     inputs_payload?: object,
 *     db_type?: string,
 *     context?: object,
 *     step_id?: string
 *   }
 *
 * Response shape for /execute:
 *   { result, trace, validation_status, error_if_any }
 *
 * validation_status values:
 *   PASSED | REJECTED | SYNTAX_ERROR | RUNTIME_ERROR | ERROR
 */

export default {
  async fetch(request, env, ctx) {
    // CORS preflight
    if (request.method === 'OPTIONS') {
      return new Response(null, { status: 204, headers: corsHeaders() });
    }

    const url = new URL(request.url);

    try {
      let response;

      if (url.pathname === '/health' && request.method === 'GET') {
        response = Response.json({
          status: 'ok',
          service: 'oracle-forge-sandbox',
          version: '1.0.0',
          timestamp: new Date().toISOString(),
        });
      } else if (url.pathname === '/execute' && request.method === 'POST') {
        response = await handleExecute(request, env);
      } else if (url.pathname === '/validate' && request.method === 'POST') {
        response = await handleValidate(request, env);
      } else {
        response = Response.json({ error: 'Not found' }, { status: 404 });
      }

      // Attach CORS headers to every response
      const headers = new Headers(response.headers);
      Object.entries(corsHeaders()).forEach(([k, v]) => headers.set(k, v));
      return new Response(response.body, { status: response.status, headers });
    } catch (err) {
      return Response.json(
        { error: 'Internal server error', detail: err.message },
        { status: 500, headers: corsHeaders() }
      );
    }
  },
};

// ---------------------------------------------------------------------------
// POST /execute
// ---------------------------------------------------------------------------
// Body: {
//   code_plan:      string   — structured JSON operation or SQL/MongoDB query
//   trace_id:       string   — correlation id
//   inputs_payload: object   — optional explicit step inputs
//   db_type:        string   — "javascript" | "transform" | "extract" |
//                              "merge" | "validate" | "sql_pg" |
//                              "sql_sqlite" | "sql_duckdb" | "mongodb"
//   context:        object   — optional shared runtime context
//   step_id:        string   — optional step id
// }
async function handleExecute(request, env) {
  let body;
  try {
    body = await request.json();
  } catch {
    return Response.json(
      { result: null, trace: [], validation_status: 'ERROR', error_if_any: 'Invalid JSON body' },
      { status: 400 }
    );
  }

  const {
    code_plan,
    trace_id,
    inputs_payload = {},
    db_type = 'javascript',
    context = {},
    step_id,
  } = body;

  if (!code_plan || typeof code_plan !== 'string') {
    return Response.json({
      result: null,
      trace: [],
      validation_status: 'ERROR',
      error_if_any: 'Missing required field: code_plan (string)',
    }, { status: 400 });
  }

  const trace = [];
  const t0 = Date.now();
  const addTrace = (step, detail = null) =>
    trace.push({ step, ms: Date.now() - t0, ...(detail && { detail }) });

  // ── Step 1: safety check ────────────────────────────────────────────────
  const safety = validateSafety(code_plan, db_type);
  addTrace('SAFETY_CHECK', { passed: safety.safe, trace_id, step_id });

  if (!safety.safe) {
    return Response.json({
      result: null,
      trace,
      validation_status: 'REJECTED',
      error_if_any: safety.reason,
    });
  }

  // ── Step 2: execute ─────────────────────────────────────────────────────
  try {
    let result;

    if (['transform', 'extract', 'merge', 'validate'].includes(db_type)) {
      addTrace('EXECUTE_START', { engine: 'structured_operation' });
      result = executeStructuredOperation(code_plan, db_type, context, inputs_payload, trace_id);
      addTrace('EXECUTE_DONE');
    } else if (db_type === 'javascript') {
      addTrace('EXECUTE_START', { engine: 'javascript' });
      result = executeJavaScript(code_plan, context, inputs_payload, trace_id);
      addTrace('EXECUTE_DONE');
    } else if (db_type === 'sql_pg') {
      addTrace('EXECUTE_START', { engine: 'postgres' });
      result = await executePostgresQuery(env, code_plan);
      addTrace('EXECUTE_DONE', { rows: Array.isArray(result) ? result.length : null });
    } else if (db_type === 'mongodb') {
      addTrace('EXECUTE_START', { engine: 'mongodb' });
      result = await executeMongoQuery(env, code_plan);
      addTrace('EXECUTE_DONE', { rows: Array.isArray(result) ? result.length : null });
    } else {
      const syntax = validateQuerySyntax(code_plan, db_type);
      addTrace('SYNTAX_CHECK', { db_type, passed: syntax.valid });

      if (!syntax.valid) {
        return Response.json({
          result: null,
          trace,
          validation_status: 'SYNTAX_ERROR',
          error_if_any: syntax.error,
        });
      }

      result = {
        status: 'VALIDATED_ONLY',
        message: `Query validated for ${db_type}. Runtime execution is not implemented yet.`,
        db_type,
        query: code_plan,
        context,
        inputs_payload,
        ...(trace_id && { trace_id }),
        ...(step_id && { step_id }),
      };
      addTrace('VALIDATION_DONE');
    }

    return Response.json({
      result,
      trace,
      validation_status: 'PASSED',
      error_if_any: null,
    });
  } catch (err) {
    addTrace('EXECUTE_ERROR', { error: err.message });
    return Response.json({
      result: null,
      trace,
      validation_status: 'RUNTIME_ERROR',
      error_if_any: err.message,
    });
  }
}

// ---------------------------------------------------------------------------
// POST /validate  (syntax check only, no execution)
// ---------------------------------------------------------------------------
async function handleValidate(request, env) {
  let body;
  try {
    body = await request.json();
  } catch {
    return Response.json({ valid: false, error: 'Invalid JSON body' }, { status: 400 });
  }

  const { code_plan, db_type = 'sql_pg' } = body;
  if (!code_plan) return Response.json({ valid: false, error: 'Missing code_plan field' }, { status: 400 });

  const safety = validateSafety(code_plan, db_type);
  if (!safety.safe) return Response.json({ valid: false, error: safety.reason });

  if (['transform', 'extract', 'merge', 'validate'].includes(db_type)) {
    const parsed = parseStructuredOperation(code_plan);
    if (!parsed.ok) {
      return Response.json({ valid: false, error: parsed.error });
    }
    const validation = validateStructuredOperation(parsed.value, db_type);
    return Response.json({ valid: validation.valid, error: validation.error ?? null });
  }

  if (db_type === 'javascript') {
    return Response.json({
      valid: false,
      error: 'Arbitrary JavaScript execution is not supported on Cloudflare Workers; use a structured operation.',
    });
  }

  const syntax = validateQuerySyntax(code_plan, db_type);
  return Response.json({ valid: syntax.valid, error: syntax.error ?? null });
}

async function executePostgresQuery(env, queryText) {
  const connectionString = resolvePostgresConnectionString(env);
  if (!connectionString) {
    throw new Error('Missing PostgreSQL configuration. Set POSTGRES_URL or PG_* variables.');
  }

  const client = new PgClient({ connectionString });
  try {
    await withTimeout(client.connect(), DB_TIMEOUT_MS, 'PostgreSQL connect timed out');
    const result = await withTimeout(client.query(queryText), DB_TIMEOUT_MS, 'PostgreSQL query timed out');
    return result.rows;
  } finally {
    try {
      await client.end();
    } catch {
      // Ignore cleanup failures.
    }
  }
}

async function executeMongoQuery(env, codePlan) {
  const uri = env.MONGODB_URI || env.MONGO_URI;
  const databaseName = env.MONGODB_DATABASE || env.MONGO_DATABASE;
  if (!uri) {
    throw new Error('Missing MongoDB configuration. Set MONGODB_URI or MONGO_URI.');
  }
  if (!databaseName) {
    throw new Error('Missing MongoDB database name. Set MONGODB_DATABASE or MONGO_DATABASE.');
  }

  let parsed;
  try {
    parsed = JSON.parse(codePlan);
  } catch (err) {
    throw new Error(`Invalid MongoDB code_plan JSON: ${err.message}`);
  }

  const collectionName = parsed.collection;
  if (!collectionName || typeof collectionName !== 'string') {
    throw new Error('MongoDB code_plan must include a string "collection" field.');
  }

  const client = new MongoClient(uri);
  try {
    await withTimeout(client.connect(), DB_TIMEOUT_MS, 'MongoDB connect timed out');
    const collection = client.db(databaseName).collection(collectionName);
    const limit = normalizeLimit(parsed.limit);

    if (Array.isArray(parsed.pipeline)) {
      return await withTimeout(
        collection.aggregate(parsed.pipeline, { maxTimeMS: DB_TIMEOUT_MS }).limit(limit).toArray(),
        DB_TIMEOUT_MS,
        'MongoDB aggregate timed out',
      );
    }

    const filter = parsed.filter && typeof parsed.filter === 'object' ? parsed.filter : {};
    const options = parsed.options && typeof parsed.options === 'object' ? parsed.options : {};
    return await withTimeout(
      collection.find(filter, options).limit(limit).toArray(),
      DB_TIMEOUT_MS,
      'MongoDB find timed out',
    );
  } finally {
    try {
      await client.close();
    } catch {
      // Ignore cleanup failures.
    }
  }
}

function resolvePostgresConnectionString(env) {
  if (env.POSTGRES_URL) {
    return env.POSTGRES_URL;
  }

  if (env.PG_HOST && env.PG_PORT && env.PG_DATABASE && env.PG_USER) {
    const password = encodeURIComponent(env.PG_PASSWORD || '');
    const user = encodeURIComponent(env.PG_USER);
    return `postgresql://${user}:${password}@${env.PG_HOST}:${env.PG_PORT}/${env.PG_DATABASE}`;
  }

  return null;
}

function normalizeLimit(rawLimit) {
  const fallback = 100;
  if (rawLimit == null) {
    return fallback;
  }

  const parsed = Number(rawLimit);
  if (!Number.isFinite(parsed) || parsed <= 0) {
    return fallback;
  }

  return Math.min(parsed, 1000);
}

async function withTimeout(promise, timeoutMs, message) {
  let timeoutId;
  try {
    return await Promise.race([
      promise,
      new Promise((_, reject) => {
        timeoutId = setTimeout(() => reject(new Error(message)), timeoutMs);
      }),
    ]);
  } finally {
    clearTimeout(timeoutId);
  }
}

// ---------------------------------------------------------------------------
// JavaScript transform executor (sandboxed globals only)
// ---------------------------------------------------------------------------
function executeJavaScript(code, context, inputsPayload, traceId) {
  const safeGlobals = {
    JSON,
    Math,
    Date,
    Array,
    Object,
    String,
    Number,
    Boolean,
    parseInt,
    parseFloat,
    isNaN,
    isFinite,
    // Suppress console side-effects
    console: { log: () => {}, warn: () => {}, error: () => {}, info: () => {} },
    // Convenience: expose shared context and resolved step inputs
    context,
    inputs: inputsPayload ?? {},
    data: context?.data ?? [],
    trace_id: traceId ?? null,
  };

  const fn = new Function(...Object.keys(safeGlobals), `"use strict";\n${code}`);
  return fn(...Object.values(safeGlobals));
}

function executeStructuredOperation(codePlan, dbType, context, inputsPayload, traceId) {
  const parsed = parseStructuredOperation(codePlan);
  if (!parsed.ok) {
    throw new Error(parsed.error);
  }

  const validation = validateStructuredOperation(parsed.value, dbType);
  if (!validation.valid) {
    throw new Error(validation.error);
  }

  const operation = parsed.value;
  switch (operation.operation) {
    case 'merge_on_key':
      return executeMergeOnKey(operation, inputsPayload);
    case 'keyword_sentiment':
      return executeKeywordSentiment(operation, inputsPayload);
    case 'regex_extract':
      return executeRegexExtract(operation, inputsPayload);
    case 'validate_non_empty':
      return executeValidateNonEmpty(operation, inputsPayload);
    default:
      throw new Error(`Unsupported structured operation: ${operation.operation}`);
  }
}

function parseStructuredOperation(codePlan) {
  try {
    const parsed = JSON.parse(codePlan);
    if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
      return { ok: false, error: 'Structured sandbox code_plan must be a JSON object' };
    }
    return { ok: true, value: parsed };
  } catch (err) {
    return { ok: false, error: `Structured sandbox code_plan must be valid JSON: ${err.message}` };
  }
}

function validateStructuredOperation(operation, dbType) {
  if (!operation.operation || typeof operation.operation !== 'string') {
    return { valid: false, error: 'Structured operation must include a string "operation" field' };
  }

  if (dbType === 'merge' && operation.operation !== 'merge_on_key') {
    return { valid: false, error: 'merge steps must use the merge_on_key operation' };
  }
  if (dbType === 'extract' && !['keyword_sentiment', 'regex_extract'].includes(operation.operation)) {
    return { valid: false, error: 'extract steps must use keyword_sentiment or regex_extract' };
  }
  if (dbType === 'validate' && operation.operation !== 'validate_non_empty') {
    return { valid: false, error: 'validate steps must use the validate_non_empty operation' };
  }

  return { valid: true };
}

function executeMergeOnKey(operation, inputsPayload) {
  const leftRows = resolveInputRows(inputsPayload, operation.left_input);
  const rightRows = resolveInputRows(inputsPayload, operation.right_input);
  const leftKey = operation.left_key;
  const rightKey = operation.right_key;
  const joinType = operation.join_type || 'inner';
  const repaired = operation.repaired === true;

  if (!leftKey || !rightKey) {
    throw new Error('merge_on_key requires left_key and right_key');
  }
  if (operation.require_repaired && !repaired) {
    throw new Error('normalization failed');
  }

  const rightIndex = new Map();
  for (const row of rightRows) {
    const key = row?.[rightKey];
    if (!rightIndex.has(key)) {
      rightIndex.set(key, []);
    }
    rightIndex.get(key).push(row);
  }

  const joined = [];
  const matchedRightKeys = new Set();
  for (const leftRow of leftRows) {
    const leftValue = leftRow?.[leftKey];
    const matches = rightIndex.get(leftValue) || [];
    if (matches.length > 0) {
      matchedRightKeys.add(leftValue);
      for (const rightRow of matches) {
        joined.push({ ...leftRow, ...rightRow, ...(repaired ? { repaired: true } : {}) });
      }
    } else if (joinType === 'left' || joinType === 'full') {
      joined.push({ ...leftRow, ...(repaired ? { repaired: true } : {}) });
    }
  }

  if (joinType === 'right' || joinType === 'full') {
    for (const [key, rows] of rightIndex.entries()) {
      if (matchedRightKeys.has(key)) continue;
      for (const row of rows) {
        joined.push({ ...row, ...(repaired ? { repaired: true } : {}) });
      }
    }
  }

  return joined;
}

function executeKeywordSentiment(operation, inputsPayload) {
  const text = resolveInputText(inputsPayload, operation.input_ref, operation.text_field);
  const normalized = text.toLowerCase();
  const positiveTerms = Array.isArray(operation.positive_terms) && operation.positive_terms.length
    ? operation.positive_terms
    : ['great', 'excellent', 'love', 'amazing', 'perfect'];
  const negativeTerms = Array.isArray(operation.negative_terms) && operation.negative_terms.length
    ? operation.negative_terms
    : ['terrible', 'awful', 'hate', 'worst', 'broken'];

  const sentiment = positiveTerms.some((term) => normalized.includes(String(term).toLowerCase()))
    ? 'positive'
    : negativeTerms.some((term) => normalized.includes(String(term).toLowerCase()))
      ? 'negative'
      : 'neutral';

  if (operation.output_mode === 'record') {
    return {
      sentiment,
      text,
      source: operation.input_ref || null,
    };
  }

  return sentiment;
}

function executeRegexExtract(operation, inputsPayload) {
  const text = resolveInputText(inputsPayload, operation.input_ref, operation.text_field);
  const pattern = operation.pattern;
  if (!pattern || typeof pattern !== 'string') {
    throw new Error('regex_extract requires a string pattern');
  }

  const flags = typeof operation.flags === 'string' ? operation.flags : '';
  const regex = new RegExp(pattern, flags);
  const match = text.match(regex);
  if (!match) {
    return operation.output_mode === 'record' ? { matched: false, value: null } : null;
  }

  if (Array.isArray(operation.group_names) && operation.group_names.length > 0) {
    const extracted = {};
    for (let i = 0; i < operation.group_names.length; i += 1) {
      extracted[operation.group_names[i]] = match[i + 1] ?? null;
    }
    return extracted;
  }

  return match[1] ?? match[0];
}

function executeValidateNonEmpty(operation, inputsPayload) {
  const values = resolveInputRows(inputsPayload, operation.input_ref);
  if (!Array.isArray(values) || values.length === 0) {
    throw new Error(operation.message || 'validation failed: expected non-empty input');
  }
  return {
    ok: true,
    count: values.length,
  };
}

function resolveInputRows(inputsPayload, refName) {
  if (!refName) {
    throw new Error('Structured operation is missing required input reference');
  }
  const value = inputsPayload?.[refName];
  return Array.isArray(value) ? value : [];
}

function resolveInputText(inputsPayload, inputRef, textField) {
  const source = inputsPayload?.[inputRef];
  if (typeof source === 'string') {
    return source;
  }
  if (source && typeof source === 'object' && textField && typeof source[textField] === 'string') {
    return source[textField];
  }
  throw new Error('Structured extraction operation could not resolve input text');
}

// ---------------------------------------------------------------------------
// Safety guard — block destructive patterns
// ---------------------------------------------------------------------------
function validateSafety(code, db_type) {
  const sqlDestructive = [
    { re: /\bDROP\s+TABLE\b/i,        reason: 'DROP TABLE not allowed (read-only sandbox)' },
    { re: /\bDROP\s+DATABASE\b/i,     reason: 'DROP DATABASE not allowed' },
    { re: /\bTRUNCATE\b/i,            reason: 'TRUNCATE not allowed (read-only sandbox)' },
    { re: /\bDELETE\s+FROM\b/i,       reason: 'DELETE not allowed (read-only sandbox)' },
    { re: /\bINSERT\s+INTO\b/i,       reason: 'INSERT not allowed (read-only sandbox)' },
    { re: /\bUPDATE\s+\w+\s+SET\b/i,  reason: 'UPDATE not allowed (read-only sandbox)' },
    { re: /\bCREATE\s+TABLE\b/i,      reason: 'CREATE TABLE not allowed' },
    { re: /\bALTER\s+TABLE\b/i,       reason: 'ALTER TABLE not allowed' },
  ];

  const jsDestructive = [
    { re: /\bprocess\b/,              reason: 'process object not accessible' },
    { re: /\brequire\s*\(/,           reason: 'require() not allowed' },
    { re: /\bimport\s*\(/,            reason: 'Dynamic import not allowed' },
    { re: /\beval\s*\(/,              reason: 'eval() not allowed' },
    { re: /\bnew\s+Function\s*\(/,    reason: 'Function constructor not allowed in code' },
    { re: /\bfetch\s*\(/,             reason: 'fetch() not allowed in sandbox code' },
    { re: /\bXMLHttpRequest\b/,       reason: 'XMLHttpRequest not allowed' },
    { re: /\bglobalThis\b/,           reason: 'globalThis access not allowed' },
    { re: /\bself\b/,                 reason: 'self access not allowed' },
  ];

  const checks = [
    ...sqlDestructive,
    ...(db_type === 'javascript' || db_type === 'transform' ? jsDestructive : []),
  ];

  for (const { re, reason } of checks) {
    if (re.test(code)) return { safe: false, reason };
  }

  return { safe: true };
}

// ---------------------------------------------------------------------------
// Query syntax validation (heuristic — not a full parser)
// ---------------------------------------------------------------------------
function validateQuerySyntax(code, db_type) {
  const trimmed = code.trim();
  if (!trimmed) return { valid: false, error: 'Empty query' };

  if (db_type === 'mongodb') {
    try {
      const parsed = JSON.parse(trimmed);
      if (Array.isArray(parsed)) {
        return { valid: false, error: 'MongoDB code_plan must be an object with collection and filter/pipeline' };
      }
      if (typeof parsed !== 'object' || parsed === null) {
        return { valid: false, error: 'MongoDB code_plan must be a JSON object' };
      }
      if (!parsed.collection || typeof parsed.collection !== 'string') {
        return { valid: false, error: 'MongoDB code_plan must include a string collection field' };
      }
      if (parsed.pipeline != null && !Array.isArray(parsed.pipeline)) {
        return { valid: false, error: 'MongoDB pipeline must be a JSON array when provided' };
      }
      if (parsed.filter != null && (typeof parsed.filter !== 'object' || Array.isArray(parsed.filter))) {
        return { valid: false, error: 'MongoDB filter must be a JSON object when provided' };
      }
      return { valid: true };
    } catch (err) {
      return { valid: false, error: `Invalid MongoDB code_plan JSON: ${err.message}` };
    }
  }

  // SQL: must start with SELECT / WITH (CTE) / EXPLAIN
  if (!/^\s*(SELECT|WITH|EXPLAIN)\b/i.test(trimmed)) {
    return { valid: false, error: 'Only SELECT / WITH (CTE) / EXPLAIN queries are allowed' };
  }

  // Basic parentheses balance check
  let depth = 0;
  for (const ch of trimmed) {
    if (ch === '(') depth++;
    if (ch === ')') depth--;
    if (depth < 0) return { valid: false, error: 'Unmatched closing parenthesis in query' };
  }
  if (depth !== 0) return { valid: false, error: 'Unmatched opening parenthesis in query' };

  return { valid: true };
}

// ---------------------------------------------------------------------------
// CORS headers
// ---------------------------------------------------------------------------
function corsHeaders() {
  return {
    'Access-Control-Allow-Origin': '*',
    'Access-Control-Allow-Methods': 'GET, POST, OPTIONS',
    'Access-Control-Allow-Headers': 'Content-Type, Authorization',
    'Content-Type': 'application/json',
  };
}
