import { useCallback, useEffect, useRef, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { CheckCircle2, Link2 } from 'lucide-react';
import { tx, useLocale } from '../localization';
import { fetchWithAuth } from '../api/fetchWithAuth';
import { apiErrorMessage } from '../api/errorMessages';
import { useToast } from '../ToastContext';

export default function OidcAccountLinks() {
  useLocale();
  const { showToast } = useToast();
  const [searchParams, setSearchParams] = useSearchParams();
  const [data, setData] = useState(null);
  const [error, setError] = useState('');
  const [selected, setSelected] = useState(null);
  const [action, setAction] = useState('link');
  const [password, setPassword] = useState('');
  const [busy, setBusy] = useState(false);
  const successHandled = useRef(false);

  const load = useCallback(async () => {
    setError('');
    try {
      const response = await fetchWithAuth('/api/v1/auth/sso/account-links');
      const result = await response.json();
      if (!response.ok) throw new Error(apiErrorMessage(result.detail));
      setData(result);
    } catch (err) {
      setError(err.message || tx('无法加载单点登录关联'));
    }
  }, []);

  useEffect(() => { load(); }, [load]);
  useEffect(() => {
    if (searchParams.get('sso_link') !== 'success' || successHandled.current) return;
    successHandled.current = true;
    showToast(tx('单点登录账户已关联'), 'success');
    setSearchParams(previous => {
      const params = new URLSearchParams(previous);
      params.delete('sso_link');
      return params;
    }, { replace: true });
  }, [searchParams, setSearchParams, showToast]);

  function selectAction(provider, nextAction) {
    setSelected(provider);
    setAction(nextAction);
    setPassword('');
    setError('');
  }

  async function submit(event) {
    event.preventDefault();
    if (busy || !selected) return;
    setBusy(true);
    setError('');
    try {
      const response = await fetchWithAuth(`/api/v1/auth/sso/${encodeURIComponent(selected.name)}/link`, {
        method: action === 'unlink' ? 'DELETE' : 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ current_password: data.has_password ? password : null }),
      });
      const result = await response.json();
      if (!response.ok) throw new Error(apiErrorMessage(result.detail));
      setPassword('');
      if (action === 'unlink') {
        setSelected(null);
        setData(null);
        await load();
        showToast(tx('单点登录关联已取消'), 'success');
        setBusy(false);
      } else {
        window.location.assign(result.authorize_url);
      }
    } catch (err) {
      setError(err.message || (action === 'unlink' ? tx('取消关联失败，请重试') : tx('关联失败，请重试')));
      setPassword('');
      setBusy(false);
    }
  }

  return (
    <section aria-label={tx('单点登录关联')} className="pt-5 border-t border-zinc-100 dark:border-zinc-800 space-y-3">
      <h3 className="flex items-center gap-2 text-sm font-bold text-zinc-900 dark:text-zinc-100">
        <Link2 className="w-4 h-4 shrink-0" aria-hidden="true" />{tx('单点登录关联')}
      </h3>
      <p className="text-xs text-zinc-500 dark:text-zinc-400">{tx('关联后可使用第三方账号登录现有账户，保留原有数据。')}</p>
      {error && <p role="alert" className="text-sm text-red-600 dark:text-red-400 break-words">{tx(error)}</p>}
      {!data && !error && <p role="status" className="text-xs text-zinc-500">{tx('正在加载…')}</p>}
      {!data && error && <button type="button" onClick={load} className="text-sm text-primary">{tx('重试')}</button>}
      {data?.providers.length === 0 && <p className="text-xs text-zinc-500">{tx('管理员尚未配置可用的单点登录服务。')}</p>}
      {data?.providers.map(provider => (
        <div key={provider.name} className="rounded-xl border border-zinc-200 dark:border-zinc-700 px-3 py-2.5 space-y-2">
          <div className="flex items-center justify-between gap-3">
            <span className="min-w-0 break-words text-sm text-zinc-900 dark:text-zinc-100">{provider.label}</span>
            {provider.has_binding ? (
              <div className="flex flex-wrap justify-end items-center gap-2 shrink-0">
                <span className={`flex items-center gap-1 text-xs ${provider.linked ? 'text-emerald-700 dark:text-emerald-400' : 'text-zinc-500 dark:text-zinc-400'}`}>
                  {provider.linked && <CheckCircle2 className="w-4 h-4" aria-hidden="true" />}{provider.linked ? tx('已关联') : tx('关联已不可用')}
                </span>
                <button type="button" disabled={busy || !provider.can_unlink} onClick={() => selectAction(provider, 'unlink')}
                  className="rounded-lg px-2 py-1.5 text-xs font-semibold text-red-600 dark:text-red-400 hover:bg-red-50 dark:hover:bg-red-950/40 disabled:opacity-50 disabled:cursor-not-allowed">{tx('取消关联')}</button>
              </div>
            ) : (
              <button type="button" disabled={busy} onClick={() => selectAction(provider, 'link')}
                className="shrink-0 rounded-lg px-3 py-1.5 bg-primary text-on-primary text-xs font-semibold disabled:opacity-50">{tx('关联')}</button>
            )}
          </div>
          {provider.has_binding && !provider.can_unlink && <p className="text-xs text-zinc-500 dark:text-zinc-400">{tx('这是唯一可用的登录方式。请先设置本地密码或关联其他可用的登录服务，再取消关联。')}</p>}
          {provider.has_binding && !provider.linked && provider.enabled && <button type="button" disabled={busy} onClick={() => selectAction(provider, 'link')}
            className="text-xs font-semibold text-primary disabled:opacity-50">{tx('重新关联')}</button>}
        </div>
      ))}
      {selected && (
        <form onSubmit={submit} className="rounded-xl bg-zinc-50 dark:bg-zinc-800/50 p-3 space-y-3">
          <p className="text-sm text-zinc-700 dark:text-zinc-200 break-words">{action === 'unlink' ? tx('取消 {p0} 的关联', { p0: selected.label }) : tx('关联 {p0}', { p0: selected.label })}</p>
          {data.has_password && (
            <label className="block space-y-1">
              <span className="text-xs font-semibold text-zinc-700 dark:text-zinc-300">{tx('本地账户密码')}</span>
              <input type="password" required maxLength={128} autoComplete="current-password" value={password}
                onChange={event => setPassword(event.target.value)} disabled={busy}
                className="w-full min-w-0 rounded-lg border border-zinc-300 dark:border-zinc-600 bg-white dark:bg-zinc-900 px-3 py-2 text-sm text-zinc-900 dark:text-zinc-100" />
            </label>
          )}
          <p className="text-xs text-zinc-500 dark:text-zinc-400">{action === 'unlink' ? tx('取消后，该服务将无法登录此账户；账本数据会保留，其他设备需要重新登录。') : tx('接下来将跳转到认证服务验证第三方账号。')}</p>
          <div className="flex gap-2">
            <button type="submit" disabled={busy} className={`rounded-lg px-3 py-2 text-sm font-semibold disabled:opacity-50 ${action === 'unlink' ? 'bg-red-600 text-white dark:bg-red-700' : 'bg-primary text-on-primary'}`}>
              {action === 'unlink' ? (busy ? tx('正在取消…') : tx('确认取消关联')) : (busy ? tx('正在关联…') : tx('继续关联'))}
            </button>
            <button type="button" disabled={busy} onClick={() => { setSelected(null); setPassword(''); }} className="rounded-lg px-3 py-2 text-sm text-zinc-600 dark:text-zinc-300">{tx('取消')}</button>
          </div>
        </form>
      )}
    </section>
  );
}
