import React, { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  CreditCard,
  Wallet,
  Plus,
  ChevronRight,
  ShieldCheck,
  Building2,
  TrendingDown,
  TrendingUp,
  X,
  ExternalLink,
} from 'lucide-react';
import { fetchWithAuth } from '../api/fetchWithAuth';
import { Button, Pill, Modal } from './ds/DesignSystem';
import { useCurrency } from '../CurrencyContext';

export default function AccountsPanel({
  selectedAccountId,
  onSelectAccount,
  onClose,
  isMobileDrawer = false,
}) {
  const navigate = useNavigate();
  const { fmt } = useCurrency();

  const [accounts, setAccounts] = useState([]);
  const [loading, setLoading] = useState(true);
  const [modalOpen, setModalOpen] = useState(false);
  const [activeTab, setActiveTab] = useState('all'); // all | asset | liability

  // Form state
  const [form, setForm] = useState({
    name: '',
    institution_name: '招商银行',
    account_type: 'checking',
    classification: 'asset',
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
      console.error('Failed to load accounts', err);
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

  const assets = accounts.filter((a) => a.classification === 'asset' || a.account_type === 'checking' || a.account_type === 'savings');
  const liabilities = accounts.filter((a) => a.classification === 'liability' || a.account_type === 'credit_card' || a.account_type === 'loan');

  const filteredAccounts = activeTab === 'asset' ? assets : activeTab === 'liability' ? liabilities : accounts;

  const totalTxCount = accounts.reduce((sum, a) => sum + (a.transaction_count || 0), 0);

  return (
    <div className="flex flex-col h-full select-none">
      {/* Header */}
      <div className="flex items-center justify-between p-4 pb-2 border-b border-outline/10">
        <div>
          <h2 className="text-sm font-bold text-on-surface tracking-tight flex items-center gap-1.5 font-headline">
            <Building2 className="w-4 h-4 text-primary" />
            <span>我的银行卡 / 账户</span>
          </h2>
          <p className="text-[11px] text-on-surface-variant mt-0.5">
            共绑定 {accounts.length} 张卡号 • {totalTxCount} 笔流水
          </p>
        </div>

        <div className="flex items-center gap-1">
          <button
            onClick={() => setModalOpen(true)}
            title="绑定新卡号"
            className="p-1.5 rounded-lg bg-primary/10 hover:bg-primary/20 text-primary transition-colors"
          >
            <Plus className="w-4 h-4" />
          </button>
          {isMobileDrawer && onClose && (
            <button
              onClick={onClose}
              className="p-1.5 rounded-lg hover:bg-surface-container text-on-surface-variant"
            >
              <X className="w-4 h-4" />
            </button>
          )}
        </div>
      </div>

      {/* Tabs (All / Assets / Liabilities) */}
      <div className="flex px-4 pt-2.5 gap-2 border-b border-outline/10 text-xs">
        {[
          { key: 'all', label: `全部 (${accounts.length})` },
          { key: 'asset', label: `借记卡 (${assets.length})` },
          { key: 'liability', label: `信用卡 (${liabilities.length})` },
        ].map((t) => (
          <button
            key={t.key}
            onClick={() => setActiveTab(t.key)}
            className={`pb-2 font-semibold transition-colors border-b-2 ${
              activeTab === t.key
                ? 'border-primary text-primary'
                : 'border-transparent text-on-surface-variant hover:text-on-surface'
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>

      {/* Account Cards List */}
      <div className="flex-1 overflow-y-auto p-3 space-y-2 scrollbar-none">
        {/* "All Accounts" Option */}
        <div
          onClick={() => {
            if (onSelectAccount) {
              onSelectAccount(null);
            } else {
              navigate('/transactions');
            }
            if (isMobileDrawer) onClose?.();
          }}
          className={`p-3 rounded-xl border cursor-pointer transition-all duration-150 flex items-center justify-between ${
            !selectedAccountId
              ? 'bg-primary/10 border-primary/40 shadow-xs'
              : 'bg-surface-container-lowest hover:bg-surface-container/60 border-outline/10'
          }`}
        >
          <div className="flex items-center gap-2.5 min-w-0">
            <div className="w-8 h-8 rounded-lg bg-surface-container flex items-center justify-center text-on-surface shrink-0">
              <Wallet className="w-4 h-4" />
            </div>
            <div className="min-w-0">
              <div className="text-xs font-bold text-on-surface truncate">
                全部卡号流水
              </div>
              <div className="text-[10px] text-on-surface-variant">
                综合家庭总账本
              </div>
            </div>
          </div>

          <div className="text-right shrink-0 font-mono text-xs font-bold text-primary">
            {totalTxCount} 笔
          </div>
        </div>

        {/* Individual Card Items */}
        {filteredAccounts.map((acc) => {
          const isSelected = selectedAccountId === acc.id;
          const isCredit = acc.account_type === 'credit_card' || acc.classification === 'liability';

          return (
            <div
              key={acc.id}
              onClick={() => {
                if (onSelectAccount) {
                  onSelectAccount(acc);
                } else {
                  navigate(`/transactions?account_id=${acc.id}`);
                }
                if (isMobileDrawer) onClose?.();
              }}
              className={`p-3 rounded-xl border cursor-pointer transition-all duration-150 flex items-center justify-between group ${
                isSelected
                  ? 'bg-primary/10 border-primary/40 shadow-xs ring-1 ring-primary/30'
                  : 'bg-surface-container-lowest hover:bg-surface-container/60 border-outline/10'
              }`}
            >
              <div className="flex items-center gap-2.5 min-w-0">
                <div
                  className={`w-8 h-8 rounded-lg flex items-center justify-center shrink-0 ${
                    isCredit
                      ? 'bg-amber-500/10 text-amber-600'
                      : 'bg-emerald-500/10 text-emerald-600'
                  }`}
                >
                  <CreditCard className="w-4 h-4" />
                </div>

                <div className="min-w-0">
                  <div className="text-xs font-bold text-on-surface truncate flex items-center gap-1.5">
                    <span>{acc.institution_name}</span>
                    <span className="font-mono text-primary font-bold">*{acc.mask}</span>
                  </div>
                  <div className="text-[10px] text-on-surface-variant flex items-center gap-1.5 mt-0.5">
                    <span className="capitalize">{isCredit ? '信用卡' : '借记卡'}</span>
                    <span>•</span>
                    <span className="font-mono">{acc.transaction_count || 0} 笔明细</span>
                  </div>
                </div>
              </div>

              <div className="text-right shrink-0">
                <span className="text-xs font-bold font-mono block text-on-surface">
                  {fmt(acc.balance || 0)}
                </span>
                <span className="text-[10px] text-emerald-600 font-semibold flex items-center justify-end gap-1">
                  <span>正常</span>
                  <ChevronRight className="w-3 h-3 text-on-surface-variant opacity-0 group-hover:opacity-100 transition-opacity" />
                </span>
              </div>
            </div>
          );
        })}
      </div>

      {/* Add Card Modal */}
      {modalOpen && (
        <Modal
          isOpen={modalOpen}
          onClose={() => setModalOpen(false)}
          title="添加新银行卡 / 账户"
        >
          <form onSubmit={handleCreateAccount} className="space-y-4">
            <div>
              <label className="block text-xs font-bold uppercase tracking-wider text-on-surface-variant mb-1">
                账户 / 卡片名称
              </label>
              <input
                type="text"
                placeholder="例如：招商银行工资卡 (1234)"
                value={form.name}
                onChange={(e) => setForm({ ...form, name: e.target.value })}
                required
                className="w-full px-3 py-2 text-sm bg-surface-container rounded-xl border border-outline/15 outline-none focus:border-primary text-on-surface"
              />
            </div>

            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="block text-xs font-bold uppercase tracking-wider text-on-surface-variant mb-1">
                  开户银行
                </label>
                <input
                  type="text"
                  placeholder="招商银行"
                  value={form.institution_name}
                  onChange={(e) => setForm({ ...form, institution_name: e.target.value })}
                  className="w-full px-3 py-2 text-sm bg-surface-container rounded-xl border border-outline/15 outline-none focus:border-primary text-on-surface"
                />
              </div>

              <div>
                <label className="block text-xs font-bold uppercase tracking-wider text-on-surface-variant mb-1">
                  卡片类型
                </label>
                <select
                  value={form.account_type}
                  onChange={(e) => setForm({ ...form, account_type: e.target.value })}
                  className="w-full px-3 py-2 text-sm bg-surface-container rounded-xl border border-outline/15 outline-none focus:border-primary text-on-surface cursor-pointer"
                >
                  <option value="checking">借记卡 / 活期</option>
                  <option value="credit_card">信用卡</option>
                  <option value="savings">储蓄卡 / 定期</option>
                  <option value="investment">投资理财账户</option>
                  <option value="loan">贷款本金账户</option>
                </select>
              </div>
            </div>

            <div>
              <label className="block text-xs font-bold uppercase tracking-wider text-on-surface-variant mb-1">
                当前余额 (CNY)
              </label>
              <input
                type="number"
                step="0.01"
                placeholder="0.00"
                value={form.balance}
                onChange={(e) => setForm({ ...form, balance: e.target.value })}
                className="w-full px-3 py-2 text-sm bg-surface-container rounded-xl border border-outline/15 outline-none focus:border-primary text-on-surface font-mono"
              />
            </div>

            <div className="flex justify-end gap-2 pt-2">
              <Button variant="secondary" size="sm" onClick={() => setModalOpen(false)}>
                取消
              </Button>
              <Button variant="primary" size="sm" type="submit">
                确认绑定
              </Button>
            </div>
          </form>
        </Modal>
      )}
    </div>
  );
}
