/**
 * Cliente HTTP único del frontend. Toda la persistencia vive en el backend (PostgreSQL);
 * el navegador no guarda datos de negocio ni tokens (la sesión es una cookie HttpOnly).
 */

const API_BASE = '/api';
const CSRF_COOKIE = 'mb_csrf';

export class ApiError extends Error {
  constructor(status, code, message, fields = {}) {
    super(message);
    this.status = status;
    this.code = code;
    this.fields = fields || {};
  }
}

function getCookie(name) {
  const match = document.cookie.split('; ').find((c) => c.startsWith(name + '='));
  return match ? decodeURIComponent(match.split('=').slice(1).join('=')) : null;
}

async function ensureCsrf(force = false) {
  if (!force && getCookie(CSRF_COOKIE)) return;
  await fetch(`${API_BASE}/auth/csrf`, { credentials: 'same-origin' });
}

function qs(params) {
  if (!params) return '';
  const sp = new URLSearchParams();
  Object.entries(params).forEach(([k, v]) => {
    if (v !== undefined && v !== null && v !== '') sp.append(k, v);
  });
  const s = sp.toString();
  return s ? `?${s}` : '';
}

async function request(method, path, { body, params, retry = true } = {}) {
  const unsafe = method !== 'GET';
  if (unsafe) await ensureCsrf();
  const headers = { Accept: 'application/json' };
  const binary = body instanceof Blob;
  if (body !== undefined) headers['Content-Type'] = binary ? (body.type || 'application/octet-stream') : 'application/json';
  if (unsafe) headers['X-CSRF-Token'] = getCookie(CSRF_COOKIE) || '';

  let res;
  try {
    res = await fetch(`${API_BASE}${path}${qs(params)}`, {
      method,
      headers,
      credentials: 'same-origin',
      body: body === undefined ? undefined : binary ? body : JSON.stringify(body),
    });
  } catch {
    throw new ApiError(0, 'network', 'No se pudo conectar con el servidor. Verifica tu conexión e inténtalo nuevamente.');
  }

  const isJson = (res.headers.get('content-type') || '').includes('application/json');
  const data = isJson ? await res.json().catch(() => null) : null;

  if (res.ok) return data;

  const err = data?.error || {};
  if (res.status === 403 && err.code === 'csrf' && retry) {
    await ensureCsrf(true);
    return request(method, path, { body, params, retry: false });
  }
  const message = err.message || (res.status >= 500
    ? 'Ocurrió un error inesperado. Inténtalo nuevamente.'
    : 'No se pudo completar la operación.');
  const error = new ApiError(res.status, err.code || 'http_error', message, err.fields);
  if (res.status === 401 && !path.startsWith('/auth/login')) {
    window.dispatchEvent(new CustomEvent('session-expired'));
  }
  throw error;
}

export const api = {
  get: (path, params) => request('GET', path, { params }),
  post: (path, body = {}) => request('POST', path, { body }),
  put: (path, body = {}) => request('PUT', path, { body }),
  patch: (path, body = {}) => request('PATCH', path, { body }),
  del: (path) => request('DELETE', path),
  /** Envía un archivo (Blob) como cuerpo binario; el Content-Type es el tipo del Blob. */
  upload: (path, blob) => request('POST', path, { body: blob }),
  url: (path, params) => `${API_BASE}${path}${qs(params)}`,
};

let mePromise = null;
/** Usuario autenticado (o null). Se cachea por página; usar refresh=true tras login/logout. */
export function currentUser(refresh = false) {
  if (refresh || !mePromise) {
    // /auth/session responde 200 con null si no hay sesión (evita errores 401 en consola).
    mePromise = api.get('/auth/session');
  }
  return mePromise;
}

export async function logout() {
  try {
    await api.post('/auth/logout');
  } finally {
    mePromise = Promise.resolve(null);
  }
}
