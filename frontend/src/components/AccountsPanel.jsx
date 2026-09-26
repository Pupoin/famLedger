import React, { useState, useEffect } from 'react';
import { useNavigate, useLocation } from 'react-router-dom';
import {
  CreditCard,
  Wallet,
  Plus,
  ChevronRight,
  ChevronDown,
  Building2,
  X,
  Layers,
} from 'lucide-react';
import { fetchWithAuth } from '../api/fetchWithAuth';
import { Modal, Button } from './ds/DesignSystem';
import { useCurrency } from '../CurrencyContext';

export default function AccountsPanel({
  selectedAccountId,
  onSelectAccount,
  onClose,
  isMobileDrawer = false,
}) {
  const navigate = useNavigate();
  const location = useLocation();
  const { fmt, privacyMode } = useCurrency();

  const [accounts, setAccounts] = useState([]);
  const [loading, setLoading] = useState(true);
  const [activeTab, setActiveTab] = useState('asset'); // 'all' | 'asset' | 'liability'
  const [modalOpen, setModalOpen] = useState(false);

  // Group expand states
  const [cashExpanded, setCashExpanded] = useState(true);
  const [creditExpanded, setCreditExpanded] = useState(true);

  // New account form
  const [form, setForm] = useState({
    name: '',
    institution_name: '招商银行',
    account_type: 'checking',
    currency: 'CNY',
    balance: '0',
  });

  const fetchAccounts = async () => {
    try {
      setLoading(true);
      const res = await fetchWithAuth('/api/v1/accounts');
      if (res.ok) {
        const data = await res.json();
        setAccounts(Array.isArray(data) ? data : (data.accounts || data.items || []));
      }
    } catch (err) {
      console.error('Failed to load accounts in SureAccountsPanel', err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchAccounts();
  }, []);

  const handleCreateAccount = async (e) => {
    e.preventDefault();
    try {
      const res = await fetchWithAuth('/api/v1/accounts', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          name: form.name,
          institution_name: form.institution_name,
          account_type: form.account_type,
          currency: form.currency,
          balance: Number(form.balance) || 0,
        }),
      });
      if (res.ok) {
        setModalOpen(false);
        fetchAccounts();
      }
    } catch (err) {
      console.error('Failed to create account', err);
    }
  };

  // Grouping accounts
  const assets = accounts.filter(
    (a) => a.classification === 'asset' || a.account_type === 'checking' || a.account_type === 'savings'
  );
  const liabilities = accounts.filter(
    (a) => a.classification === 'liability' || a.account_type === 'credit_card' || a.account_type === 'loan'
  );

  const totalAssets = assets.reduce((sum, a) => sum + Number(a.balance || 0), 0);
  const totalLiabilities = liabilities.reduce((sum, a) => sum + Number(a.balance || 0), 0);

  const handleAccountClick = (acc) => {
    if (onSelectAccount) {
      onSelectAccount(acc);
    } else {
      navigate(acc ? `/transactions?account_id=${acc.id}` : '/transactions');
    }
    if (isMobileDrawer && onClose) {
      onClose();
    }
  };

  return (
    <div className="flex flex-col h-full bg-white dark:bg-zinc-900 text-zinc-900 dark:text-zinc-100 select-none border-r border-zinc-200/80 dark:border-zinc-800">
      {/* ── 1. Top Three-way Segmented Pills (Exact Sure Design) ── */}
      <div className="p-4 pb-2">
        <div className="flex items-center p-1 bg-zinc-100 dark:bg-zinc-800/80 rounded-xl">
          {[
            { id: 'all', label: 'All' },
            { id: 'asset', label: 'Assets' },
            { id: 'liability', label: 'Debts' },
          ].map((t) => (
            <button
              key={t.id}
              onClick={() => setActiveTab(t.id)}
              className={`flex-1 py-1.5 text-xs font-semibold rounded-lg text-center transition-all ${
                activeTab === t.id
                  ? 'bg-white dark:bg-zinc-700 text-zinc-900 dark:text-white shadow-xs'
                  : 'text-zinc-500 hover:text-zinc-900 dark:hover:text-zinc-200'
              }`}
            >
              {t.label}
            </button>
          ))}
        </div>
      </div>

      {/* ── 2. Accounts Header & New Asset Action (Sure Layout) ── */}
      <div className="px-4 py-2 flex items-center justify-between">
        <span className="text-sm font-bold text-zinc-900 dark:text-zinc-100">
          Accounts
        </span>
        <button
          onClick={() => {}}
          className="text-xs text-zinc-500 hover:text-zinc-800 dark:hover:text-zinc-300 flex items-center gap-1 transition-colors"
        >
          <span>By type</span>
          <ChevronDown className="w-3 h-3" />
        </button>
      </div>

      <div className="px-4 pb-2">
        <button
          onClick={() => setModalOpen(true)}
          className="text-xs font-medium text-zinc-600 dark:text-zinc-400 hover:text-zinc-900 dark:hover:text-zinc-100 flex items-center gap-1.5 py-1 px-1.5 -ml-1 rounded hover:bg-zinc-100 dark:hover:bg-zinc-800 transition-colors"
        >
          <Plus className="w-3.5 h-3.5" />
          <span>New asset</span>
        </button>
      </div>

      {/* ── 3. Accounts Hierarchy List (Exact Sure Style) ── */}
      <div className="flex-1 overflow-y-auto px-2 py-1 space-y-3 custom-scrollbar">
        {/* All Accounts Summary Shortcut */}
        <div
          onClick={() => handleAccountClick(null)}
          className={`flex items-center justify-between px-3 py-2 rounded-lg cursor-pointer transition-colors text-xs ${
            !selectedAccountId && location.pathname === '/transactions' && !location.search.includes('account_id=')
              ? 'bg-zinc-100 dark:bg-zinc-800 font-semibold'
              : 'hover:bg-zinc-50 dark:hover:bg-zinc-800/50 text-zinc-700 dark:text-zinc-300'
          }`}
        >
          <div className="flex items-center gap-2">
            <Wallet className="w-4 h-4 text-zinc-500" />
            <span>全部卡号流水</span>
          </div>
          <span className="font-mono text-zinc-400">
            {accounts.reduce((s, a) => s + (a.transaction_count || 0), 0)} 笔
          </span>
        </div>

        {/* Group A: Cash / Depositories (借记卡活期) */}
        {(activeTab === 'all' || activeTab === 'asset') && (
          <div className="space-y-1">
            {/* Group Header */}
            <div
              onClick={() => setCashExpanded(!cashExpanded)}
              className="flex items-center justify-between px-3 py-1.5 text-xs text-zinc-600 dark:text-zinc-400 font-medium hover:text-zinc-900 dark:hover:text-zinc-100 cursor-pointer"
            >
              <div className="flex items-center gap-1.5">
                {cashExpanded ? <ChevronDown className="w-3.5 h-3.5" /> : <ChevronRight className="w-3.5 h-3.5" />}
                <span className="font-semibold text-zinc-800 dark:text-zinc-200">Cash (借记卡)</span>
              </div>
              <span className="font-mono font-semibold text-zinc-900 dark:text-zinc-100">
                {fmt(totalAssets)}
              </span>
            </div>

            {/* Group Items */}
            {cashExpanded && (
              <div className="space-y-0.5 pl-2">
                {assets.map((acc) => {
                  const isCurrent =
                    selectedAccountId === acc.id || location.search.includes(`account_id=${acc.id}`);

                  return (
                    <div
                      key={acc.id}
                      onClick={() => handleAccountClick(acc)}
                      className={`flex items-center justify-between px-3 py-2 rounded-xl cursor-pointer transition-all ${
                        isCurrent
                          ? 'bg-zinc-100 dark:bg-zinc-800 font-semibold shadow-2xs'
                          : 'hover:bg-zinc-50 dark:hover:bg-zinc-800/50'
                      }`}
                    >
                      <div className="flex items-center gap-2.5 min-w-0">
                        <div className="w-7 h-7 rounded-lg bg-emerald-500/10 text-emerald-600 dark:text-emerald-400 flex items-center justify-center shrink-0">
                          <CreditCard className="w-3.5 h-3.5" />
                        </div>
                        <div className="min-w-0">
                          <p className="text-xs font-medium text-zinc-900 dark:text-zinc-100 truncate">
                            {acc.name || acc.institution_name}
                          </p>
                          <p className="text-[10px] text-zinc-500 font-mono">
                            *{acc.mask} · {acc.transaction_count || 0} 笔
                          </p>
                        </div>
                      </div>

                      <div className="text-right shrink-0">
                        <span className="text-xs font-mono font-medium block text-zinc-900 dark:text-zinc-100">
                          {fmt(acc.balance || 0)}
                        </span>
                      </div>
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        )}

        {/* Group B: Credit Cards / Debts (信用卡) */}
        {(activeTab === 'all' || activeTab === 'liability') && (
          <div className="space-y-1 pt-1">
            {/* Group Header */}
            <div
              onClick={() => setCreditExpanded(!creditExpanded)}
              className="flex items-center justify-between px-3 py-1.5 text-xs text-zinc-600 dark:text-zinc-400 font-medium hover:text-zinc-900 dark:hover:text-zinc-100 cursor-pointer"
            >
              <div className="flex items-center gap-1.5">
                {creditExpanded ? <ChevronDown className="w-3.5 h-3.5" /> : <ChevronRight className="w-3.5 h-3.5" />}
                <span className="font-semibold text-zinc-800 dark:text-zinc-200">Credit Cards (信用卡)</span>
              </div>
              <span className="font-mono font-semibold text-zinc-900 dark:text-zinc-100">
                {fmt(totalLiabilities)}
              </span>
            </div>

            {/* Group Items */}
            {creditExpanded && (
              <div className="space-y-0.5 pl-2">
                {liabilities.length === 0 ? (
                  <div className="px-3 py-2 text-[11px] text-zinc-400">暂无绑定信用卡</div>
                ) : (
                  liabilities.map((acc) => {
                    const isCurrent =
                      selectedAccountId === acc.id || location.search.includes(`account_id=${acc.id}`);

                    return (
                      <div
                        key={acc.id}
                        onClick={() => handleAccountClick(acc)}
                        className={`flex items-center justify-between px-3 py-2 rounded-xl cursor-pointer transition-all ${
                          isCurrent
                            ? 'bg-zinc-100 dark:bg-zinc-800 font-semibold shadow-2xs'
                            : 'hover:bg-zinc-50 dark:hover:bg-zinc-800/50'
                        }`}
                      >
                        <div className="flex items-center gap-2.5 min-w-0">
                          <div className="w-7 h-7 rounded-lg bg-amber-500/10 text-amber-600 dark:text-amber-400 flex items-center justify-center shrink-0">
                            <CreditCard className="w-3.5 h-3.5" />
                          </div>
                          <div className="min-w-0">
                            <p className="text-xs font-medium text-zinc-900 dark:text-zinc-100 truncate">
                              {acc.name || acc.institution_name}
                            </p>
                            <p className="text-[10px] text-zinc-500 font-mono">
                              *{acc.mask} · {acc.transaction_count || 0} 笔
                            </p>
                          </div>
                        </div>

                        <div className="text-right shrink-0">
                          <span className="text-xs font-mono font-medium block text-zinc-900 dark:text-zinc-100">
                            {fmt(acc.balance || 0)}
                          </span>
                        </div>
                      </div>
                    );
                  })
                )}
              </div>
            )}
          </div>
        )}
      </div>

      {/* ── 4. Add Account Modal ── */}
      {modalOpen && (
        <Modal
          isOpen={modalOpen}
          onClose={() => setModalOpen(false)}
          title="添加新银行卡 / 账户"
        >
          <form onSubmit={handleCreateAccount} className="space-y-4">
            <div>
              <label className="block text-xs font-bold uppercase tracking-wider text-zinc-500 mb-1">
                账户 / 卡片名称
              </label>
              <input
                type="text"
                placeholder="例如：招商银行工资卡 (1234)"
                value={form.name}
                onChange={(e) => setForm({ ...form, name: e.target.value })}
                required
                className="w-full px-3 py-2 text-sm bg-zinc-50 dark:bg-zinc-800 rounded-lg border border-zinc-200 dark:border-zinc-700 outline-none focus:border-zinc-900 dark:focus:border-white text-zinc-900 dark:text-white"
              />
            </div>

            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="block text-xs font-bold uppercase tracking-wider text-zinc-500 mb-1">
                  开户银行
                </label>
                <input
                  type="text"
                  placeholder="招商银行"
                  value={form.institution_name}
                  onChange={(e) => setForm({ ...form, institution_name: e.target.value })}
                  className="w-full px-3 py-2 text-sm bg-zinc-50 dark:bg-zinc-800 rounded-lg border border-zinc-200 dark:border-zinc-700 outline-none text-zinc-900 dark:text-white"
                />
              </div>

              <div>
                <label className="block text-xs font-bold uppercase tracking-wider text-zinc-500 mb-1">
                  卡片类型
                </label>
                <select
                  value={form.account_type}
                  onChange={(e) => setForm({ ...form, account_type: e.target.value })}
                  className="w-full px-3 py-2 text-sm bg-zinc-50 dark:bg-zinc-800 rounded-lg border border-zinc-200 dark:border-zinc-700 outline-none text-zinc-900 dark:text-white cursor-pointer"
                >
                  <option value="checking">借记卡 / 活期</option>
                  <option value="credit_card">信用卡</option>
                  <option value="savings">定期储蓄</option>
                  <option value="loan">贷款本金</option>
                </select>
              </div>
            </div>

            <div>
              <label className="block text-xs font-bold uppercase tracking-wider text-zinc-500 mb-1">
                当前余额 (CNY)
              </label>
              <input
                type="number"
                step="0.01"
                placeholder="0.00"
                value={form.balance}
                onChange={(e) => setForm({ ...form, balance: e.target.value })}
                className="w-full px-3 py-2 text-sm bg-zinc-50 dark:bg-zinc-800 rounded-lg border border-zinc-200 dark:border-zinc-700 outline-none font-mono text-zinc-900 dark:text-white"
              />
            </div>

            <div className="flex justify-end gap-2 pt-2">
              <Button variant="secondary" size="sm" onClick={() => setModalOpen(false)}>
                取消
              </Button>
              <button
                type="submit"
                className="px-3 py-1.5 text-xs font-medium rounded-lg bg-zinc-900 hover:bg-zinc-800 text-white transition-colors"
              >
                确认绑定
              </button>
            </div>
          </form>
        </Modal>
      )}
    </div>
  );
}
