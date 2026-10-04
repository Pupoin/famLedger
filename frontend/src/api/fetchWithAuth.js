import { tx } from "../localization.js";
let _onUnauthorized = null;

export function setOnUnauthorized(callback) {
  _onUnauthorized = callback;
}

export async function fetchWithAuth(url, options = {}) {
  const headers = new Headers(options.headers);
  if (!['GET', 'HEAD', 'OPTIONS'].includes((options.method || 'GET').toUpperCase())) {
    headers.set('X-FamLedger-CSRF', '1');
  }
  const res = await fetch(url, { ...options, headers, credentials: "include" });
  if (res.status === 401 && _onUnauthorized) {
    _onUnauthorized();
    throw new Error(tx("Session expired. Please log in again."));
  }
  return res;
}
