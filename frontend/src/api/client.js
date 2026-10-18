import { getToken, clearSession } from '../lib/auth.js';

// Parse a fetch Response as JSON, with a readable error when the server
// returns something else (e.g. the SPA fallback serving index.html with a
// 200 for unknown /api paths — that used to explode as
// "Unexpected token '<'"). The thrown message now names the URL.
async function parseJson(res) {
  const text = await res.text();
  try {
    return JSON.parse(text);
  } catch {
    const head = text.trim().slice(0, 40).replace(/\s+/g, ' ');
    throw new Error(
      `${res.url} returned non-JSON${head ? ` (${head}…)` : ''} — is the backend up to date?`,
    );
  }
}

// Hooks pass full paths like "/api/groups" — fetch them as-is.
// Attaches the bearer token when signed in; a 401 anywhere clears the
// session and sends the user to /login (preserving where they were).
async function request(path) {
  const token = getToken();
  const res = await fetch(path, {
    headers: token ? { Authorization: `Bearer ${token}` } : undefined,
  });
  if (!res.ok) {
    if (res.status === 401 && !path.startsWith('/api/auth/')) {
      clearSession();
      const next = encodeURIComponent(window.location.pathname + window.location.search);
      window.location.assign(`/login?next=${next}`);
    }
    let message = `Request failed (${res.status})`;
    try {
      const body = await parseJson(res);
      if (body?.error) message = body.error;
      else if (body?.detail) {
        // FastAPI validation errors arrive as a list of {msg,...}
        message = Array.isArray(body.detail) ? body.detail.map((d) => d.msg).join('; ') : body.detail;
      }
    } catch (err) {
      message = err.message;
    }
    throw new Error(message);
  }
  return parseJson(res);
}

// POST/PUT helper with a JSON body.
async function send(path, method, body) {
  const token = getToken();
  const res = await fetch(path, {
    method,
    headers: {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!res.ok) {
    let message = `Request failed (${res.status})`;
    try {
      const data = await parseJson(res);
      if (data?.error) message = data.error;
      else if (data?.detail) {
        // FastAPI validation errors arrive as a list of {msg,...}
        message = Array.isArray(data.detail) ? data.detail.map((d) => d.msg).join('; ') : data.detail;
      }
    } catch (err) {
      message = err.message;
    }
    throw new Error(message);
  }
  return parseJson(res);
}

export function post(path, body) {
  return send(path, 'POST', body);
}

// Build a "?a=1&b=2" query string, dropping empty/undefined values
export function buildQuery(params) {
  const sp = new URLSearchParams();
  Object.entries(params || {}).forEach(([k, v]) => {
    if (v === undefined || v === null || v === '') return;
    sp.set(k, String(v));
  });
  const qs = sp.toString();
  return qs ? `?${qs}` : '';
}

export default request;