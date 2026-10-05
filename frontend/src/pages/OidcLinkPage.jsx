import { useEffect, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { CircleAlert, Link2, LockKeyhole } from 'lucide-react';
import { tx, useLocale } from '../localization';
import { apiErrorMessage } from '../api/errorMessages';

export default function OidcLinkPage() {
  useLocale();
  const [searchParams] = useSearchParams();
  const state = searchParams.get('state') || '';
  const [request, setRequest] = useState(null);
  const [loading, setLoading] = useState(true);
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    const controller = new AbortController();
    setRequest(null);
    setPassword('');
    setError('');
    setLoading(true);
    async function load() {
      try {
        if (!state) throw new Error(tx('关联请求已失效，请重新使用 OIDC 登录'));
        const response = await fetch(`/api/v1/auth/sso/link-requests/${encodeURIComponent(state)}`, {
          credentials: 'include', signal: controller.signal,
        });
        const data = await response.json();
        if (!response.ok) throw new Error(apiErrorMessage(data.detail));
        if (!controller.signal.aborted) setRequest(data);
      } catch (err) {
        if (!controller.signal.aborted) setError(err.message || tx('无法加载关联请求'));
      } finally {
        if (!controller.signal.aborted) setLoading(false);
      }
    }
    load();
    return () => controller.abort();
  }, [state]);

  async function complete(event) {
    event.preventDefault();
    if (submitting) return;
    setSubmitting(true);
    setError('');
    try {
      const response = await fetch('/api/v1/auth/sso/link-requests/complete', {
        method: 'POST', credentials: 'include',
        headers: { 'Content-Type': 'application/json', 'X-FamLedger-CSRF': '1' },
        body: JSON.stringify({ state, password }),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(apiErrorMessage(data.detail));
      setPassword('');
      // Reload the authenticated app so preferences and the current account
      // are loaded together, including when another account was signed in.
      window.location.replace('/');
    } catch (err) {
      setError(err.message || tx('关联失败，请重试'));
      setPassword('');
      setSubmitting(false);
    }
  }

  return (
    <div className="min-h-screen bg-background flex items-center justify-center px-4 py-8">
      <div className="w-full max-w-sm bg-surface-container-lowest rounded-[2rem] p-6 sm:p-8 shadow-lg space-y-5">
        <img src="/logo.svg?v=blue-purple" alt="famLedger" className="h-16 w-16 mx-auto object-contain" />
        <h1 className="text-xl font-bold text-on-surface text-center">{tx('关联已有账户')}</h1>
        {loading && <p role="status" className="text-sm text-on-surface-variant">{tx('正在确认关联请求…')}</p>}
        {error && (
          <div role="alert" className="flex items-start gap-2 rounded-xl bg-error-container/20 text-error p-3 text-sm break-words">
            <CircleAlert className="w-4 h-4 shrink-0 mt-0.5" aria-hidden="true" />
            <span className="min-w-0">{tx(error)}</span>
          </div>
        )}
        {request && (
          <form onSubmit={complete} className="space-y-4">
            <p className="text-sm text-on-surface-variant break-words">
              {tx('确认将 {p0} 登录关联到本地账户 {p1}。', { p0: request.provider_label, p1: request.username })}
            </p>
            <p className="text-xs text-on-surface-variant">{tx('首次关联需确认本地密码，之后可直接使用单点登录。')}</p>
            <label className="block space-y-2">
              <span className="text-sm font-semibold text-on-surface">{tx('本地账户密码')}</span>
              <div className="flex items-center gap-3 rounded-xl bg-surface-container-high px-3 py-3">
                <LockKeyhole className="w-5 h-5 shrink-0 text-on-surface-variant" aria-hidden="true" />
                <input type="password" value={password} onChange={event => setPassword(event.target.value)}
                  required maxLength={128} autoComplete="current-password" autoFocus disabled={submitting}
                  className="w-full min-w-0 bg-transparent text-on-surface outline-none" />
              </div>
            </label>
            <button type="submit" disabled={submitting}
              className="w-full flex items-center justify-center gap-2 rounded-xl bg-primary text-on-primary font-semibold px-4 py-3 disabled:opacity-50">
              <Link2 className="w-4 h-4 shrink-0" aria-hidden="true" />
              {submitting ? tx('正在关联…') : tx('确认关联并登录')}
            </button>
          </form>
        )}
        <Link to="/login" className="block text-center text-sm text-primary font-semibold">{tx('返回登录')}</Link>
      </div>
    </div>
  );
}
