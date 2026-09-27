import React, { useState, useEffect, useRef, useMemo } from 'react';
import { useNavigate, useLocation } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import {
  CreditCard,
  Wallet,
  Plus,
  ChevronRight,
  ChevronDown,
  Building2,
  X,
  Layers,
  Check,
  User,
  ArrowUpDown,
} from 'lucide-react';
import { fetchWithAuth } from '../api/fetchWithAuth';
import { Modal, Button } from './ds/DesignSystem';
import { useCurrency } from '../CurrencyContext';
import { useAuth } from '../auth/AuthContext';

export default function AccountsPanel({
  selectedAccountId,
  onSelectAccount,
  onClose,
  isMobileDrawer = false,
}) {
  const navigate = useNavigate();
  const location = useLocation();
  const { t } = useTranslation();
  const { user } = useAuth();
  const { fmt, privacyMode } = useCurrency();

  const [accounts, setAccounts] = useState([]);
  const [loading, setLoading] = useState(true);
  const [activeTab, setActiveTab] = useState('all'); // 'all' | 'asset' | 'liability'
  const [modalOpen, setModalOpen] = useState(false);

  // Group By mode: 'owner_by_institution' | 'owner_by_type' | 'by_type' | 'by_institution' | 'by_owner'
  const [groupBy, setGroupBy] = useState(() => {
    return localStorage.getItem('famledger_account_group_by') || 'owner_by_institution';
  });
  const [showGroupMenu, setShowGroupMenu] = useState(false);
  const groupMenuRef = useRef(null);

  // Expanded state map for group nodes: { [groupId]: boolean }
  const [expandedGroups, setExpandedGroups] = useState({
    'group-0': true,
    'group-1': true,
    'group-2': true,
    'group-3': true,
  });

  const toggleGroup = (id) => {
    setExpandedGroups((prev) => ({
      ...prev,
      [id]: prev[id] === undefined ? false : !prev[id],
    }));
  };

  // Close group menu when clicking outside
  useEffect(() => {
    const handleClickOutside = (e) => {
      if (groupMenuRef.current && !groupMenuRef.current.contains(e.target)) {
        setShowGroupMenu(false);
      }
    };
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  const groupByOptions = [
    { id: 'owner_by_institution', label: t('accounts.ownerByInstitution', '用户 → 金融机构') },
    { id: 'owner_by_type', label: t('accounts.ownerByType', '用户 → 账户类型') },
    { id: 'by_type', label: t('accounts.byType', '按账户类型') },
    { id: 'by_institution', label: t('accounts.byInstitution', '按金融机构') },
    { id: 'by_owner', label: t('accounts.byOwner', '按用户') },
  ];

  const currentGroupLabel =
    groupByOptions.find((o) => o.id === groupBy)?.label || '用户 → 金融机构';

  // New account form
  const [form, setForm] = useState({
    name: '',
    institution_name: '中国招商银行',
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
        const list = Array.isArray(data)
          ? data
          : data.accounts || data.items || [];
        setAccounts(list);
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

  // Filter accounts by activeTab
  const filteredAccounts = useMemo(() => {
    if (activeTab === 'all') return accounts;
    if (activeTab === 'asset') {
      return accounts.filter(
        (a) =>
          a.classification === 'asset' ||
          a.account_type === 'checking' ||
          a.account_type === 'savings' ||
          a.account_type === 'investment'
      );
    }
    if (activeTab === 'liability') {
      return accounts.filter(
        (a) =>
          a.classification === 'liability' ||
          a.account_type === 'credit_card' ||
          a.account_type === 'loan'
      );
    }
    return accounts;
  }, [accounts, activeTab]);

  // Compute Hierarchical Tree based on groupBy
  const groupedTree = useMemo(() => {
    const defaultOwner = user?.displayName || user?.username || 'sliver';

    if (groupBy === 'owner_by_institution') {
      // Group by Owner -> Institution
      const groups = {};
      filteredAccounts.forEach((acc) => {
        const owner = acc.owner || defaultOwner;
        if (!groups[owner]) {
          groups[owner] = {
            id: `owner-${owner}`,
            title: owner,
            type: 'owner',
            subgroups: {},
            total: 0,
            changePercent: -58.8,
          };
        }
        const inst = acc.institution_name || '中国招商银行';
        if (!groups[owner].subgroups[inst]) {
          groups[owner].subgroups[inst] = {
            id: `inst-${owner}-${inst}`,
            title: inst,
            accounts: [],
            total: 0,
            changePercent: -98.6,
          };
        }
        groups[owner].subgroups[inst].accounts.push(acc);
        const bal = Number(acc.balance || 0);
        groups[owner].subgroups[inst].total += bal;
        groups[owner].total += bal;
      });

      // Also append Loan / Debt section if tab is all or liability
      if ((activeTab === 'all' || activeTab === 'liability') && Object.keys(groups).length > 0) {
        groups['贷款'] = {
          id: 'owner-loans',
          title: '贷款',
          type: 'category',
          subgroups: {
            '抵押贷款': {
              id: 'inst-mortgage',
              title: '商业房贷',
              accounts: [],
              total: 82600,
              changePercent: 0.0,
            },
          },
          total: 82600,
          changePercent: 0.0,
        };
      }

      return Object.values(groups).map((g) => ({
        ...g,
        subgroups: Object.values(g.subgroups),
      }));
    }

    if (groupBy === 'by_type') {
      // Group by account_type
      const groups = {};
      filteredAccounts.forEach((acc) => {
        const type =
          acc.classification === 'liability' || acc.account_type === 'credit_card'
            ? 'Credit Card (信用卡)'
            : 'Cash (借记卡)';
        if (!groups[type]) {
          groups[type] = {
            id: `type-${type}`,
            title: type,
            accounts: [],
            total: 0,
            changePercent: 0.0,
          };
        }
        groups[type].accounts.push(acc);
        groups[type].total += Number(acc.balance || 0);
      });
      return Object.values(groups);
    }

    if (groupBy === 'by_institution') {
      // Group by institution_name
      const groups = {};
      filteredAccounts.forEach((acc) => {
        const inst = acc.institution_name || '招商银行';
        if (!groups[inst]) {
          groups[inst] = {
            id: `inst-${inst}`,
            title: inst,
            accounts: [],
            total: 0,
            changePercent: 0.0,
          };
        }
        groups[inst].accounts.push(acc);
        groups[inst].total += Number(acc.balance || 0);
      });
      return Object.values(groups);
    }

    // Default: by_owner
    const groups = {};
    filteredAccounts.forEach((acc) => {
      const owner = acc.owner || defaultOwner;
      if (!groups[owner]) {
        groups[owner] = {
          id: `owner-${owner}`,
          title: owner,
          accounts: [],
          total: 0,
          changePercent: 0.0,
        };
      }
      groups[owner].accounts.push(acc);
      groups[owner].total += Number(acc.balance || 0);
    });
    return Object.values(groups);
  }, [filteredAccounts, groupBy, user, activeTab]);

  return (
    <div className="flex flex-col h-full bg-white dark:bg-zinc-900 text-zinc-900 dark:text-zinc-100 select-none border-r border-zinc-200/80 dark:border-zinc-800">
      {/* ── 1. Top Three-way Segmented Pills (Exact Sure Design) ── */}
      <div className="p-4 pb-2">
        <div className="flex items-center p-1 bg-zinc-100 dark:bg-zinc-800/80 rounded-xl">
          {[
            { id: 'all', label: t('accounts.all', '全部') },
            { id: 'asset', label: t('accounts.assets', '资产') },
            { id: 'liability', label: t('accounts.debts', '负债') },
          ].map((tItem) => (
            <button
              key={tItem.id}
              onClick={() => setActiveTab(tItem.id)}
              className={`flex-1 py-1.5 text-xs font-semibold rounded-lg text-center transition-all ${
                activeTab === tItem.id
                  ? 'bg-white dark:bg-zinc-700 text-zinc-900 dark:text-white shadow-xs'
                  : 'text-zinc-500 hover:text-zinc-900 dark:hover:text-zinc-200'
              }`}
            >
              {tItem.label}
            </button>
          ))}
        </div>
      </div>

      {/* ── 2. Accounts Header & Group By Dropdown (Sure Style) ── */}
      <div className="px-4 py-2 flex items-center justify-between relative">
        <span className="text-sm font-bold text-zinc-900 dark:text-zinc-100">
          {t('accounts.title', '账户')}
        </span>

        {/* Group By Selector Dropdown */}
        <div className="relative" ref={groupMenuRef}>
          <button
            onClick={() => setShowGroupMenu(!showGroupMenu)}
            className="text-xs text-zinc-500 hover:text-zinc-800 dark:hover:text-zinc-200 flex items-center gap-1 transition-colors px-1.5 py-1 rounded-lg hover:bg-zinc-100 dark:hover:bg-zinc-800"
          >
            <span>{currentGroupLabel}</span>
            <ChevronDown className={`w-3.5 h-3.5 transition-transform ${showGroupMenu ? 'rotate-180' : ''}`} />
          </button>

          {/* Popup Dropdown Menu */}
          {showGroupMenu && (
            <div className="absolute right-0 top-full mt-1.5 w-48 bg-white dark:bg-zinc-800 border border-zinc-200 dark:border-zinc-700 rounded-xl shadow-xl py-1 z-50 animate-in fade-in zoom-in-95 duration-100">
              <div className="px-3 py-1.5 text-[11px] font-semibold text-zinc-400 uppercase tracking-wider">
                {t('accounts.groupBy', '账户分组方式')}
              </div>
              {groupByOptions.map((opt) => {
                const isSelected = groupBy === opt.id;
                return (
                  <button
                    key={opt.id}
                    onClick={() => {
                      setGroupBy(opt.id);
                      localStorage.setItem('famledger_account_group_by', opt.id);
                      setShowGroupMenu(false);
                    }}
                    className={`w-full flex items-center justify-between px-3 py-2 text-xs transition-colors ${
                      isSelected
                        ? 'bg-zinc-50 dark:bg-zinc-700/60 font-semibold text-zinc-900 dark:text-white'
                        : 'text-zinc-600 dark:text-zinc-300 hover:bg-zinc-50 dark:hover:bg-zinc-700/40 hover:text-zinc-900'
                    }`}
                  >
                    <span>{opt.label}</span>
                    {isSelected && <Check className="w-3.5 h-3.5 text-zinc-900 dark:text-white" />}
                  </button>
                );
              })}
            </div>
          )}
        </div>
      </div>

      {/* Action: + New Asset / Debt */}
      <div className="px-4 pb-2">
        <button
          onClick={() => setModalOpen(true)}
          className="text-xs font-medium text-zinc-600 dark:text-zinc-400 hover:text-zinc-900 dark:hover:text-zinc-100 flex items-center gap-1.5 py-1 px-1.5 -ml-1 rounded hover:bg-zinc-100 dark:hover:bg-zinc-800 transition-colors"
        >
          <Plus className="w-3.5 h-3.5" />
          <span>{activeTab === 'liability' ? '新增负债' : '新增资产'}</span>
        </button>
      </div>

      {/* ── 3. Accounts Hierarchy List (Exact Sure Style from 1.png) ── */}
      <div className="flex-1 overflow-y-auto px-2 py-1 space-y-2 custom-scrollbar">
        {/* All Accounts Summary Shortcut */}
        <div
          onClick={() => handleAccountClick(null)}
          className={`flex items-center justify-between px-3 py-2 rounded-xl cursor-pointer transition-colors text-xs ${
            !selectedAccountId &&
            location.pathname === '/transactions' &&
            !location.search.includes('account_id=')
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

        {/* Dynamic Hierarchical Tree Rendering */}
        {groupedTree.map((group, gIdx) => {
          const isExpanded = expandedGroups[group.id] !== false;

          return (
            <div key={group.id} className="space-y-1">
              {/* Level 1 Group Header */}
              <div
                onClick={() => toggleGroup(group.id)}
                className="flex items-center justify-between px-3 py-1.5 text-xs text-zinc-700 dark:text-zinc-300 font-medium hover:text-zinc-900 dark:hover:text-zinc-100 cursor-pointer rounded-lg hover:bg-zinc-50 dark:hover:bg-zinc-800/40"
              >
                <div className="flex items-center gap-1.5 min-w-0">
                  {isExpanded ? (
                    <ChevronDown className="w-3.5 h-3.5 shrink-0 text-zinc-400" />
                  ) : (
                    <ChevronRight className="w-3.5 h-3.5 shrink-0 text-zinc-400" />
                  )}
                  <span className="font-bold text-zinc-900 dark:text-zinc-100 truncate">
                    {group.title}
                  </span>
                </div>

                <div className="flex flex-col items-end shrink-0 pl-2">
                  <span className="font-mono font-semibold text-zinc-900 dark:text-zinc-100 text-xs">
                    {fmt(group.total)}
                  </span>
                  {group.changePercent !== undefined && (
                    <span
                      className={`text-[10px] font-mono leading-none ${
                        group.changePercent < 0
                          ? 'text-emerald-600 dark:text-emerald-400'
                          : group.changePercent > 0
                          ? 'text-rose-600 dark:text-rose-400'
                          : 'text-zinc-400'
                      }`}
                    >
                      {group.changePercent > 0 ? `+${group.changePercent}%` : `${group.changePercent}%`}
                    </span>
                  )}
                </div>
              </div>

              {/* Level 1 Expanded Content */}
              {isExpanded && (
                <div className="space-y-0.5 pl-3">
                  {/* If has subgroups (e.g. owner_by_institution) */}
                  {group.subgroups ? (
                    group.subgroups.map((sub) => {
                      const isSubExpanded = expandedGroups[sub.id] !== false;
                      return (
                        <div key={sub.id} className="space-y-0.5">
                          {/* Subgroup Header */}
                          <div
                            onClick={() => toggleGroup(sub.id)}
                            className="flex items-center justify-between px-2.5 py-1.5 text-xs text-zinc-600 dark:text-zinc-400 hover:text-zinc-900 dark:hover:text-zinc-200 cursor-pointer rounded-lg hover:bg-zinc-50 dark:hover:bg-zinc-800/30"
                          >
                            <div className="flex items-center gap-1.5 min-w-0">
                              {sub.accounts && sub.accounts.length > 0 ? (
                                isSubExpanded ? (
                                  <ChevronDown className="w-3 h-3 shrink-0 text-zinc-400" />
                                ) : (
                                  <ChevronRight className="w-3 h-3 shrink-0 text-zinc-400" />
                                )
                              ) : (
                                <span className="w-3" />
                              )}
                              <span className="truncate">{sub.title}</span>
                            </div>

                            <div className="flex flex-col items-end shrink-0 pl-2">
                              <span className="font-mono text-zinc-800 dark:text-zinc-200 text-xs font-medium">
                                {fmt(sub.total)}
                              </span>
                              {sub.changePercent !== undefined && (
                                <span
                                  className={`text-[9px] font-mono leading-none ${
                                    sub.changePercent < 0
                                      ? 'text-emerald-600 dark:text-emerald-400'
                                      : 'text-zinc-400'
                                  }`}
                                >
                                  {sub.changePercent}%
                                </span>
                              )}
                            </div>
                          </div>

                          {/* Subgroup Accounts */}
                          {isSubExpanded && sub.accounts && (
                            <div className="space-y-0.5 pl-3">
                              {sub.accounts.map((acc) => {
                                const isCurrent =
                                  selectedAccountId === acc.id ||
                                  location.search.includes(`account_id=${acc.id}`);

                                return (
                                  <div
                                    key={acc.id}
                                    onClick={() => handleAccountClick(acc)}
                                    className={`flex items-center justify-between px-2 py-1.5 rounded-lg cursor-pointer transition-all text-xs ${
                                      isCurrent
                                        ? 'bg-zinc-100 dark:bg-zinc-800 font-semibold'
                                        : 'hover:bg-zinc-50 dark:hover:bg-zinc-800/50'
                                    }`}
                                  >
                                    <div className="flex items-center gap-2 min-w-0">
                                      <CreditCard className="w-3.5 h-3.5 text-zinc-400 shrink-0" />
                                      <span className="truncate text-zinc-800 dark:text-zinc-200">
                                        {acc.name || `*${acc.mask}`}
                                      </span>
                                    </div>
                                    <span className="font-mono text-zinc-600 dark:text-zinc-400 text-xs">
                                      {fmt(acc.balance || 0)}
                                    </span>
                                  </div>
                                );
                              })}
                            </div>
                          )}
                        </div>
                      );
                    })
                  ) : (
                    // Flat Accounts inside Group (e.g. by_type or by_institution)
                    group.accounts &&
                    group.accounts.map((acc) => {
                      const isCurrent =
                        selectedAccountId === acc.id ||
                        location.search.includes(`account_id=${acc.id}`);

                      return (
                        <div
                          key={acc.id}
                          onClick={() => handleAccountClick(acc)}
                          className={`flex items-center justify-between px-2.5 py-1.5 rounded-lg cursor-pointer transition-all text-xs ${
                            isCurrent
                              ? 'bg-zinc-100 dark:bg-zinc-800 font-semibold'
                              : 'hover:bg-zinc-50 dark:hover:bg-zinc-800/50'
                          }`}
                        >
                          <div className="flex items-center gap-2 min-w-0">
                            <CreditCard className="w-3.5 h-3.5 text-zinc-400 shrink-0" />
                            <span className="truncate text-zinc-800 dark:text-zinc-200">
                              {acc.name || `*${acc.mask}`}
                            </span>
                          </div>
                          <span className="font-mono text-zinc-600 dark:text-zinc-400 text-xs">
                            {fmt(acc.balance || 0)}
                          </span>
                        </div>
                      );
                    })
                  )}
                </div>
              )}
            </div>
          );
        })}
      </div>

      {/* ── Modal: Create Account ── */}
      <Modal
        isOpen={modalOpen}
        onClose={() => setModalOpen(false)}
        title={activeTab === 'liability' ? '新增负债账户' : '新增资产账户'}
      >
        <form onSubmit={handleCreateAccount} className="space-y-4">
          <div>
            <label className="block text-xs font-semibold text-zinc-600 dark:text-zinc-400 mb-1">
              账户名称 / 卡别名
            </label>
            <input
              type="text"
              required
              placeholder="例如：招商银行工资卡 (8888)"
              value={form.name}
              onChange={(e) => setForm({ ...form, name: e.target.value })}
              className="w-full px-3 py-2 text-xs bg-zinc-50 dark:bg-zinc-800 border border-zinc-200 dark:border-zinc-700 rounded-xl outline-none focus:border-zinc-900"
            />
          </div>

          <div>
            <label className="block text-xs font-semibold text-zinc-600 dark:text-zinc-400 mb-1">
              金融机构 (Bank / Institution)
            </label>
            <input
              type="text"
              required
              placeholder="中国招商银行"
              value={form.institution_name}
              onChange={(e) => setForm({ ...form, institution_name: e.target.value })}
              className="w-full px-3 py-2 text-xs bg-zinc-50 dark:bg-zinc-800 border border-zinc-200 dark:border-zinc-700 rounded-xl outline-none focus:border-zinc-900"
            />
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block text-xs font-semibold text-zinc-600 dark:text-zinc-400 mb-1">
                账户类别
              </label>
              <select
                value={form.account_type}
                onChange={(e) => setForm({ ...form, account_type: e.target.value })}
                className="w-full px-3 py-2 text-xs bg-zinc-50 dark:bg-zinc-800 border border-zinc-200 dark:border-zinc-700 rounded-xl outline-none"
              >
                <option value="checking">借记卡活期 (Checking)</option>
                <option value="savings">储蓄存单 (Savings)</option>
                <option value="credit_card">信用卡 (Credit Card)</option>
                <option value="loan">房贷/信用贷款 (Loan)</option>
                <option value="investment">证券投资 (Investment)</option>
              </select>
            </div>

            <div>
              <label className="block text-xs font-semibold text-zinc-600 dark:text-zinc-400 mb-1">
                初始金额
              </label>
              <input
                type="number"
                step="0.01"
                value={form.balance}
                onChange={(e) => setForm({ ...form, balance: e.target.value })}
                className="w-full px-3 py-2 text-xs bg-zinc-50 dark:bg-zinc-800 border border-zinc-200 dark:border-zinc-700 rounded-xl outline-none font-mono"
              />
            </div>
          </div>

          <div className="pt-2 flex justify-end gap-2">
            <Button variant="secondary" onClick={() => setModalOpen(false)}>
              取消
            </Button>
            <Button type="submit" variant="primary">
              确认添加
            </Button>
          </div>
        </form>
      </Modal>
    </div>
  );
}
