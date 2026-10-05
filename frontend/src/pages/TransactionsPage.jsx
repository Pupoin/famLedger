import { categoryLabel, dateLabel, tx, useLocale, currentLocale } from "../localization.js";
import { currencySymbol, originalTransactionMoney, totalsByCurrency, formatCurrencyTotals } from '../utils/currency';
import BookingMoneyInfo from '../components/BookingMoneyInfo';
import PendingFxPanel from '../components/PendingFxPanel';
import React, { useState, useEffect, useMemo, useCallback, useRef } from 'react';
import { useSearchParams } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { MoreHorizontal, Upload, Plus, Search, ArrowRightLeft, RotateCcw, Lock, SlidersHorizontal, Loader2, ArrowDown, Users, Scissors } from 'lucide-react';
import { fetchWithAuth } from '../api/fetchWithAuth';
import { useAuth } from '../auth/AuthContext';
import { useCurrency } from '../CurrencyContext';
import { useToast } from '../ToastContext';
import TransactionDrawer from '../components/TransactionDrawer';
import useTransactionDrawer from '../hooks/useTransactionDrawer';
import TransactionFilterModal from '../components/TransactionFilterModal';
import ReimbursementBadge from '../components/ReimbursementBadge';
import ScheduledPlans from '../components/ScheduledPlans';
import AddTransactionModal from '../components/AddTransactionModal';
import { formatDateTime } from '../utils/dates';
import { getTransactionInitialBadge, formatAccountDisplayName } from '../utils/accountIcons';
import AccountSharingModal from '../components/AccountSharingModal';
import {
  EditAccountModal,
  TransferOwnershipModal,
  DeleteAccountModal,
  ImportTransactionsModal,
} from '../components/AccountModals';

export default function TransactionsPage() {
  const locale = useLocale();
  const [searchParams, setSearchParams] = useSearchParams();
  const accountIdFilter = searchParams.get('account_id') || '';
  const accountMaskFilter = searchParams.get('account_mask') || '';
  const institutionFilter = searchParams.get('institution_name') || '';
  const startDateFilter = searchParams.get('start_date') || searchParams.get('date') || '';
  const endDateFilter = searchParams.get('end_date') || searchParams.get('date') || '';
  const querySearch = searchParams.get('search') || '';
  const categoryNameFilter = searchParams.get('category_name') || '';
  const typeFilter = searchParams.get('transaction_type') || '';
  const isRefundFilter = searchParams.get('is_refund') === 'true';
  const hasRefundFilter = searchParams.get('has_refund') === 'true';
  const tagFilter = searchParams.get('tag') || '';
  const merchantFilter = searchParams.get('merchant') || '';
  const merchantGroupFilter = searchParams.get('merchant_group') || '';
  const statusFilter = searchParams.get('status') || '';
  const minAmountFilter = searchParams.get('min_amount') || '';
  const maxAmountFilter = searchParams.get('max_amount') || '';
  const userFilter = searchParams.get('user') || '';

  const { t } = useTranslation();
  const { user } = useAuth();
  const { fmt, privacyMode } = useCurrency();
  const { showToast } = useToast();

  const [accounts, setAccounts] = useState([]);
  const reloadAfterBooking = useCallback(() => window.location.reload(), []);

  const displayAccountNames = useMemo(() => {
    if (!accountIdFilter) return '';
    const ids = accountIdFilter.split(',').map((s) => s.trim()).filter(Boolean);
    const names = ids.map((id) => {
      const acc = accounts.find((a) => a.id === id);
      return acc ? (acc.name || id) : id;
    });
    if (names.length <= 2) return names.join(locale === 'zh-CN' ? '、' : ', ');
    return tx("{p0} 等 {p1} 个账户", { p0: names[0], p1: names.length });
  }, [accountIdFilter, accounts, locale]);

  const displayTypeNames = useMemo(() => {
    if (!typeFilter) return '';
    const TYPE_MAP = {
      expense: '支出',
      income: '收入',
      transfer: '内部转账/还贷',
      adjustment: '对账调整',
      refund: '退款',
    };
    return typeFilter
      .split(',')
      .map((t) => tx(TYPE_MAP[t.trim()] || t.trim()))
      .join(locale === 'zh-CN' ? '、' : ', ');
  }, [typeFilter, locale]);

  const displayCategoryNames = useMemo(() => {
    if (!categoryNameFilter) return '';
    const cats = categoryNameFilter.split(',').map((s) => s.trim()).filter(Boolean).map(categoryLabel);
    if (cats.length <= 3) return cats.join(locale === 'zh-CN' ? '、' : ', ');
    return tx("{p0}、{p1} 等 {p2} 个分类", { p0: cats[0], p1: cats[1], p2: cats.length });
  }, [categoryNameFilter, locale]);
  const [transactions, setTransactions] = useState([]);
  const [loading, setLoading] = useState(true);
  const [isLoadingMore, setIsLoadingMore] = useState(false);
  const [hasMore, setHasMore] = useState(false);
  const [nextCursor, setNextCursor] = useState(null);
  const [totalCount, setTotalCount] = useState(0);
  const nextCursorRef = useRef(null);
  const loadMoreRef = useRef(null);

  // Filters & Tabs
  const [search, setSearch] = useState(querySearch);
  const [activeTab, setActiveTab] = useState('transactions'); // 'transactions' | 'upcoming'
  const [isFilterModalOpen, setIsFilterModalOpen] = useState(false);
  const [filterOptions, setFilterOptions] = useState(null);
  const [showAddModal, setShowAddModal] = useState(false);

  // Account operations menu & modals (Exact 12.png)
  const [showAccountMenu, setShowAccountMenu] = useState(false);
  const [editingAccount, setEditingAccount] = useState(null);
  const [sharingAccountId, setSharingAccountId] = useState(null);
  const [transferringAccount, setTransferringAccount] = useState(null);
  const [deletingAccount, setDeletingAccount] = useState(null);
  const [importingAccount, setImportingAccount] = useState(null);

  // Synchronize local search state when querySearch param changes
  useEffect(() => {
    setSearch(querySearch);
  }, [querySearch]);

  // Selected Transaction for Drawer
  const [selectedTxnId, setSelectedTxnId] = useTransactionDrawer();

  // Multi-selection set
  const [selectedIds, setSelectedIds] = useState(new Set());
  const [pairingLoading, setPairingLoading] = useState(false);

  // Handle in-place update of transaction attributes (reimbursement / excluded_from_stats)
  const handleTxnStatusUpdated = (txnId, updatedFields) => {
    setTransactions((prev) =>
      prev.map((t) => (t.id === txnId ? { ...t, ...updatedFields } : t))
    );
  };

  // Load Accounts
  useEffect(() => {
    async function loadAccounts() {
      try {
        const res = await fetchWithAuth('/api/v1/accounts');
        if (res.ok) {
          const data = await res.json();
          setAccounts(Array.isArray(data) ? data : data.accounts || []);
        }
      } catch (e) {
        console.error('Failed to load accounts in TransactionsPage', e);
      }
    }
    loadAccounts();
    window.addEventListener('accounts-updated', loadAccounts);
    return () => window.removeEventListener('accounts-updated', loadAccounts);
  }, []);

  // Load Filter Options
  useEffect(() => {
    async function loadFilterOptions() {
      try {
        const res = await fetchWithAuth('/api/v1/transactions/filter-options');
        if (res.ok) {
          const data = await res.json();
          setFilterOptions(data);
        }
      } catch (e) {
        console.error('Failed to load filter options', e);
      }
    }
    loadFilterOptions();
  }, []);

  // Compute active filter count
  const activeFilterCount = useMemo(() => {
    let count = 0;
    if (accountIdFilter) count += accountIdFilter.split(',').filter(Boolean).length;
    if (accountMaskFilter) count += accountMaskFilter.split(',').filter(Boolean).length;
    if (institutionFilter) count += institutionFilter.split(',').filter(Boolean).length;
    if (categoryNameFilter) count += categoryNameFilter.split(',').filter(Boolean).length;
    if (typeFilter) count += typeFilter.split(',').filter(Boolean).length;
    if (isRefundFilter) count++;
    if (hasRefundFilter) count++;
    if (tagFilter) count += tagFilter.split(',').filter(Boolean).length;
    if (merchantFilter) count += merchantFilter.split(',').filter(Boolean).length;
    if (merchantGroupFilter) count++;
    if (statusFilter) count += statusFilter.split(',').filter(Boolean).length;
    if (minAmountFilter || maxAmountFilter) count++;
    if (startDateFilter || endDateFilter) count++;
    if (userFilter) count++;
    return count;
  }, [
    accountIdFilter,
    accountMaskFilter,
    institutionFilter,
    categoryNameFilter,
    typeFilter,
    isRefundFilter,
    hasRefundFilter,
    tagFilter,
    merchantFilter,
    merchantGroupFilter,
    statusFilter,
    minAmountFilter,
    maxAmountFilter,
    startDateFilter,
    endDateFilter,
    userFilter,
  ]);

  // Load Transactions
  const fetchTransactions = useCallback(
    async (reset = false) => {
      if (reset) {
        setLoading(true);
        nextCursorRef.current = null;
      } else {
        if (!nextCursorRef.current) return;
        setIsLoadingMore(true);
      }

      try {
        const params = new URLSearchParams();
        params.append('limit', '100');
        if (accountIdFilter) params.append('account_id', accountIdFilter);
        if (accountMaskFilter) params.append('account_mask', accountMaskFilter);
        if (institutionFilter) params.append('institution_name', institutionFilter);
        if (startDateFilter) params.append('start_date', startDateFilter);
        if (endDateFilter) params.append('end_date', endDateFilter);
        if (categoryNameFilter) params.append('category_name', categoryNameFilter);
        if (typeFilter) params.append('transaction_type', typeFilter);
        if (isRefundFilter) params.append('is_refund', 'true');
        if (hasRefundFilter) params.append('has_refund', 'true');
        if (tagFilter) params.append('tag', tagFilter);
        if (merchantFilter) params.append('merchant', merchantFilter);
        if (merchantGroupFilter) params.append('merchant_group', merchantGroupFilter);
        if (statusFilter) params.append('status', statusFilter);
        if (minAmountFilter) params.append('min_amount', minAmountFilter);
        if (maxAmountFilter) params.append('max_amount', maxAmountFilter);
        if (querySearch) params.append('search', querySearch);
        if (userFilter) params.append('user', userFilter);

        if (!reset && nextCursorRef.current) {
          params.append('cursor', nextCursorRef.current);
        }

        const res = await fetchWithAuth(`/api/v1/transactions?${params.toString()}`);
        if (res.ok) {
          const data = await res.json();
          const items = data.items || [];
          setTransactions((prev) => (reset ? items : [...prev, ...items]));
          setHasMore(Boolean(data.has_more));
          nextCursorRef.current = data.next_cursor || null;
          setNextCursor(data.next_cursor || null);
          if (data.total_count !== undefined) {
            setTotalCount(data.total_count);
          }
        }
      } catch (err) {
        console.error('Failed to fetch transactions', err);
      } finally {
        setLoading(false);
        setIsLoadingMore(false);
      }
    },
    [
      accountIdFilter,
      accountMaskFilter,
      institutionFilter,
      startDateFilter,
      endDateFilter,
      categoryNameFilter,
      typeFilter,
      isRefundFilter,
      hasRefundFilter,
      tagFilter,
      merchantFilter,
      merchantGroupFilter,
      statusFilter,
      minAmountFilter,
      maxAmountFilter,
      querySearch,
      userFilter,
    ]
  );

  useEffect(() => {
    fetchTransactions(true);
  }, [
    accountIdFilter,
    accountMaskFilter,
    institutionFilter,
    startDateFilter,
    endDateFilter,
    categoryNameFilter,
    typeFilter,
    isRefundFilter,
    hasRefundFilter,
    tagFilter,
    merchantFilter,
    merchantGroupFilter,
    statusFilter,
    minAmountFilter,
    maxAmountFilter,
    querySearch,
    userFilter,
  ]);

  // 监听全局交易添加事件
  useEffect(() => {
    const handleTxAdded = () => fetchTransactions(true);
    window.addEventListener('transaction-added', handleTxAdded);
    return () => window.removeEventListener('transaction-added', handleTxAdded);
  }, [fetchTransactions]);

  // 底部触底自动加载观察器 (IntersectionObserver)
  useEffect(() => {
    if (!hasMore || loading || isLoadingMore) return;
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries[0] && entries[0].isIntersecting) {
          fetchTransactions(false);
        }
      },
      { threshold: 0.1 }
    );
    const target = loadMoreRef.current;
    if (target) {
      observer.observe(target);
    }
    return () => {
      if (target) observer.unobserve(target);
    };
  }, [hasMore, loading, isLoadingMore, fetchTransactions]);

  const handleSearchSubmit = (e) => {
    e.preventDefault();
    const nextParams = new URLSearchParams(searchParams);
    if (search.trim()) {
      nextParams.set('search', search.trim());
    } else {
      nextParams.delete('search');
    }
    setSearchParams(nextParams);
  };

  const handleApplyFilterModal = (draft) => {
    const nextParams = new URLSearchParams(searchParams);

    if (draft.account_id) nextParams.set('account_id', draft.account_id);
    else nextParams.delete('account_id');

    if (draft.account_mask) nextParams.set('account_mask', draft.account_mask);
    else nextParams.delete('account_mask');

    if (draft.institution_name) nextParams.set('institution_name', draft.institution_name);
    else nextParams.delete('institution_name');

    if (draft.transaction_type) nextParams.set('transaction_type', draft.transaction_type);
    else nextParams.delete('transaction_type');

    if (draft.category_name) nextParams.set('category_name', draft.category_name);
    else nextParams.delete('category_name');

    if (draft.is_refund) nextParams.set('is_refund', 'true');
    else nextParams.delete('is_refund');

    if (draft.has_refund) nextParams.set('has_refund', 'true');
    else nextParams.delete('has_refund');

    if (draft.tag) nextParams.set('tag', draft.tag);
    else nextParams.delete('tag');

    if (draft.merchant) {
      nextParams.set('merchant', draft.merchant);
      nextParams.delete('merchant_group');
    }
    else nextParams.delete('merchant');

    if (draft.status) nextParams.set('status', draft.status);
    else nextParams.delete('status');

    if (draft.min_amount) nextParams.set('min_amount', draft.min_amount);
    else nextParams.delete('min_amount');

    if (draft.max_amount) nextParams.set('max_amount', draft.max_amount);
    else nextParams.delete('max_amount');

    if (draft.start_date) nextParams.set('start_date', draft.start_date);
    else nextParams.delete('start_date');

    if (draft.end_date) nextParams.set('end_date', draft.end_date);
    else nextParams.delete('end_date');

    nextParams.delete('date');

    setSearchParams(nextParams);
  };

  const handleResetFilters = () => {
    const nextParams = new URLSearchParams();
    if (querySearch) nextParams.set('search', querySearch);
    setSearchParams(nextParams);
  };

  // Group transactions by date (Exact 5.png layout!)
  const groupedTransactions = useMemo(() => {
    const groups = [];
    const dateMap = {};

    transactions.forEach((txn) => {
      const dateStr = txn.transacted_at ? txn.transacted_at.slice(0, 10) : '未知日期';
      if (!dateMap[dateStr]) {
        // Format date string to Chinese: e.g. "2026年09月18日"
        let displayDate = dateStr;
        try {
          const parts = dateStr.split('-');
          if (parts.length === 3) {
            displayDate = `${parts[0]}年${parts[1]}月${parts[2]}日`;
          }
        } catch (_) {}

        dateMap[dateStr] = {
          dateKey: dateStr,
          displayDate,
          items: [],
          currencyTotals: {},
        };
        groups.push(dateMap[dateStr]);
      }

      dateMap[dateStr].items.push(txn);
    });

    groups.forEach((g) => {
      g.currencyTotals = totalsByCurrency(g.items, 'net', 'original');
      g.items.sort((a, b) => {
        const timeA = new Date(a.occurred_at || a.created_at || a.transacted_at).getTime() || 0;
        const timeB = new Date(b.occurred_at || b.created_at || b.transacted_at).getTime() || 0;
        // 同日内按发生时间正序 (由早到晚，10:15 -> 23:58)
        return timeA - timeB;
      });
    });
    groups.sort((a, b) => b.dateKey.localeCompare(a.dateKey));

    return groups;
  }, [transactions]);

  // Overall metrics (Total transactions, Income, Expenses)
  const metrics = useMemo(() => {
    return {
      count: transactions.length,
      income: formatCurrencyTotals(totalsByCurrency(transactions, "income", 'original')),
      expense: formatCurrencyTotals(totalsByCurrency(transactions, "expense", 'original')),
    };
  }, [transactions]);

  // Selection toggle
  const toggleSelect = (id) => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  // Select all in date group
  const toggleGroupSelect = (items) => {
    const allSelected = items.every((i) => selectedIds.has(i.id));
    setSelectedIds((prev) => {
      const next = new Set(prev);
      items.forEach((i) => {
        if (allSelected) next.delete(i.id);
        else next.add(i.id);
      });
      return next;
    });
  };

  // Manual Transfer Pair for selected 2 items
  const handlePairSelectedAsTransfer = async () => {
    if (selectedIds.size !== 2) return;
    const ids = Array.from(selectedIds);
    const item1 = transactions.find((t) => t.id === ids[0]);
    const item2 = transactions.find((t) => t.id === ids[1]);
    if (!item1 || !item2) return;

    // Determine which is outflow and which is inflow
    let outflowId = item1.id;
    let inflowId = item2.id;
    if (
      (item1.transaction_type === 'income') &&
      (item2.transaction_type === 'expense' || item2.transaction_type === 'transfer')
    ) {
      outflowId = item2.id;
      inflowId = item1.id;
    }

    try {
      setPairingLoading(true);
      const res = await fetchWithAuth('/api/v1/transfers/manual-pair', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          outflow_transaction_id: outflowId,
          inflow_transaction_id: inflowId,
        }),
      });
      if (res.ok) {
        showToast(tx("已成功撮合并配对为内部转账！"), 'success');
        setSelectedIds(new Set());
        fetchTransactions(true);
      } else {
        const err = await res.json();
        showToast(tx(err.detail || '配对失败'), 'error');
      }
    } catch (e) {
      showToast(tx("网络请求错误"), 'error');
    } finally {
      setPairingLoading(false);
    }
  };

  // Manual Refund Link for selected 2 items
  const handleLinkSelectedAsRefund = async () => {
    if (selectedIds.size !== 2) return;
    const ids = Array.from(selectedIds);
    const item1 = transactions.find((t) => t.id === ids[0]);
    const item2 = transactions.find((t) => t.id === ids[1]);
    if (!item1 || !item2) return;

    let refundId = item1.id;
    let originalId = item2.id;
    if (item2.transaction_type === 'refund') {
      refundId = item2.id;
      originalId = item1.id;
    }

    try {
      setPairingLoading(true);
      const res = await fetchWithAuth(`/api/v1/refunds/${refundId}/link/${originalId}`, {
        method: 'POST',
      });
      if (res.ok) {
        showToast(tx("已成功将退款与原消费冲抵关联！"), 'success');
        setSelectedIds(new Set());
        fetchTransactions(true);
      } else {
        const err = await res.json();
        showToast(tx(err.detail || '冲抵关联失败'), 'error');
      }
    } catch (e) {
      showToast(tx("网络请求错误"), 'error');
    } finally {
      setPairingLoading(false);
    }
  };

  const currentAccount = accounts.find((a) => a.id === accountIdFilter);

  return (
    <div className="space-y-6 pb-20 max-w-7xl mx-auto">
      {/* ── 1. Page Header (Exact 5.png Header) ── */}
      <div className="flex items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl sm:text-3xl font-bold tracking-tight text-zinc-900 dark:text-zinc-100 flex items-center gap-2">
            <span>{tx("交易")}</span>
            {currentAccount && (
              <span className="text-xs px-2.5 py-1 rounded-lg bg-zinc-100 dark:bg-zinc-800 text-zinc-700 dark:text-zinc-300 font-mono font-semibold border border-zinc-200 dark:border-zinc-700">
                {formatAccountDisplayName(currentAccount)}
              </span>
            )}
          </h1>
        </div>

        <div className="flex items-center gap-2">
          {/* Account Action Dropdown (Exact 12.png) */}
          <div className="relative">
            <button
              type="button"
              onClick={() => setShowAccountMenu(!showAccountMenu)}
              title={tx("账户操作")}
              className="p-2 rounded-lg border border-zinc-200 dark:border-zinc-700 text-zinc-600 dark:text-zinc-400 hover:bg-zinc-100 dark:hover:bg-zinc-800 transition-colors cursor-pointer"
            >
              <MoreHorizontal className="w-4 h-4" />
            </button>

            {showAccountMenu && (
              <>
                <div
                  className="fixed inset-0 z-20"
                  onClick={() => setShowAccountMenu(false)}
                />
                <div className="absolute right-0 top-full mt-1.5 w-44 rounded-xl bg-white dark:bg-zinc-800 border border-zinc-200 dark:border-zinc-700 shadow-xl py-1.5 z-30 text-xs animate-in fade-in zoom-in-95 duration-100">
                  <div className="px-3 py-1 text-[11px] font-semibold text-zinc-400 uppercase tracking-wider">
                    {currentAccount ? currentAccount.name : tx("账户操作")}
                  </div>
                  <button
                    type="button"
                    onClick={() => {
                      setEditingAccount(currentAccount || accounts[0]);
                      setShowAccountMenu(false);
                    }}
                    className="w-full text-left px-3 py-2 text-zinc-700 dark:text-zinc-200 hover:bg-zinc-50 dark:hover:bg-zinc-700/60 flex items-center gap-2 cursor-pointer"
                  >
                    <span>{tx("✏️ 编辑")}</span>
                  </button>
                  <button
                    type="button"
                    onClick={() => {
                      setSharingAccountId((currentAccount || accounts[0])?.id);
                      setShowAccountMenu(false);
                    }}
                    className="w-full text-left px-3 py-2 text-zinc-700 dark:text-zinc-200 hover:bg-zinc-50 dark:hover:bg-zinc-700/60 flex items-center gap-2 cursor-pointer"
                  >
                    <span>{tx("🔗 共享")}</span>
                  </button>
                  <button
                    type="button"
                    onClick={() => {
                      setTransferringAccount(currentAccount || accounts[0]);
                      setShowAccountMenu(false);
                    }}
                    className="w-full text-left px-3 py-2 text-zinc-700 dark:text-zinc-200 hover:bg-zinc-50 dark:hover:bg-zinc-700/60 flex items-center gap-2 cursor-pointer"
                  >
                    <span>{tx("🔄 转移所有权")}</span>
                  </button>
                  <button
                    type="button"
                    onClick={() => {
                      setImportingAccount(currentAccount || accounts[0]);
                      setShowAccountMenu(false);
                    }}
                    className="w-full text-left px-3 py-2 text-zinc-700 dark:text-zinc-200 hover:bg-zinc-50 dark:hover:bg-zinc-700/60 flex items-center gap-2 cursor-pointer"
                  >
                    <span>{tx("📥 导入交易记录")}</span>
                  </button>
                  <div className="my-1 border-t border-zinc-100 dark:border-zinc-700/60" />
                  <button
                    type="button"
                    onClick={() => {
                      setDeletingAccount(currentAccount || accounts[0]);
                      setShowAccountMenu(false);
                    }}
                    className="w-full text-left px-3 py-2 text-red-600 dark:text-red-400 hover:bg-red-50 dark:hover:bg-red-950/30 flex items-center gap-2 cursor-pointer"
                  >
                    <span>{tx("🗑️ 删除账户")}</span>
                  </button>
                </div>
              </>
            )}
          </div>

          <button
            type="button"
            onClick={() => setImportingAccount(currentAccount || accounts[0])}
            title={tx("导入交易")}
            className="hidden sm:inline-flex items-center gap-1.5 px-3 py-2 text-xs font-semibold rounded-lg border border-zinc-200 dark:border-zinc-700 text-zinc-700 dark:text-zinc-200 bg-white dark:bg-zinc-800 hover:bg-zinc-50 dark:hover:bg-zinc-700 transition-colors shadow-2xs cursor-pointer"
          >
            <Upload className="w-3.5 h-3.5" />
            <span>{tx("导入")}</span>
          </button>
          <button
            type="button"
            onClick={() => setShowAddModal(true)}
            title={tx("记新账 / 新建交易")}
            className="inline-flex items-center justify-center px-3.5 py-2 text-xs font-bold rounded-lg bg-zinc-900 hover:bg-zinc-800 text-white dark:bg-white dark:text-zinc-900 dark:hover:bg-zinc-100 shadow-xs transition-colors active:scale-95 gap-1.5 cursor-pointer"
          >
            <Plus className="w-4 h-4" />
            <span>{tx("新增")}</span>
          </button>
        </div>
      </div>

      <PendingFxPanel accounts={accounts} onPosted={reloadAfterBooking} />
      {/* Compact count column; original-currency totals wrap without truncation. */}
      <div data-testid="transaction-metrics" className="rounded-2xl border border-zinc-200/80 dark:border-zinc-800 bg-white dark:bg-zinc-900 grid grid-cols-[4.5rem_minmax(0,1fr)_minmax(0,1.4fr)] sm:grid-cols-[7rem_minmax(0,1fr)_minmax(0,1.4fr)] divide-x divide-zinc-200/80 dark:divide-zinc-800 p-2.5 sm:p-3 shadow-xs">
        <div className="min-w-0 px-1.5 py-1 sm:px-3 text-center sm:text-left">
          <p className="text-2xs sm:text-xs font-medium text-zinc-500 dark:text-zinc-400">{tx("交易总数")}</p>
          <p className="text-sm sm:text-base md:text-lg font-bold font-mono text-zinc-900 dark:text-zinc-100 mt-0.5 tracking-tight tabular-nums">
            {metrics.count}
          </p>
        </div>

        <div className="min-w-0 px-1.5 py-1 sm:px-3 text-center sm:text-left">
          <p className="text-2xs sm:text-xs font-medium text-emerald-600 dark:text-emerald-400">{tx("收入（原币）")}</p>
          <div data-testid="transaction-income-totals" className="flex flex-wrap justify-center sm:justify-start gap-x-3 gap-y-1 text-xs sm:text-base md:text-lg font-bold font-mono text-emerald-600 dark:text-emerald-400 mt-0.5 tracking-tight tabular-nums">
            {privacyMode ? '••••••' : metrics.income.split(' / ').map((amount) => (
              <span key={amount} className="max-w-full [overflow-wrap:anywhere]">{amount}</span>
            ))}
          </div>
        </div>

        <div className="min-w-0 px-1.5 py-1 sm:px-3 text-center sm:text-left">
          <p className="text-2xs sm:text-xs font-medium text-zinc-500 dark:text-zinc-400">{tx("支出（原币）")}</p>
          <div data-testid="transaction-expense-totals" className="flex flex-wrap justify-center sm:justify-start gap-x-3 gap-y-1 text-xs sm:text-base md:text-lg font-bold font-mono text-zinc-900 dark:text-zinc-100 mt-0.5 tracking-tight tabular-nums">
            {privacyMode ? '••••••' : metrics.expense.split(' / ').map((amount) => (
              <span key={amount} className="max-w-full [overflow-wrap:anywhere]">{amount}</span>
            ))}
          </div>
        </div>
      </div>

      {/* ── 3. Tabs: 交易 / 待发生 ── */}
      <div className="flex items-center justify-between gap-2 flex-wrap">
        <div className="inline-flex p-1 bg-zinc-100 dark:bg-zinc-800 rounded-xl">
          <button
            onClick={() => setActiveTab('transactions')}
            className={`px-4 py-1.5 text-xs font-semibold rounded-lg transition-all ${
              activeTab === 'transactions'
                ? 'bg-white dark:bg-zinc-700 text-zinc-900 dark:text-white shadow-xs'
                : 'text-zinc-500 hover:text-zinc-800 dark:hover:text-zinc-200'
            }`}
          >{tx("交易")}</button>
          <button
            onClick={() => setActiveTab('upcoming')}
            className={`px-4 py-1.5 text-xs font-semibold rounded-lg transition-all ${
              activeTab === 'upcoming'
                ? 'bg-white dark:bg-zinc-700 text-zinc-900 dark:text-white shadow-xs'
                : 'text-zinc-500 hover:text-zinc-800 dark:hover:text-zinc-200'
            }`}
          >{tx("计划")}</button>
        </div>

        {/* Active Filter Badges */}
        {(startDateFilter ||
          querySearch ||
          userFilter ||
          accountIdFilter ||
          accountMaskFilter ||
          institutionFilter ||
          typeFilter ||
          categoryNameFilter ||
          isRefundFilter ||
          hasRefundFilter ||
          tagFilter ||
          merchantFilter ||
          merchantGroupFilter ||
          statusFilter ||
          minAmountFilter ||
          maxAmountFilter) && (
          <div className="flex items-center gap-2 flex-wrap text-xs">
            <span className="text-zinc-400">{tx("生效筛选:")}</span>

            {/* 成员 */}
            {userFilter && (
              <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg bg-indigo-50 dark:bg-indigo-950/40 text-indigo-700 dark:text-indigo-300 font-medium border border-indigo-200 dark:border-indigo-800">
                <span>{tx("👤 成员:")} {userFilter}</span>
                <button
                  onClick={() => {
                    const p = new URLSearchParams(searchParams);
                    p.delete('user');
                    setSearchParams(p);
                  }}
                  className="hover:text-indigo-900 dark:hover:text-indigo-100 font-bold ml-0.5 cursor-pointer"
                >
                  ✕
                </button>
              </span>
            )}

            {/* 机构 */}
            {institutionFilter && (
              <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg bg-sky-50 dark:bg-sky-950/40 text-sky-700 dark:text-sky-300 font-medium border border-sky-200 dark:border-sky-800">
                <span>{tx("🏦 机构:")} {institutionFilter}</span>
                <button
                  onClick={() => {
                    const p = new URLSearchParams(searchParams);
                    p.delete('institution_name');
                    setSearchParams(p);
                  }}
                  className="hover:text-sky-900 dark:hover:text-sky-100 font-bold ml-0.5 cursor-pointer"
                >
                  ✕
                </button>
              </span>
            )}

            {/* 卡号 */}
            {accountMaskFilter && (
              <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg bg-indigo-50 dark:bg-indigo-950/40 text-indigo-700 dark:text-indigo-300 font-medium border border-indigo-200 dark:border-indigo-800">
                <span>{tx("💳 卡号: *")} {accountMaskFilter}</span>
                <button
                  onClick={() => {
                    const p = new URLSearchParams(searchParams);
                    p.delete('account_mask');
                    setSearchParams(p);
                  }}
                  className="hover:text-indigo-900 dark:hover:text-indigo-100 font-bold ml-0.5 cursor-pointer"
                >
                  ✕
                </button>
              </span>
            )}

            {/* 账户 */}
            {accountIdFilter && (
              <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg bg-zinc-100 dark:bg-zinc-800 text-zinc-700 dark:text-zinc-300 font-medium border border-zinc-200 dark:border-zinc-700">
                <span>{tx("👤 账户:")} {displayAccountNames}</span>
                <button
                  onClick={() => {
                    const p = new URLSearchParams(searchParams);
                    p.delete('account_id');
                    setSearchParams(p);
                  }}
                  className="hover:text-zinc-900 dark:hover:text-zinc-100 font-bold ml-0.5 cursor-pointer"
                >
                  ✕
                </button>
              </span>
            )}

            {/* 分类 */}
            {categoryNameFilter && (
              <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg bg-emerald-50 dark:bg-emerald-950/40 text-emerald-700 dark:text-emerald-300 font-medium border border-emerald-200 dark:border-emerald-800">
                <span>{tx("📂 分类:")} {displayCategoryNames}</span>
                <button
                  onClick={() => {
                    const p = new URLSearchParams(searchParams);
                    p.delete('category_name');
                    setSearchParams(p);
                  }}
                  className="hover:text-emerald-900 dark:hover:text-emerald-100 font-bold ml-0.5 cursor-pointer"
                >
                  ✕
                </button>
              </span>
            )}

            {/* 类型 */}
            {typeFilter && (
              <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg bg-purple-50 dark:bg-purple-950/40 text-purple-700 dark:text-purple-300 font-medium border border-purple-200 dark:border-purple-800">
                <span>{tx("🏷️ 类型:")} {tx(displayTypeNames)}</span>
                <button
                  onClick={() => {
                    const p = new URLSearchParams(searchParams);
                    p.delete('transaction_type');
                    setSearchParams(p);
                  }}
                  className="hover:text-purple-900 dark:hover:text-purple-100 font-bold ml-0.5 cursor-pointer"
                >
                  ✕
                </button>
              </span>
            )}

            {/* 仅退款入账 */}
            {isRefundFilter && (
              <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg bg-emerald-50 dark:bg-emerald-950/40 text-emerald-700 dark:text-emerald-300 font-medium border border-emerald-200 dark:border-emerald-800">
                <span>{tx("↺ 仅退款入账")}</span>
                <button
                  onClick={() => {
                    const p = new URLSearchParams(searchParams);
                    p.delete('is_refund');
                    setSearchParams(p);
                  }}
                  className="hover:text-emerald-900 dark:hover:text-emerald-100 font-bold ml-0.5 cursor-pointer"
                >
                  ✕
                </button>
              </span>
            )}

            {/* 仅退款冲抵原消费 */}
            {hasRefundFilter && (
              <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg bg-amber-50 dark:bg-amber-950/40 text-amber-700 dark:text-amber-300 font-medium border border-amber-200 dark:border-amber-800">
                <span>{tx("🛡️ 仅被退款冲抵原消费")}</span>
                <button
                  onClick={() => {
                    const p = new URLSearchParams(searchParams);
                    p.delete('has_refund');
                    setSearchParams(p);
                  }}
                  className="hover:text-amber-900 dark:hover:text-amber-100 font-bold ml-0.5 cursor-pointer"
                >
                  ✕
                </button>
              </span>
            )}

            {/* 标签 */}
            {tagFilter && (
              <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg bg-rose-50 dark:bg-rose-950/40 text-rose-700 dark:text-rose-300 font-medium border border-rose-200 dark:border-rose-800">
                <span>🏷 #{tagFilter}</span>
                <button
                  onClick={() => {
                    const p = new URLSearchParams(searchParams);
                    p.delete('tag');
                    setSearchParams(p);
                  }}
                  className="hover:text-rose-900 dark:hover:text-rose-100 font-bold ml-0.5 cursor-pointer"
                >
                  ✕
                </button>
              </span>
            )}

            {/* 商户 */}
            {(merchantFilter || merchantGroupFilter) && (
              <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg bg-orange-50 dark:bg-orange-950/40 text-orange-700 dark:text-orange-300 font-medium border border-orange-200 dark:border-orange-800">
                <span>{tx("🏬 商户:")} {merchantGroupFilter === 'other' ? tx('其他商户（合计）') : merchantFilter}</span>
                <button
                  onClick={() => {
                    const p = new URLSearchParams(searchParams);
                    p.delete('merchant');
                    p.delete('merchant_group');
                    setSearchParams(p);
                  }}
                  className="hover:text-orange-900 dark:hover:text-orange-100 font-bold ml-0.5 cursor-pointer"
                >
                  ✕
                </button>
              </span>
            )}

            {/* 状态 */}
            {statusFilter && (
              <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg bg-teal-50 dark:bg-teal-950/40 text-teal-700 dark:text-teal-300 font-medium border border-teal-200 dark:border-teal-800">
                <span>{tx("⏱️ 状态:")} {statusFilter.split(',').map((s) => (s === 'cleared' ? tx("已清算") : s === 'pending' ? tx("待入账") : s)).join('、')}</span>
                <button
                  onClick={() => {
                    const p = new URLSearchParams(searchParams);
                    p.delete('status');
                    setSearchParams(p);
                  }}
                  className="hover:text-teal-900 dark:hover:text-teal-100 font-bold ml-0.5 cursor-pointer"
                >
                  ✕
                </button>
              </span>
            )}

            {/* 金额区间 */}
            {(minAmountFilter || maxAmountFilter) && (
              <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg bg-zinc-100 dark:bg-zinc-800 text-zinc-700 dark:text-zinc-300 font-medium border border-zinc-200 dark:border-zinc-700">
                <span>💰 ¥{minAmountFilter || '0'} ~ ¥{maxAmountFilter || '∞'}</span>
                <button
                  onClick={() => {
                    const p = new URLSearchParams(searchParams);
                    p.delete('min_amount');
                    p.delete('max_amount');
                    setSearchParams(p);
                  }}
                  className="hover:text-zinc-900 dark:hover:text-zinc-100 font-bold ml-0.5 cursor-pointer"
                >
                  ✕
                </button>
              </span>
            )}

            {/* 日期区间 */}
            {startDateFilter && (
              <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg bg-blue-50 dark:bg-blue-950/40 text-blue-700 dark:text-blue-300 font-medium border border-blue-200 dark:border-blue-800">
                <span>📅 {startDateFilter === endDateFilter ? startDateFilter : tx("{p0} 至 {p1}", {p0: (startDateFilter), p1: (endDateFilter)})}</span>
                <button
                  onClick={() => {
                    const p = new URLSearchParams(searchParams);
                    p.delete('start_date');
                    p.delete('end_date');
                    p.delete('date');
                    setSearchParams(p);
                  }}
                  className="hover:text-blue-900 dark:hover:text-blue-100 font-bold ml-0.5 cursor-pointer"
                >
                  ✕
                </button>
              </span>
            )}

            {/* 搜索词 */}
            {querySearch && (
              <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg bg-zinc-100 dark:bg-zinc-800 text-zinc-700 dark:text-zinc-300 font-medium border border-zinc-200 dark:border-zinc-700">
                <span>🔍 "{querySearch}"</span>
                <button
                  onClick={() => {
                    const p = new URLSearchParams(searchParams);
                    p.delete('search');
                    setSearchParams(p);
                    setSearch('');
                  }}
                  className="hover:text-zinc-900 dark:hover:text-zinc-100 font-bold ml-0.5 cursor-pointer"
                >
                  ✕
                </button>
              </span>
            )}

            <button
              onClick={handleResetFilters}
              className="text-xs text-zinc-500 hover:text-zinc-900 dark:hover:text-zinc-200 underline ml-1 cursor-pointer"
            >{tx("清除全部")}</button>
          </div>
        )}
      </div>

      {/* ── 4. Search Bar & Filter Button (Exact 5.png) ── */}
      {activeTab === 'upcoming' ? (
        <ScheduledPlans onSelectTransaction={setSelectedTxnId} onChanged={() => fetchTransactions(true)} />
      ) : <>
      <div className="flex items-center gap-3">
        <form onSubmit={handleSearchSubmit} className="relative flex-1">
          <Search className="w-4 h-4 absolute left-3.5 top-1/2 -translate-y-1/2 text-zinc-400" />
          <input
            type="text"
            placeholder={tx("搜索交易名称、商户、卡号、分类...")}
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="w-full pl-10 pr-4 py-2.5 bg-white dark:bg-zinc-900 border border-zinc-200 dark:border-zinc-800 rounded-xl text-xs text-zinc-900 dark:text-zinc-100 placeholder-zinc-400 focus:outline-hidden focus:ring-2 focus:ring-zinc-400 shadow-2xs"
          />
        </form>

        <button
          data-testid="transactions-filter-btn"
          onClick={() => setIsFilterModalOpen(true)}
          className={`flex items-center gap-1.5 px-3.5 py-2.5 rounded-xl border text-xs font-semibold transition-all shadow-2xs cursor-pointer ${
            activeFilterCount > 0
              ? 'bg-zinc-900 text-white dark:bg-white dark:text-zinc-900 border-transparent ring-2 ring-zinc-900/10 dark:ring-white/20'
              : 'bg-white dark:bg-zinc-900 border-zinc-200 dark:border-zinc-800 text-zinc-700 dark:text-zinc-300 hover:bg-zinc-50 dark:hover:bg-zinc-800'
          }`}
        >
          <SlidersHorizontal className="w-3.5 h-3.5" />
          <span>{tx("筛选")}</span>
          {activeFilterCount > 0 && (
            <span className="ml-1 px-1.5 py-0.5 rounded-full text-[11px] font-bold bg-white text-zinc-900 dark:bg-zinc-900 dark:text-white">
              {activeFilterCount}
            </span>
          )}
        </button>
      </div>

      {/* ── 5. Column Headers (Aligned with row items) ── */}
      <div className="hidden sm:flex items-center px-3.5 sm:px-4 py-2 text-xs font-semibold text-zinc-400 border-b border-zinc-200/80 dark:border-zinc-800 select-none">
        <div className="flex-1 min-w-0 pr-4 text-left">
          <span>{tx("交易")}</span>
        </div>
        <div className="w-36 shrink-0 text-left">
          <span>{tx("分类")}</span>
        </div>
        <div className="w-32 shrink-0 text-right pr-0.5">
          <span>{tx("金额")}</span>
        </div>
      </div>

      {/* ── 6. Grouped Transaction List (Exact 5.png Date-Grouped Layout) ── */}
      {loading ? (
        <div className="py-24 flex flex-col items-center justify-center gap-3">
          <div className="w-8 h-8 border-2 border-zinc-900 dark:border-white border-t-transparent rounded-full animate-spin" />
          <span className="text-xs text-zinc-500">{tx("正在获取交易流水...")}</span>
        </div>
      ) : groupedTransactions.length === 0 ? (
        <div className="py-24 text-center text-sm text-zinc-400">{tx("未检索到符合条件的交易流水")}</div>
      ) : (
        <div className="space-y-6">
          {groupedTransactions.map((group) => {
            return (
              <div key={group.dateKey} className="space-y-1">
                {/* Date Header Row */}
                <div className="flex flex-col items-start gap-1 sm:flex-row sm:items-center sm:justify-between sm:gap-3 px-3.5 sm:px-4 py-2 bg-zinc-50/70 dark:bg-zinc-900/40 rounded-xl text-xs font-medium text-zinc-600 dark:text-zinc-400">
                  <span className="shrink-0 whitespace-nowrap font-semibold text-zinc-800 dark:text-zinc-200">
                    {dateLabel(group.displayDate)} · {group.items.length}
                  </span>

                  <span className="min-w-0 max-w-full break-words sm:text-right font-mono font-semibold text-zinc-700 dark:text-zinc-300">
                    {privacyMode ? '••••••' : formatCurrencyTotals(group.currencyTotals)}
                  </span>
                </div>

                {/* Date Group Items */}
                <div className="divide-y divide-zinc-100 dark:divide-zinc-800/60 bg-white dark:bg-zinc-900 rounded-xl border border-zinc-200/70 dark:border-zinc-800 shadow-xs overflow-hidden">
                  {group.items.map((txn) => {
                    const isSelected = selectedIds.has(txn.id);
                    const isRefund = txn.transaction_type === 'refund' || (txn.narration || '').includes("退款") || !!txn.refund_of_transaction_id;
                    const isTransfer = txn.transaction_type === 'transfer' || !!txn.transfer_id;
                    const badge = getTransactionInitialBadge(txn.narration);
                    const originalMoney = originalTransactionMoney(txn);
                    const amt = Number(originalMoney.amount) || 0;
                    const nativeSymbol = currencySymbol(originalMoney.currency);
                    const formattedAmt = Math.abs(amt).toLocaleString(currentLocale(), { minimumFractionDigits: 2, maximumFractionDigits: 2 });

                    const isMe = txn.account_is_owner !== undefined
                      ? txn.account_is_owner
                      : (!txn.account_owner ||
                         txn.account_owner === '我的' ||
                         txn.account_owner === '本人' ||
                         txn.account_owner === user?.username ||
                         txn.account_owner === user?.displayName);
                    const ownerName = !isMe ? (txn.account_owner_name || (txn.account_owner !== '我的' && txn.account_owner !== '本人' ? txn.account_owner : null)) : null;
                    const accTitle = txn.account_name || txn.institution_name || tx("银行账户");

                    const isPeerMe = txn.transfer_peer_is_owner !== undefined
                      ? txn.transfer_peer_is_owner
                      : (!txn.transfer_peer_owner_name ||
                         txn.transfer_peer_owner_name === '我的' ||
                         txn.transfer_peer_owner_name === '本人' ||
                         txn.transfer_peer_owner_name === user?.username ||
                         txn.transfer_peer_owner_name === user?.displayName);
                    const peerOwnerName = !isPeerMe ? txn.transfer_peer_owner_name : null;

                    // 辅助函数：渲染账户节点。本人账户绝不写“我的”，他人账户写上名字
                    const renderAccountNode = (accName, isAccountMe, accOwnerName, isSecondary = false) => {
                      if (!accName || accName === '外部账户') {
                        return <span className="text-zinc-400">{tx("外部账户")}</span>;
                      }
                      if (isAccountMe) {
                        return <span className={isSecondary ? "text-zinc-500 dark:text-zinc-400" : ""}>{accName}</span>;
                      }
                      const ownerLabel = accOwnerName || tx("共享成员");
                      return (
                        <span className={`inline-flex items-center gap-1 ${isSecondary ? 'text-zinc-600 dark:text-zinc-300' : 'text-purple-600 dark:text-purple-400'}`}>
                          <span className="font-semibold text-purple-600 dark:text-purple-400">{ownerLabel}</span>
                          <span className="font-normal text-zinc-400 dark:text-zinc-500">· {accName}</span>
                        </span>
                      );
                    };

                    const formattedExactTime = txn.occurred_at ? formatDateTime(txn.occurred_at).split(' ')[1] : null;

                    const renderAmount = () => {
                      if (privacyMode) return <span>••••••</span>;
                      if (isRefund) {
                        return (
                          <span className="inline-flex items-center gap-1 font-mono font-bold text-xs text-emerald-600 dark:text-emerald-400">
                            <Lock className="w-3 h-3 text-emerald-600" />
                            <span>+{nativeSymbol}{formattedAmt}</span>
                          </span>
                        );
                      }
                      if (isTransfer) {
                        return (
                          <span className="font-mono font-bold text-xs text-zinc-600 dark:text-zinc-300">
                            {nativeSymbol}{formattedAmt}
                          </span>
                        );
                      }
                      if (txn.transaction_type === 'income') {
                        return (
                          <span className="font-mono font-bold text-xs text-emerald-600 dark:text-emerald-400">
                            +{nativeSymbol}{formattedAmt}
                          </span>
                        );
                      }
                      if (txn.transaction_type === 'adjustment') {
                        const isMinus = (txn.narration || '').includes('(-') || (txn.notes && txn.notes.includes("减少"));
                        return (
                          <span className={`font-mono font-bold text-xs ${isMinus ? 'text-zinc-900 dark:text-zinc-100' : 'text-emerald-600 dark:text-emerald-400'}`}>
                            {isMinus ? '−' : '+'}{nativeSymbol}{formattedAmt}
                          </span>
                        );
                      }
                      return (
                        <span className="font-mono font-bold text-xs text-zinc-900 dark:text-zinc-100">
                          −{nativeSymbol}{formattedAmt}
                        </span>
                      );
                    };

                    return (
                      <div
                        key={txn.id}
                        data-testid="transaction-row"
                        onClick={() => setSelectedTxnId(txn.id)}
                        className="flex flex-col py-2 px-3.5 sm:px-4 hover:bg-zinc-50 dark:hover:bg-zinc-800/50 cursor-pointer transition-colors group"
                      >
                        <div className="flex items-center justify-between w-full">
                          {/* Left: Platform / Transaction Initial Logo + Name & Subtitle */}
                          <div className="flex items-center gap-3 flex-1 min-w-0 pr-3">
                            {/* Transaction Initial Logo Circle/Square (保留交易名称第一个字大写显示在前面) */}
                            <div
                              className={`w-7 h-7 rounded-lg ${badge.bg} font-bold text-xs flex items-center justify-center shrink-0 shadow-2xs select-none`}
                            >
                              {tx(badge.label)}
                            </div>

                            <div className="min-w-0 flex-1">
                              <div className="flex items-center gap-1.5 flex-wrap">
                                <span
                                  className="font-medium text-xs text-zinc-900 dark:text-zinc-100 group-hover:text-blue-600 dark:group-hover:text-blue-400 transition-colors break-words line-clamp-2 leading-snug"
                                  title={txn.narration || tx("日常消费")}
                                >
                                  {txn.narration || tx("日常消费")}
                                </span>

                                {isRefund && (
                                  <span className="inline-flex items-center gap-0.5 px-1.5 py-0.5 rounded text-[11px] leading-tight font-semibold bg-emerald-50 dark:bg-emerald-950/40 text-emerald-700 dark:text-emerald-300 border border-emerald-200 dark:border-emerald-800 whitespace-nowrap shrink-0">
                                    <RotateCcw className="w-2.5 h-2.5" />
                                    <span>{tx("退款")}</span>
                                  </span>
                                )}
                                {isTransfer && (
                                  <span className="inline-flex items-center gap-0.5 px-1.5 py-0.5 rounded text-[11px] leading-tight font-semibold bg-blue-50 dark:bg-blue-950/40 text-blue-700 dark:text-blue-300 border border-blue-200 dark:border-blue-800 whitespace-nowrap shrink-0">
                                    <ArrowRightLeft className="w-2.5 h-2.5" />
                                    <span>
                                      {txn.transfer_is_outflow === true
                                        ? tx("转账流出")
                                        : txn.transfer_is_outflow === false || (txn.narration || '').includes("转入") || (txn.narration || '').includes("收到")
                                        ? tx("转账流入")
                                        : tx("内部转账")}
                                    </span>
                                  </span>
                                )}
                                {txn.is_split && (
                                  <span className="inline-flex items-center gap-0.5 px-1.5 py-0.5 rounded text-[11px] leading-tight font-semibold bg-purple-50 dark:bg-purple-950/40 text-purple-700 dark:text-purple-300 border border-purple-200 dark:border-purple-800 whitespace-nowrap shrink-0">
                                    <Scissors className="w-2.5 h-2.5" />
                                    <span>{tx("已拆分")}</span>
                                  </span>
                                )}
                              </div>
                              <BookingMoneyInfo transaction={txn} privacy={privacyMode} />
                              <div className="text-[11px] text-zinc-400 dark:text-zinc-500 mt-0.5 min-w-0 flex items-center gap-1.5">
                                {isTransfer ? (
                                  <span className="font-semibold text-blue-600 dark:text-blue-400 flex items-center flex-wrap gap-x-1 gap-y-0.5 leading-tight">
                                    {txn.transfer_peer_account ? (
                                      txn.transfer_is_outflow ? (
                                        <>
                                          {renderAccountNode(accTitle, isMe, ownerName, true)}
                                          <span className="text-blue-500 font-bold shrink-0">➔</span>
                                          {renderAccountNode(txn.transfer_peer_account, isPeerMe, peerOwnerName, false)}
                                        </>
                                      ) : (
                                        <>
                                          {renderAccountNode(txn.transfer_peer_account, isPeerMe, peerOwnerName, true)}
                                          <span className="text-blue-500 font-bold shrink-0">➔</span>
                                          {renderAccountNode(accTitle, isMe, ownerName, false)}
                                        </>
                                      )
                                    ) : (
                                      (txn.narration || '').includes("转入") || (txn.narration || '').includes("收到") ? (
                                        <>
                                          <span className="text-zinc-400 shrink-0">{tx("外部账户")}</span>
                                          <span className="text-blue-500 font-bold shrink-0">➔</span>
                                          {renderAccountNode(accTitle, isMe, ownerName, false)}
                                        </>
                                      ) : (
                                        <>
                                          {renderAccountNode(accTitle, isMe, ownerName, true)}
                                          <span className="text-blue-500 font-bold shrink-0">➔</span>
                                          <span className="text-zinc-400 shrink-0">{tx("外部账户")}</span>
                                        </>
                                      )
                                    )}
                                  </span>
                                ) : (
                                  <>
                                    <span className="truncate font-normal max-w-[120px] sm:max-w-none flex items-center gap-1" title={accTitle}>
                                      {!isMe && ownerName ? (
                                        <span className="inline-flex items-center gap-1 text-purple-600 dark:text-purple-400 font-medium">
                                          <Users className="w-2.5 h-2.5 shrink-0" />
                                          <span>{ownerName}</span>
                                          <span className="text-zinc-400 dark:text-zinc-500 font-normal">· {accTitle}</span>
                                        </span>
                                      ) : (
                                        <span>{accTitle}</span>
                                      )}
                                    </span>
                                    {/* 移动端专享分类胶囊：紧随账户名右侧，释放右侧区域宽度 */}
                                    {txn.transaction_type !== 'transfer' && (
                                      <span
                                        data-testid="mobile-category-pill"
                                        className="sm:hidden inline-flex items-center gap-1 px-1.5 py-0.5 rounded-full text-[11px] font-medium bg-zinc-100 dark:bg-zinc-800 text-zinc-600 dark:text-zinc-300 border border-zinc-200/60 dark:border-zinc-700/60 shrink-0"
                                      >
                                        <span>{txn.category_icon || '📦'}</span>
                                        <span className="truncate max-w-[85px]">{categoryLabel(txn.category_name) || tx("日常消费")}</span>
                                      </span>
                                    )}
                                  </>
                                )}
                              </div>
                            </div>
                          </div>

                          {/* Center: Category Pill (Desktop only, exactly w-36 text-left to align with header) */}
                          <div className="hidden sm:flex items-center w-36 shrink-0 text-left">
                            {txn.transaction_type === 'transfer' ? (
                              <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-[11px] font-semibold bg-purple-50 dark:bg-purple-950/40 text-purple-700 dark:text-purple-300 border border-purple-200/60 dark:border-purple-800/60" title={tx("账户间内部转账，不计入收支分类")}>
                                <span>⇄</span>
                                <span className="truncate max-w-[90px]">{tx("内部转账")}</span>
                              </span>
                            ) : (
                              <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-[11px] font-semibold bg-zinc-100 dark:bg-zinc-800 text-zinc-700 dark:text-zinc-300 border border-zinc-200/60 dark:border-zinc-700/60">
                                <span>{txn.category_icon || '📦'}</span>
                                <span className="truncate max-w-[90px]">{categoryLabel(txn.category_name) || tx("日常消费")}</span>
                              </span>
                            )}
                          </div>

                          {/* Right: Amount & Time (Fixed w-32 for alignment) */}
                          <div className="w-auto sm:w-32 text-right shrink-0 flex flex-col items-end gap-0.5">
                            {renderAmount()}
                            <span className="text-[10px] text-zinc-500">{originalMoney.currency}</span>
                            {formattedExactTime && (
                              <span className="font-mono text-[11px] text-zinc-400 dark:text-zinc-500 tabular-nums leading-tight">
                                {formattedExactTime}
                              </span>
                            )}
                          </div>
                        </div>

                        {/* Line 3: 状态胶囊行 (待报销/代垫状态靠左对齐在所属账户正下方；不计支出靠右对齐在时间正下方) */}
                        {(txn.is_reimbursable || txn.extra?.reimbursement_type || txn.excluded_from_stats) && (
                          <div className="pt-1 pl-10 flex flex-wrap items-center justify-between gap-2 min-w-0">
                            {/* Left: 靠左对齐，放置于所属账户下方 */}
                            {(txn.is_reimbursable || txn.extra?.reimbursement_type) && (
                              <div className="flex items-center min-w-0 max-w-full sm:flex-1">
                                <ReimbursementBadge txn={txn} onStatusUpdated={handleTxnStatusUpdated} />
                              </div>
                            )}

                            {/* Right: 靠右对齐，放置于时间正下方 (与时间列宽对齐) */}
                            {txn.excluded_from_stats && (
                              <div className="ml-auto shrink-0 w-auto sm:w-32 flex items-center justify-end pr-0.5">
                                <span
                                  title={tx("此交易不计入家庭支出统计")}
                                  className="inline-flex items-center gap-0.5 px-1.5 py-0.5 rounded text-[11px] font-semibold bg-zinc-100 dark:bg-zinc-800 text-zinc-600 dark:text-zinc-300 border border-zinc-200/80 dark:border-zinc-700/80 select-none whitespace-nowrap"
                                >
                                  <span>{tx("🚫不计支出")}</span>
                                </span>
                              </div>
                            )}
                          </div>
                        )}
                      </div>
                    );
                    })}
                </div>
              </div>
            );
          })}
        </div>
      )}

      {/* ── 列表底部加载更多 / 完成状态栏 ── */}
      {!loading && transactions.length > 0 && (
        <div ref={loadMoreRef} className="py-8 flex flex-col items-center justify-center gap-2">
          {hasMore ? (
            <div className="flex flex-col items-center gap-2">
              <button
                type="button"
                data-testid="load-more-btn"
                onClick={() => fetchTransactions(false)}
                disabled={isLoadingMore}
                className="px-5 py-2.5 rounded-xl text-xs font-semibold bg-white dark:bg-zinc-800 border border-zinc-200 dark:border-zinc-700 text-zinc-700 dark:text-zinc-200 hover:bg-zinc-50 dark:hover:bg-zinc-700/60 shadow-2xs transition-all flex items-center gap-2 cursor-pointer disabled:opacity-60"
              >
                {isLoadingMore ? (
                  <>
                    <Loader2 className="w-4 h-4 animate-spin text-zinc-500" />
                    <span>{tx("正在载入更早之前的历史流水...")}</span>
                  </>
                ) : (
                  <>
                    <ArrowDown className="w-4 h-4 text-zinc-500" />
                    <span>{tx("加载更早交易（已显示")} {transactions.length}
                      {totalCount ? ` / ${totalCount}` : ''} {tx("笔）")}</span>
                  </>
                )}
              </button>
              <span className="text-[11px] text-zinc-400">{tx("向下滚动页面亦可自动连贯加载历史数据")}</span>
            </div>
          ) : (
            <div className="flex items-center gap-3 text-xs text-zinc-400 py-3">
              <span className="w-12 h-px bg-zinc-200 dark:bg-zinc-700" />
              <span>{tx("已完整显示全部")} {transactions.length} {tx("笔历史交易明细")}</span>
              <span className="w-12 h-px bg-zinc-200 dark:bg-zinc-700" />
            </div>
          )}
        </div>
      )}

      </>}

      {/* ── 7. Multi-Selection Floating Action Bar ── */}
      {selectedIds.size > 0 && (
        <div className="fixed bottom-6 left-1/2 -translate-x-1/2 z-40 bg-zinc-900 dark:bg-zinc-800 text-white px-5 py-3 rounded-2xl shadow-2xl flex items-center gap-4 border border-zinc-700 animate-in fade-in slide-in-from-bottom-3 duration-150">
          <span className="text-xs font-semibold">{tx("已选择")} <span className="font-mono font-bold text-amber-400">{selectedIds.size}</span> {tx("笔交易")}</span>

          <div className="h-4 w-px bg-zinc-700" />

          {selectedIds.size === 2 ? (
            <div className="flex items-center gap-2">
              <button
                onClick={handlePairSelectedAsTransfer}
                disabled={pairingLoading}
                className="px-3 py-1.5 rounded-lg bg-blue-600 hover:bg-blue-700 text-xs font-bold flex items-center gap-1.5 transition-colors shadow-xs"
              >
                <ArrowRightLeft className="w-3.5 h-3.5" />
                <span>{tx("配对为内部转账")}</span>
              </button>

              <button
                onClick={handleLinkSelectedAsRefund}
                disabled={pairingLoading}
                className="px-3 py-1.5 rounded-lg bg-emerald-600 hover:bg-emerald-700 text-xs font-bold flex items-center gap-1.5 transition-colors shadow-xs"
              >
                <RotateCcw className="w-3.5 h-3.5" />
                <span>{tx("冲抵为原消费退款")}</span>
              </button>
            </div>
          ) : (
            <span className="text-[11px] text-zinc-400">{tx("勾选 2 笔流水可一键撮合转账或退款冲抵")}</span>
          )}

          <button
            onClick={() => setSelectedIds(new Set())}
            className="text-xs text-zinc-400 hover:text-white transition-colors"
          >{tx("取消选择")}</button>
        </div>
      )}

      {/* ── 8. Transaction SlideOver Drawer ── */}
      {selectedTxnId && (
        <TransactionDrawer
          transactionId={selectedTxnId}
          onClose={() => setSelectedTxnId(null)}
          onTransactionUpdated={() => fetchTransactions(true)}
        />
      )}

      {/* ── 9. Multi-Dimensional Filter Modal ── */}
      <TransactionFilterModal
        isOpen={isFilterModalOpen}
        onClose={() => setIsFilterModalOpen(false)}
        currentFilters={{
          account_id: accountIdFilter,
          account_mask: accountMaskFilter,
          institution_name: institutionFilter,
          transaction_type: typeFilter,
          category_name: categoryNameFilter,
          is_refund: isRefundFilter,
          has_refund: hasRefundFilter,
          tag: tagFilter,
          min_amount: minAmountFilter,
          max_amount: maxAmountFilter,
          start_date: startDateFilter,
          end_date: endDateFilter,
        }}
        onApply={handleApplyFilterModal}
        onReset={handleResetFilters}
        accounts={accounts}
        filterOptions={filterOptions}
      />

      {/* ── 10. Add Transaction Modal (Sure Style Modal) ── */}
      <AddTransactionModal
        open={showAddModal}
        onClose={() => setShowAddModal(false)}
        onSuccess={() => fetchTransactions(true)}
      />

      {/* ── 11. Account Operation Modals (Exact 12.png) ── */}
      <EditAccountModal
        isOpen={!!editingAccount}
        onClose={() => setEditingAccount(null)}
        account={editingAccount}
        onSuccess={() => {
          fetchTransactions(true);
          // reload accounts
          fetchWithAuth('/api/v1/accounts')
            .then((r) => r.json())
            .then((d) => setAccounts(Array.isArray(d) ? d : d.accounts || []))
            .catch(() => {});
        }}
      />

      <AccountSharingModal
        accountId={sharingAccountId}
        isOpen={!!sharingAccountId}
        onClose={() => setSharingAccountId(null)}
        onSuccess={() => {
          fetchTransactions(true);
        }}
      />

      <TransferOwnershipModal
        isOpen={!!transferringAccount}
        onClose={() => setTransferringAccount(null)}
        account={transferringAccount}
        onSuccess={() => {
          fetchTransactions(true);
          fetchWithAuth('/api/v1/accounts')
            .then((r) => r.json())
            .then((d) => setAccounts(Array.isArray(d) ? d : d.accounts || []))
            .catch(() => {});
        }}
      />

      <DeleteAccountModal
        isOpen={!!deletingAccount}
        onClose={() => setDeletingAccount(null)}
        account={deletingAccount}
        onSuccess={() => {
          // Clear account filter if deleted
          const p = new URLSearchParams(searchParams);
          p.delete('account_id');
          p.delete('account_mask');
          setSearchParams(p);
          fetchTransactions(true);
          fetchWithAuth('/api/v1/accounts')
            .then((r) => r.json())
            .then((d) => setAccounts(Array.isArray(d) ? d : d.accounts || []))
            .catch(() => {});
        }}
      />

      <ImportTransactionsModal
        isOpen={!!importingAccount}
        onClose={() => setImportingAccount(null)}
        account={importingAccount}
        onSuccess={() => fetchTransactions(true)}
      />
    </div>
  );
}
