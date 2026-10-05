import React, { useEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { X } from 'lucide-react';
import { tx, useLocale } from '../localization';
import { fetchWithAuth } from '../api/fetchWithAuth';
import { apiErrorMessage } from '../api/errorMessages';
import { formatCurrency, currencySymbol } from '../utils/currency';
import { useCurrency } from '../CurrencyContext';
import { useToast } from '../ToastContext';
import { ACCOUNT_TYPE_OPTIONS } from './AccountTypeSelectDropdown';
import { Button } from './ds/DesignSystem';

export default function BulkAccountSettingsModal({ isOpen, accounts, members, onClose, onSuccess }) {
  useLocale();
  const { showToast } = useToast();
  const { privacyMode } = useCurrency();
  const [hidden, setHidden] = useState('');
  const [applyInstitution, setApplyInstitution] = useState(false);
  const [institution, setInstitution] = useState('');
  const [accountType, setAccountType] = useState('');
  const [shareChanges, setShareChanges] = useState({});
  const [confirmation, setConfirmation] = useState(null);
  const [error, setError] = useState('');
  const [saving, setSaving] = useState(false);
  const savingRef = useRef(false);
  const dialogRef = useRef(null);
  const closeRef = useRef(onClose);
  closeRef.current = onClose;
  const canEdit = accounts.length > 0 && accounts.every(account => account.can_manage === true);
  const canShare = accounts.length > 0 && accounts.every(account => account.can_manage_shares === true);
  const hasChanges = hidden !== '' || (canEdit && (applyInstitution || accountType !== ''))
    || (canShare && Object.values(shareChanges).some(Boolean));
  const inputClass = 'w-full min-w-0 rounded-lg border border-zinc-200 dark:border-zinc-700 bg-white dark:bg-zinc-800 text-zinc-900 dark:text-zinc-100 px-2.5 py-2 text-sm disabled:opacity-50';

  useEffect(() => {
    if (!isOpen) return;
    setHidden(''); setApplyInstitution(false); setInstitution(''); setAccountType('');
    setShareChanges({}); setConfirmation(null); setError('');
    const previousFocus = document.activeElement;
    const roots = [document.documentElement, document.body];
    const overflow = roots.map(root => root.style.overflow);
    roots.forEach(root => { root.style.overflow = 'hidden'; });
    dialogRef.current?.focus();
    const onKeyDown = event => {
      if (event.key === 'Escape') { event.preventDefault(); if (!savingRef.current) closeRef.current(); }
      if (event.key !== 'Tab') return;
      const controls = dialogRef.current?.querySelectorAll('button:enabled, input:enabled, select:enabled');
      if (!controls?.length) return;
      const first = controls[0], last = controls[controls.length - 1];
      if (event.shiftKey && (document.activeElement === first || document.activeElement === dialogRef.current)) {
        event.preventDefault(); last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault(); first.focus();
      }
    };
    document.addEventListener('keydown', onKeyDown);
    return () => {
      roots.forEach((root, index) => { root.style.overflow = overflow[index]; });
      document.removeEventListener('keydown', onKeyDown);
      previousFocus?.focus({ preventScroll: true });
    };
  }, [isOpen]);

  if (!isOpen) return null;
  const close = () => { if (!savingRef.current) onClose(); };
  const save = async (payload) => {
    if (savingRef.current) return;
    savingRef.current = true; setSaving(true); setError('');
    try {
      const response = await fetchWithAuth('/api/v1/accounts/bulk/settings', {
        method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload),
      });
      const result = await response.json().catch(() => ({}));
      if (response.status === 409 && result.detail?.code === 'balance_confirmation_required') {
        setConfirmation({ payload, accounts: result.detail.accounts });
        return;
      }
      if (!response.ok) throw new Error(apiErrorMessage(result.detail, tx('批量设置保存失败')));
      showToast(tx('已更新 {p0} 个账户', { p0: result.updated_count }), 'success');
      if (result.unlinked_account_ids?.length) showToast(tx('共享或账户类型已修改，相关副卡关系已解除'), 'info');
      onSuccess(); onClose();
    } catch (failure) {
      setError(failure.message || tx('批量设置保存失败'));
    } finally {
      savingRef.current = false; setSaving(false);
    }
  };
  const submit = event => {
    event.preventDefault();
    if (!hasChanges || accounts.length > 200) return;
    const payload = { account_ids: accounts.map(account => account.account_id) };
    if (hidden !== '') payload.hidden = hidden === 'hide';
    if (canEdit && applyInstitution) payload.institution_name = institution;
    if (canEdit && accountType) payload.account_type = accountType;
    const changed = Object.entries(shareChanges).filter(([, value]) => value);
    if (canShare && changed.length) payload.members = changed.map(([user_id, value]) => ({
      user_id, shared: value !== 'none', permission: value === 'none' ? 'read_only' : value,
    }));
    save(payload);
  };

  return createPortal(
    <div className="fixed inset-0 z-[9999] bg-black/50 backdrop-blur-xs p-3 sm:p-4 flex items-center justify-center overflow-hidden overscroll-none"
      onClick={event => { if (event.target === event.currentTarget) close(); }}>
      <div ref={dialogRef} role="dialog" aria-modal="true" aria-labelledby="bulk-account-title" tabIndex={-1}
        className="w-full max-w-lg max-h-[90dvh] overflow-y-auto overscroll-contain rounded-2xl bg-white dark:bg-zinc-900 border border-zinc-200 dark:border-zinc-800 p-4 sm:p-5 space-y-4 shadow-xl">
        <div className="flex items-center justify-between gap-2">
          <h3 id="bulk-account-title" className="font-bold text-zinc-900 dark:text-zinc-100">{tx('批量编辑账户')}</h3>
          <button type="button" disabled={saving} onClick={close} aria-label={tx('关闭')} className="p-1.5 text-zinc-500"><X className="w-4 h-4" /></button>
        </div>
        <p className="text-xs text-zinc-500">{tx('已选择 {p0} 个账户，仅应用修改的设置。', { p0: accounts.length })}</p>
        <div className="text-xs text-zinc-600 dark:text-zinc-400 max-h-20 overflow-y-auto overscroll-contain">
          {accounts.map(account => <p key={account.account_id}>{account.account_name}</p>)}
        </div>
        {accounts.length > 200 && <p role="alert" className="text-xs text-rose-600">{tx('每次最多编辑 200 个账户，请减少选择。')}</p>}
        {error && <p role="alert" className="text-sm text-rose-600 dark:text-rose-400">{error}</p>}
        <form onSubmit={submit} className="space-y-4">
          <fieldset disabled={saving || Boolean(confirmation)} className="space-y-4">
            <div>
              <label htmlFor="bulk-account-visibility" className="block text-xs font-medium mb-1 text-zinc-600 dark:text-zinc-400">{tx('侧边栏显示')}</label>
              <select id="bulk-account-visibility" value={hidden} onChange={event => setHidden(event.target.value)} className={inputClass}>
                <option value="">{tx('保持不变')}</option><option value="hide">{tx('从侧边栏隐藏')}</option><option value="show">{tx('恢复侧边栏显示')}</option>
              </select>
            </div>
            {!canEdit && <p className="text-xs text-amber-700 dark:text-amber-300">{tx('所选账户包含只读或读写共享账户，仅能批量修改侧边栏显示。')}</p>}
            <fieldset disabled={!canEdit} className="space-y-3">
              <div>
                <label className="flex items-center gap-2 text-xs font-medium text-zinc-600 dark:text-zinc-400">
                  <input type="checkbox" checked={applyInstitution} onChange={event => setApplyInstitution(event.target.checked)} />{tx('修改金融机构')}
                </label>
                {applyInstitution && <input aria-label={tx('金融机构')} maxLength={100} value={institution} onChange={event => setInstitution(event.target.value)} className={`${inputClass} mt-2`} placeholder={tx('留空可清除金融机构')} />}
              </div>
              <div>
                <label htmlFor="bulk-account-type" className="block text-xs font-medium mb-1 text-zinc-600 dark:text-zinc-400">{tx('账户类型')}</label>
                <select id="bulk-account-type" value={accountType} onChange={event => setAccountType(event.target.value)} className={inputClass}>
                  <option value="">{tx('保持不变')}</option>
                  {ACCOUNT_TYPE_OPTIONS.map(option => <option key={option.value} value={option.value}>{tx(option.shortLabel)}</option>)}
                </select>
              </div>
            </fieldset>
            <fieldset disabled={!canShare} className="space-y-2">
              <legend className="text-xs font-medium text-zinc-600 dark:text-zinc-400 mb-2">{tx('共享权限')}</legend>
              <p className="text-xs text-zinc-500">{tx('只修改指定成员的共享权限；账户拥有者的权限保持不变。')}</p>
              {members.map(member => {
                const ownsAll = accounts.every(account => account.owner_id === member.id);
                return <div key={member.id} className="flex items-center gap-2">
                <label htmlFor={`bulk-share-${member.id}`} title={member.display_name || member.username} className="text-xs min-w-0 flex-1 truncate text-zinc-600 dark:text-zinc-300">{member.display_name || member.username}</label>
                <select id={`bulk-share-${member.id}`} disabled={ownsAll} value={ownsAll ? 'full_control' : shareChanges[member.id] || ''}
                  onChange={event => setShareChanges(previous => ({ ...previous, [member.id]: event.target.value }))}
                  className={`${inputClass} !w-36 shrink-0`}>
                  <option value="">{tx('保持不变')}</option><option value="read_only">{tx('只读')}</option>
                  <option value="read_write">{tx('读写')}</option><option value="full_control">{tx('完全控制')}</option><option value="none">{tx('取消共享')}</option>
                </select>
              </div>;
              })}
            </fieldset>
          </fieldset>
          {confirmation && <div className="rounded-xl border border-amber-200 dark:border-amber-800 bg-amber-50 dark:bg-amber-950/30 p-3 space-y-2 text-xs">
            <p>{tx('以下账户仍有余额，是否隐藏并保存全部修改？')}</p>
            {confirmation.accounts.map(account => <p key={account.account_id} className="break-words">{account.account_name} · {privacyMode ? '••••' : formatCurrency(account.balance, currencySymbol(account.currency))} {account.currency}</p>)}
            <Button size="sm" variant="secondary" disabled={saving} onClick={() => setConfirmation(null)}>{tx('返回修改')}</Button>
          </div>}
          <div className="flex justify-end gap-2 border-t border-zinc-100 dark:border-zinc-800 pt-3">
            <Button variant="secondary" size="sm" disabled={saving} onClick={close}>{tx('取消')}</Button>
            {confirmation ? <Button size="sm" loading={saving} onClick={() => save({ ...confirmation.payload, confirm_nonzero_balance: true })}>{tx('确认隐藏并保存')}</Button>
              : <Button size="sm" type="submit" loading={saving} disabled={!hasChanges || accounts.length > 200}>{tx('保存配置')}</Button>}
          </div>
        </form>
      </div>
    </div>, document.body,
  );
}
