import { tx, useLocale } from "../localization.js";
import { apiErrorMessage } from '../api/errorMessages';
import React, { useState, useEffect, useRef } from 'react';
import { X, AlertTriangle, ArrowRightLeft, Edit3, Upload } from 'lucide-react';
import { fetchWithAuth } from '../api/fetchWithAuth';
import { useToast } from '../ToastContext';
import { useCurrency } from '../UserPreferencesContext';
import { toLocalISODate } from '../utils/dates';
import AccountSelectDropdown from './AccountSelectDropdown';
import AccountTypeSelectDropdown from './AccountTypeSelectDropdown';
import ExternalIdentifierField from './ExternalIdentifierField';

/**
 * 1. 编辑账户基本信息弹窗
 */
export function EditAccountModal({ isOpen, onClose, account, onSuccess }) {
  useLocale();
  const { showToast } = useToast();
  const { currencies } = useCurrency();
  const [name, setName] = useState('');
  const [institutionName, setInstitutionName] = useState('');
  const [externalIdentifier, setExternalIdentifier] = useState('');
  const externalIdentifierEdited = useRef(false);
  const [accountType, setAccountType] = useState('checking');
  const [accountTypeEdited, setAccountTypeEdited] = useState(false);
  const [currency, setCurrency] = useState('CNY');
  const [currencyEdited, setCurrencyEdited] = useState(false);
  const [balance, setBalance] = useState('0');
  const [balanceEdited, setBalanceEdited] = useState(false);
  const [parentAccountId, setParentAccountId] = useState('');
  const parentAccountEdited = useRef(false);
  const [currentParent, setCurrentParent] = useState(null);
  const [parentsLoading, setParentsLoading] = useState(false);
  const [candidateParents, setCandidateParents] = useState([]);
  const [submitting, setSubmitting] = useState(false);

  const normalizeAccountTypeForSelect = (val) => {
    const t = String(val || '').toLowerCase();
    if (['cash', 'checking', 'savings', '现金'].includes(t)) return 'cash';
    if (['iou', 'receivable', 'loan_receivable', '借据', '借出款'].includes(t)) return 'iou';
    if (['investment', 'brokerage', 'mutual_fund', 'stock', '投资'].includes(t)) return 'investment';
    if (['crypto', 'cryptocurrency', '加密资产'].includes(t)) return 'crypto';
    if (['real_estate', 'property', 'house', '房产'].includes(t)) return 'real_estate';
    if (['vehicle', 'car', '车辆'].includes(t)) return 'vehicle';
    if (['other_asset', '其他资产'].includes(t)) return 'other_asset';
    if (['credit_card', 'credit', '信用卡'].includes(t)) return 'credit_card';
    if (['loan', 'mortgage', '贷款'].includes(t)) return 'loan';
    if (['other_liability', '其他负债'].includes(t)) return 'other_liability';
    return 'cash';
  };

  useEffect(() => {
    let cancelled = false;
    if (account?.can_manage === true && isOpen) {
      setName(account.name || '');
      setInstitutionName(account.institution_name || '');
      setExternalIdentifier(account.external_identifier || '');
      externalIdentifierEdited.current = false;
      setAccountType(normalizeAccountTypeForSelect(account.account_type));
      setAccountTypeEdited(false);
      setCurrency(account.currency || 'CNY');
      setCurrencyEdited(false);
      setBalance(account.balance ? String(account.balance) : '0');
      setBalanceEdited(false);
      setParentAccountId(account.parent_account_id ? String(account.parent_account_id) : '');
      parentAccountEdited.current = false;
      setCurrentParent(account.parent_account || null);
      setCandidateParents([]);
      setParentsLoading(true);

      // 获取当前家庭所有账户供选择父级主账户（排除自己及子账户）
      fetchWithAuth('/api/v1/accounts')
        .then((res) => (res.ok ? res.json() : null))
        .then((data) => {
          if (!data || cancelled) return;
          const list = Array.isArray(data) ? data : data.accounts || data.items || [];
          const latest = list.find((a) => String(a.id) === String(account.id));
          if (latest) {
            if (!externalIdentifierEdited.current) setExternalIdentifier(latest.external_identifier || '');
            if (!parentAccountEdited.current) setParentAccountId(latest.parent_account_id || '');
            setCurrentParent(latest.parent_account || null);
          }
          const candidates = list.filter((a) => a.id !== account.id && a.can_manage === true && !a.parent_account_id && ['credit_card', '信用卡'].includes(a.account_type));
          setCandidateParents(candidates);
        })
        .catch(() => {})
        .finally(() => { if (!cancelled) setParentsLoading(false); });
    }
    return () => { cancelled = true; };
  }, [account, isOpen]);

  if (!isOpen || !account || account.can_manage !== true) return null;

  const handleSubmit = async (e) => {
    e.preventDefault();
    try {
      setSubmitting(true);
      const res = await fetchWithAuth(`/api/v1/accounts/${account.id}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          name: name.trim(),
          institution_name: institutionName.trim(),
          ...(externalIdentifierEdited.current ? { external_identifier: externalIdentifier.trim() || null } : {}),
          ...(accountTypeEdited ? { account_type: accountType } : {}),
          ...(currencyEdited ? { currency } : {}),
          ...(balanceEdited ? { balance } : {}),
          ...(parentAccountEdited.current ? { parent_account_id: parentAccountId ? parentAccountId.trim() : '', historical_settlement_policy: 'convert_verified' } : {}),
        }),
      });

      if (res.ok) {
        showToast(tx("账户信息已成功更新"), 'success');
        window.dispatchEvent(new CustomEvent('accounts-updated'));
        if (onSuccess) onSuccess();
        onClose();
      } else {
        const err = await res.json();
        showToast(tx(apiErrorMessage(err.detail, '更新失败')), 'error');
      }
    } catch {
      showToast(tx("网络请求错误"), 'error');
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 overflow-y-auto flex items-center justify-center p-4">
      <div className="fixed inset-0 bg-black/50 backdrop-blur-xs" onClick={onClose} />
      <div className="relative bg-white dark:bg-zinc-900 rounded-2xl shadow-2xl w-full max-w-md border border-zinc-200 dark:border-zinc-800 z-10 animate-in fade-in zoom-in-95 duration-150">
        <div className="px-6 py-4 border-b border-zinc-100 dark:border-zinc-800 flex items-center justify-between">
          <h3 className="text-base font-bold text-zinc-900 dark:text-zinc-100 flex items-center gap-2">
            <Edit3 className="w-4 h-4 text-zinc-500" />
            <span>{tx("编辑账户信息")}</span>
          </h3>
          <button onClick={onClose} className="p-1 rounded-lg text-zinc-400 hover:text-zinc-700 dark:hover:text-zinc-200 hover:bg-zinc-100 dark:hover:bg-zinc-800">
            <X className="w-4 h-4" />
          </button>
        </div>

        <form onSubmit={handleSubmit} className="p-6 space-y-4 text-xs">
          <div>
            <label className="block text-xs font-medium text-zinc-600 dark:text-zinc-400 mb-1">{tx("账户名称")}</label>
            <input
              type="text"
              required
              value={name}
              onChange={(e) => setName(e.target.value)}
              className="w-full px-3 py-2 rounded-lg border border-zinc-200 dark:border-zinc-700 bg-white dark:bg-zinc-800 text-zinc-900 dark:text-white text-xs focus:ring-1 focus:ring-zinc-900"
            />
          </div>

          <div>
            <label className="block text-xs font-medium text-zinc-600 dark:text-zinc-400 mb-1">{tx("金融机构 / 银行")}</label>
            <input
              type="text"
              required
              value={institutionName}
              onChange={(e) => setInstitutionName(e.target.value)}
              className="w-full px-3 py-2 rounded-lg border border-zinc-200 dark:border-zinc-700 bg-white dark:bg-zinc-800 text-zinc-900 dark:text-white text-xs focus:ring-1 focus:ring-zinc-900"
            />
          </div>

          <ExternalIdentifierField
            id="edit-account-external-identifier"
            value={externalIdentifier}
            onChange={(value) => {
              externalIdentifierEdited.current = true;
              setExternalIdentifier(value);
            }}
          />

          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block text-xs font-medium text-zinc-600 dark:text-zinc-400 mb-1">{tx("账户类型")}</label>
              <AccountTypeSelectDropdown
                name="account_type"
                value={accountType}
                onChange={(e) => {
                  const newType = e.target.value;
                  setAccountType(newType);
                  setAccountTypeEdited(true);
                  if (newType !== 'credit_card') {
                    parentAccountEdited.current = true;
                    setParentAccountId('');
                  }
                }}
                testId="edit-account-type-select"
                useShortLabel
              />
            </div>

            <div>
              <label className="block text-xs font-medium text-zinc-600 dark:text-zinc-400 mb-1">{tx("账户币种")}</label>
              <select
                value={currency}
                onChange={(e) => {
                  setCurrency(e.target.value);
                  setCurrencyEdited(true);
                }}
                className="w-full px-3 py-2 rounded-lg border border-zinc-200 dark:border-zinc-700 bg-white dark:bg-zinc-800 text-zinc-900 dark:text-white text-xs focus:ring-1 focus:ring-zinc-900 cursor-pointer"
              >
                {(currencies || []).map((c) => (
                  <option key={c.code} value={c.code}>
                    {c.code} ({c.symbol}) - {c.name}
                  </option>
                ))}
              </select>
            </div>
          </div>

          {accountType === 'credit_card' && (
            <div>
              <div className="flex items-center justify-between mb-1">
                <label className="text-xs font-medium text-zinc-600 dark:text-zinc-400">{tx("所属信用卡主卡 (可选)")}</label>
                {parentAccountId && (
                  <span className="text-[10px] font-semibold text-amber-600 dark:text-amber-400 bg-amber-50 dark:bg-amber-950/60 px-1.5 py-0.5 rounded">{tx("附属卡")}</span>
                )}
              </div>
              <AccountSelectDropdown
                name="parent_account_id"
                value={parentAccountId}
                onChange={(e) => {
                  parentAccountEdited.current = true;
                  setParentAccountId(e.target.value);
                }}
                accounts={candidateParents}
                selectedAccountFallback={currentParent ? { ...currentParent, is_owner: false, relationship_only: true } : null}
                disabled={parentsLoading}
                emptyLabel={tx("无 (独立主卡)")}
                placeholder={tx("选择所属信用卡主卡")}
                testId="edit-account-parent-select"
              />
              <p className="mt-1 text-[11px] text-zinc-400">{tx("请先共享给主卡所有者，再设置为副卡。取消共享会解除副卡关系。更改外币主卡会按交易日期固定结算历史流水，未核实原币的记录需先核对。")}</p>
            </div>
          )}

          <div>
            <label className="block text-xs font-medium text-zinc-600 dark:text-zinc-400 mb-1">{tx("当前余额 (")} {currencies?.find((c) => c.code === currency)?.symbol || '¥'})
            </label>
            <input
              type="number"
              required
              step="0.01"
              value={balance}
              onChange={(e) => {
                setBalance(e.target.value);
                setBalanceEdited(true);
              }}
              className="w-full px-3 py-2 rounded-lg border border-zinc-200 dark:border-zinc-700 bg-white dark:bg-zinc-800 font-mono text-zinc-900 dark:text-white text-xs focus:ring-1 focus:ring-zinc-900"
            />
            <p className="mt-1 text-[11px] text-zinc-400">{tx("修改此金额会新增余额调整记录；仅修改账户资料不会改变余额。")}</p>
          </div>

          <div className="pt-2 flex justify-end gap-2">
            <button
              type="button"
              onClick={onClose}
              className="px-3.5 py-2 rounded-lg border border-zinc-200 dark:border-zinc-700 text-zinc-600 dark:text-zinc-300 hover:bg-zinc-100 dark:hover:bg-zinc-800 text-xs font-medium"
            >{tx("取消")}</button>
            <button
              type="submit"
              disabled={submitting}
              className="px-4 py-2 rounded-lg bg-zinc-900 dark:bg-white text-white dark:text-zinc-900 hover:bg-zinc-800 dark:hover:bg-zinc-100 text-xs font-semibold shadow-xs disabled:opacity-50"
            >
              {submitting ? tx("保存中...") : tx("保存更改")}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

/**
 * 2. 转移账户所有权弹窗
 */
export function TransferOwnershipModal({ isOpen, onClose, account, onSuccess }) {
  useLocale();
  const { showToast } = useToast();
  const [members, setMembers] = useState([]);
  const [selectedUserId, setSelectedUserId] = useState('');
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    if (isOpen && account?.can_manage_shares === true) {
      fetchWithAuth('/api/v1/family/current')
        .then((res) => res.json())
        .then((data) => {
          const list = data.members || [];
          const currentOwnerId = account.owner_id || account.ownerId;
          const currentOwnerName = account.owner || account.owner_name;
          const candidates = list.filter((m) => {
            if (currentOwnerId && (String(m.id) === String(currentOwnerId) || String(m.user_id) === String(currentOwnerId))) {
              return false;
            }
            if (!currentOwnerId && currentOwnerName && (m.username === currentOwnerName || m.display_name === currentOwnerName)) {
              return false;
            }
            return true;
          });
          setMembers(candidates);
          if (candidates.length > 0) {
            setSelectedUserId(candidates[0].id);
          }
        })
        .catch((err) => {
          console.error('Failed to load family members for transfer', err);
        });
    }
  }, [isOpen, account]);

  if (!isOpen || !account || account.can_manage_shares !== true) return null;

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!selectedUserId) {
      showToast(tx("请选择目标成员"), 'error');
      return;
    }

    try {
      setSubmitting(true);
      const res = await fetchWithAuth(`/api/v1/accounts/${account.id}/transfer-ownership`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ new_owner_id: selectedUserId }),
      });

      if (res.ok) {
        showToast(tx("账户所有权已成功转移"), 'success');
        window.dispatchEvent(new CustomEvent('accounts-updated'));
        if (onSuccess) onSuccess();
        onClose();
      } else {
        const err = await res.json();
        showToast(tx(apiErrorMessage(err.detail, '转移失败')), 'error');
      }
    } catch {
      showToast(tx("网络请求错误"), 'error');
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 overflow-y-auto flex items-center justify-center p-4">
      <div className="fixed inset-0 bg-black/50 backdrop-blur-xs" onClick={onClose} />
      <div className="relative bg-white dark:bg-zinc-900 rounded-2xl shadow-2xl w-full max-w-md border border-zinc-200 dark:border-zinc-800 overflow-hidden z-10 animate-in fade-in zoom-in-95 duration-150">
        <div className="px-6 py-4 border-b border-zinc-100 dark:border-zinc-800 flex items-center justify-between">
          <h3 className="text-base font-bold text-zinc-900 dark:text-zinc-100 flex items-center gap-2">
            <ArrowRightLeft className="w-4 h-4 text-zinc-500" />
            <span>{tx("转移账户所有权")}</span>
          </h3>
          <button onClick={onClose} className="p-1 rounded-lg text-zinc-400 hover:text-zinc-700 dark:hover:text-zinc-200 hover:bg-zinc-100 dark:hover:bg-zinc-800">
            <X className="w-4 h-4" />
          </button>
        </div>

        <form onSubmit={handleSubmit} className="p-6 space-y-4 text-xs sm:text-sm">
          <p className="text-xs text-zinc-500">{tx("将当前账户")} <span className="font-semibold text-zinc-900 dark:text-white">“{account.name}”</span> {tx("的所有权移交给家庭组其他成员。转移后，您将自动保留该账户的完全控制权限。")}</p>

          <div>
            <label className="block text-xs font-medium text-zinc-600 dark:text-zinc-400 mb-1">{tx("选择新所有者 (家庭组成员)")}</label>
            {members.length === 0 ? (
              <p className="text-xs text-zinc-400 py-2">{tx("家庭组暂无其他成员可供转移")}</p>
            ) : (
              <select
                value={selectedUserId}
                onChange={(e) => setSelectedUserId(e.target.value)}
                className="w-full px-3 py-2 rounded-lg border border-zinc-200 dark:border-zinc-700 bg-white dark:bg-zinc-800 text-zinc-900 dark:text-white text-xs sm:text-sm focus:ring-1 focus:ring-zinc-900"
              >
                {members.map((m) => (
                  <option key={m.id} value={m.id}>
                    {m.display_name || m.username} ({m.username})
                  </option>
                ))}
              </select>
            )}
          </div>

          <div className="pt-2 flex justify-end gap-2">
            <button
              type="button"
              onClick={onClose}
              className="px-3.5 py-2 rounded-lg border border-zinc-200 dark:border-zinc-700 text-zinc-600 dark:text-zinc-300 hover:bg-zinc-100 dark:hover:bg-zinc-800 text-xs font-medium"
            >{tx("取消")}</button>
            <button
              type="submit"
              disabled={submitting || members.length === 0}
              className="px-4 py-2 rounded-lg bg-zinc-900 dark:bg-white text-white dark:text-zinc-900 hover:bg-zinc-800 dark:hover:bg-zinc-100 text-xs font-semibold shadow-xs disabled:opacity-50"
            >
              {submitting ? tx("转移中...") : tx("确认转移所有权")}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

/**
 * 3. 删除账户确认弹窗
 */
export function DeleteAccountModal({ isOpen, onClose, account, onSuccess }) {
  useLocale();
  const { showToast } = useToast();
  const [submitting, setSubmitting] = useState(false);

  if (!isOpen || !account) return null;

  const handleDelete = async () => {
    try {
      setSubmitting(true);
      const res = await fetchWithAuth(`/api/v1/accounts/${account.id}`, {
        method: 'DELETE',
      });

      if (res.ok) {
        showToast(tx("账户已成功删除"), 'success');
        window.dispatchEvent(
          new CustomEvent('accounts-updated', {
            detail: { deletedAccountId: account.id },
          })
        );
        if (onSuccess) onSuccess();
        onClose();
      } else {
        const err = await res.json();
        showToast(tx(apiErrorMessage(err.detail, '删除失败')), 'error');
      }
    } catch {
      showToast(tx("网络请求错误"), 'error');
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 overflow-y-auto flex items-center justify-center p-4">
      <div className="fixed inset-0 bg-black/50 backdrop-blur-xs" onClick={onClose} />
      <div className="relative bg-white dark:bg-zinc-900 rounded-2xl shadow-2xl w-full max-w-sm border border-red-200 dark:border-red-900/50 overflow-hidden z-10 animate-in fade-in zoom-in-95 duration-150">
        <div className="p-6 space-y-4">
          <div className="w-10 h-10 rounded-full bg-red-100 dark:bg-red-950/50 text-red-600 dark:text-red-400 flex items-center justify-center">
            <AlertTriangle className="w-5 h-5" />
          </div>

          <div>
            <h3 className="text-base font-bold text-zinc-900 dark:text-zinc-100">{tx("确定要删除此账户吗？")}</h3>
            <p className="mt-1 text-xs text-zinc-500">{tx("您即将删除账户")} <span className="font-semibold text-zinc-800 dark:text-zinc-200">“{account.name}”</span> {tx("。相关的共享权限将被一并移除。此操作无法撤销。")}</p>
          </div>

          <div className="pt-2 flex justify-end gap-2">
            <button
              type="button"
              onClick={onClose}
              className="px-3.5 py-2 rounded-lg border border-zinc-200 dark:border-zinc-700 text-zinc-600 dark:text-zinc-300 hover:bg-zinc-100 dark:hover:bg-zinc-800 text-xs font-medium"
            >{tx("取消")}</button>
            <button
              type="button"
              onClick={handleDelete}
              disabled={submitting}
              className="px-4 py-2 rounded-lg bg-red-600 hover:bg-red-700 text-white text-xs font-semibold shadow-xs disabled:opacity-50"
            >
              {submitting ? tx("删除中...") : tx("确认删除")}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

/**
 * 4. 账单导入弹窗 (对标 Sure CSV / 微信 / 支付宝导入)
 */
export function ImportTransactionsModal({ isOpen, onClose, account, onSuccess }) {
  useLocale();
  const { showToast } = useToast();
  const [importText, setImportText] = useState('');
  const [submitting, setSubmitting] = useState(false);

  if (!isOpen || !account) return null;

  const handleImport = async (e) => {
    e.preventDefault();
    if (!importText.trim()) {
      showToast(tx("请粘贴账单内容或账单流水文本"), 'error');
      return;
    }

    try {
      setSubmitting(true);
      // 调用批量创建或导入流水接口
      const lines = importText.split('\n').filter((l) => l.trim().length > 0);
      let importedCount = 0;

      for (const line of lines) {
        // 简单提取金额和描述
        const match = line.match(/(\d{4}[-/]\d{2}[-/]\d{2})?[^\d]*([+-]?\d+(?:\.\d{1,2})?)/);
        const amt = match ? Math.abs(parseFloat(match[2])) : 10.0;
        const txDate = match && match[1] ? match[1].replace(/\//g, '-') : toLocalISODate(new Date());
        await fetchWithAuth('/api/v1/transactions', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            account_id: account.id,
            name: line.slice(0, 30),
            amount: amt,
            transaction_type: 'expense',
            transacted_at: txDate,
          }),
        });
        importedCount++;
      }

      showToast(tx("已成功导入 {p0} 笔流水", {p0: (importedCount)}), 'success');
      if (onSuccess) onSuccess();
      onClose();
    } catch {
      showToast(tx("导入失败，请检查格式"), 'error');
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 overflow-y-auto flex items-center justify-center p-4">
      <div className="fixed inset-0 bg-black/50 backdrop-blur-xs" onClick={onClose} />
      <div className="relative bg-white dark:bg-zinc-900 rounded-2xl shadow-2xl w-full max-w-md border border-zinc-200 dark:border-zinc-800 overflow-hidden z-10 animate-in fade-in zoom-in-95 duration-150">
        <div className="px-6 py-4 border-b border-zinc-100 dark:border-zinc-800 flex items-center justify-between">
          <h3 className="text-base font-bold text-zinc-900 dark:text-zinc-100 flex items-center gap-2">
            <Upload className="w-4 h-4 text-zinc-500" />
            <span>{tx("导入交易记录 ·")} {account.name}</span>
          </h3>
          <button onClick={onClose} className="p-1 rounded-lg text-zinc-400 hover:text-zinc-700 dark:hover:text-zinc-200 hover:bg-zinc-100 dark:hover:bg-zinc-800">
            <X className="w-4 h-4" />
          </button>
        </div>

        <form onSubmit={handleImport} className="p-6 space-y-4 text-xs sm:text-sm">
          <p className="text-xs text-zinc-500">{tx("支持粘贴微信支付账单、支付宝账单或银行卡明细文本，系统将智能提取金额与商户。")}</p>

          <div>
            <textarea
              rows={5}
              placeholder={tx("在此粘贴账单明细文本...")}
              value={importText}
              onChange={(e) => setImportText(e.target.value)}
              className="w-full px-3 py-2 rounded-lg border border-zinc-200 dark:border-zinc-700 bg-white dark:bg-zinc-800 text-zinc-900 dark:text-white text-xs font-mono focus:ring-1 focus:ring-zinc-900"
            />
          </div>

          <div className="pt-2 flex justify-end gap-2">
            <button
              type="button"
              onClick={onClose}
              className="px-3.5 py-2 rounded-lg border border-zinc-200 dark:border-zinc-700 text-zinc-600 dark:text-zinc-300 hover:bg-zinc-100 dark:hover:bg-zinc-800 text-xs font-medium"
            >{tx("取消")}</button>
            <button
              type="submit"
              disabled={submitting}
              className="px-4 py-2 rounded-lg bg-zinc-900 dark:bg-white text-white dark:text-zinc-900 hover:bg-zinc-800 dark:hover:bg-zinc-100 text-xs font-semibold shadow-xs disabled:opacity-50"
            >
              {submitting ? tx("解析导入中...") : tx("开始导入")}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
