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
//   code:     string   — JS transformation code or SQL/MongoDB query
//   db_type:  string   — "javascript" | "transform" | "sql_pg" |
//                        "sql_sqlite" | "sql_duckdb" | "mongodb"
//   context:  object   — optional data passed into JS transforms
//   query_id: string   — optional correlation id
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

  const { code, db_type = 'javascript', context = {}, query_id } = body;

  if (!code || typeof code !== 'string') {
    return Response.json({
      result: null,
      trace: [],
      validation_status: 'ERROR',
      error_if_any: 'Missing required field: code (string)',
    }, { status: 400 });
  }

  const trace = [];
  const t0 = Date.now();
  const addTrace = (step, detail = null) =>
    trace.push({ step, ms: Date.now() - t0, ...(detail && { detail }) });

  // ── Step 1: safety check ────────────────────────────────────────────────
  const safety = validateSafety(code, db_type);
  addTrace('SAFETY_CHECK', { passed: safety.safe });

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

    if (db_type === 'javascript' || db_type === 'transform') {
      addTrace('EXECUTE_START', { engine: 'javascript' });
      result = executeJavaScript(code, context);
      addTrace('EXECUTE_DONE');
    } else {
      // SQL / MongoDB: validate syntax, then hand back to local MCP toolbox
      const syntax = validateQuerySyntax(code, db_type);
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
        status: 'VALIDATED',
        message: `Query validated for ${db_type}. Execute via local MCP toolbox.`,
        db_type,
        query: code,
        context,
        ...(query_id && { query_id }),
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

  const { code, db_type = 'sql_pg' } = body;
  if (!code) return Response.json({ valid: false, error: 'Missing code field' }, { status: 400 });

  const safety = validateSafety(code, db_type);
  if (!safety.safe) return Response.json({ valid: false, error: safety.reason });

  if (db_type === 'javascript' || db_type === 'transform') {
    try {
      new Function(code); // parse-only, no execution
      return Response.json({ valid: true });
    } catch (err) {
      return Response.json({ valid: false, error: err.message });
    }
  }

  const syntax = validateQuerySyntax(code, db_type);
  return Response.json({ valid: syntax.valid, error: syntax.error ?? null });
}

// ---------------------------------------------------------------------------
// JavaScript transform executor (sandboxed globals only)
// ---------------------------------------------------------------------------
function executeJavaScript(code, context) {
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
    // Convenience: expose context + its data array directly
    context,
    data: context?.data ?? [],
  };

  const fn = new Function(...Object.keys(safeGlobals), `"use strict";\n${code}`);
  return fn(...Object.values(safeGlobals));
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
      if (!Array.isArray(parsed) && typeof parsed !== 'object') {
        return { valid: false, error: 'MongoDB query must be a JSON array (pipeline) or object' };
      }
      return { valid: true };
    } catch (err) {
      return { valid: false, error: `Invalid MongoDB JSON: ${err.message}` };
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
