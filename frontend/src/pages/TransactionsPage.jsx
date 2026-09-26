import React, { useState, useEffect, useCallback, useMemo } from 'react';
import { useSearchParams, Link } from 'react-router-dom';
import {
  Search,
  Plus,
  Scissors,
  ArrowLeftRight,
  RotateCcw,
  SlidersHorizontal,
  Upload,
  MoreHorizontal,
  CreditCard,
  Wallet,
} from 'lucide-react';
import { VirtualTransactionList } from '../components/ds/VirtualTransactionList';
import { Button, Card, Drawer } from '../components/ds/DesignSystem';
import { fetchWithAuth } from '../api/fetchWithAuth';
import { useCurrency } from '../CurrencyContext';

export default function TransactionsPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const accountIdFilter = searchParams.get('account_id') || '';
  const { fmt, privacyMode } = useCurrency();

  const [accounts, setAccounts] = useState([]);
  const [transactions, setTransactions] = useState([]);
  const [loading, setLoading] = useState(true);
  const [isLoadingMore, setIsLoadingMore] = useState(false);
  const [hasMore, setHasMore] = useState(false);
  const [nextCursor, setNextCursor] = useState(null);

  // Filters
  const [search, setSearch] = useState('');
  const [typeFilter, setTypeFilter] = useState('');
  const [activeTab, setActiveTab] = useState('transactions'); // 'transactions' | 'upcoming'

  // Drawer details
  const [selectedTxn, setSelectedTxn] = useState(null);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [splits, setSplits] = useState([]);
  const [isSplitting, setIsSplitting] = useState(false);
  const [splitItems, setSplitItems] = useState([
    { amount: '', notes: '' },
    { amount: '', notes: '' },
  ]);

  useEffect(() => {
    fetchWithAuth('/api/v1/accounts')
      .then((r) => r.json())
      .then((d) => setAccounts(Array.isArray(d) ? d : (d.accounts || d.items || [])))
      .catch((err) => console.error('Failed to load accounts', err));
  }, []);

  const fetchTransactions = useCallback(async (reset = false) => {
    try {
      if (reset) {
        setLoading(true);
      } else {
        setIsLoadingMore(true);
      }

      const params = new URLSearchParams();
      params.append('limit', '50');
      if (accountIdFilter) params.append('account_id', accountIdFilter);
      if (search) params.append('search', search);
      if (typeFilter) params.append('transaction_type', typeFilter);

      const res = await fetchWithAuth(`/api/v1/transactions?${params.toString()}`);
      if (res.ok) {
        const data = await res.json();
        setTransactions(reset ? data.items : (prev) => [...prev, ...data.items]);
        setHasMore(data.has_more);
        setNextCursor(data.next_cursor);
      }
    } catch (err) {
      console.error('Failed to fetch transactions', err);
    } finally {
      setLoading(false);
      setIsLoadingMore(false);
    }
  }, [accountIdFilter, search, typeFilter]);

  useEffect(() => {
    fetchTransactions(true);
  }, [fetchTransactions]);

  const handleSelectTransaction = async (txn) => {
    setSelectedTxn(txn);
    setDrawerOpen(true);
    setIsSplitting(false);

    if (txn.is_split) {
      try {
        const res = await fetchWithAuth(`/api/v1/transactions/${txn.id}/splits`);
        if (res.ok) {
          const s = await res.json();
          setSplits(s);
        }
      } catch (err) {
        console.error('Failed to fetch splits', err);
      }
    } else {
      setSplits([]);
      const half = (Math.abs(Number(txn.amount)) / 2).toFixed(2);
      setSplitItems([
        { amount: half, notes: '子项目 1' },
        { amount: (Math.abs(Number(txn.amount)) - Number(half)).toFixed(2), notes: '子项目 2' },
      ]);
    }
  };

  const handleApplySplit = async () => {
    if (!selectedTxn) return;
    try {
      const res = await fetchWithAuth(`/api/v1/transactions/${selectedTxn.id}/split`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          splits: splitItems.map((s) => ({
            amount: Number(s.amount),
            notes: s.notes,
          })),
        }),
      });
      if (res.ok) {
        setIsSplitting(false);
        setDrawerOpen(false);
        fetchTransactions(true);
      } else {
        const err = await res.json();
        alert(err.detail || '拆分失败');
      }
    } catch (err) {
      console.error('Split failed', err);
    }
  };

  // Metrics summary
  const metrics = useMemo(() => {
    const totalCount = accounts.reduce((s, a) => s + (a.transaction_count || 0), 0);
    let totalExpense = 0;
    let totalIncome = 0;
    transactions.forEach((t) => {
      const amt = Number(t.amount) || 0;
      if (t.transaction_type === 'refund' || amt < 0) {
        totalIncome += Math.abs(amt);
      } else if (t.transaction_type === 'expense') {
        totalExpense += amt;
      }
    });
    return {
      count: totalCount,
      income: totalIncome,
      expense: totalExpense,
    };
  }, [accounts, transactions]);

  const currentAccount = accounts.find((a) => a.id === accountIdFilter);

  return (
    <div className="space-y-6">
      {/* ── 1. Page Header (Exact Sure Header) ── */}
      <div className="flex items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl sm:text-3xl font-bold tracking-tight text-zinc-900 dark:text-zinc-100 flex items-center gap-2">
            <span>Transactions</span>
            {currentAccount && (
              <span className="text-xs px-2.5 py-1 rounded-lg bg-zinc-100 dark:bg-zinc-800 text-zinc-700 dark:text-zinc-300 font-mono font-semibold border border-zinc-200 dark:border-zinc-700">
                {currentAccount.institution_name} *{currentAccount.mask}
              </span>
            )}
          </h1>
        </div>

        <div className="flex items-center gap-2">
          <button
            title="更多操作"
            className="p-2 rounded-lg border border-zinc-200 dark:border-zinc-700 text-zinc-600 dark:text-zinc-400 hover:bg-zinc-100 dark:hover:bg-zinc-800 transition-colors"
          >
            <MoreHorizontal className="w-4 h-4" />
          </button>
          <button
            title="导入交易"
            className="hidden sm:inline-flex items-center gap-1.5 px-3 py-2 text-sm font-medium rounded-lg border border-zinc-200 dark:border-zinc-700 text-zinc-700 dark:text-zinc-200 bg-white dark:bg-zinc-800 hover:bg-zinc-50 dark:hover:bg-zinc-700 transition-colors"
          >
            <Upload className="w-4 h-4" />
            <span>Import</span>
          </button>
          <Link
            to="/add"
            title="记新账 / 新增交易"
            className="inline-flex items-center justify-center w-9 h-9 sm:w-auto sm:px-3 sm:py-2 text-sm font-medium rounded-full sm:rounded-lg bg-zinc-900 hover:bg-zinc-800 text-white shadow-xs transition-colors active:scale-95"
          >
            <Plus className="w-4 h-4" />
            <span className="hidden sm:inline ml-1.5">New transaction</span>
          </Link>
        </div>
      </div>

      {/* ── 2. Sure 3-Segment Metric Box (Total / Income / Expenses) ── */}
      <div className="rounded-2xl border border-zinc-200/80 dark:border-zinc-800 bg-white dark:bg-zinc-900 grid grid-cols-1 sm:grid-cols-3 divide-y sm:divide-y-0 sm:divide-x divide-zinc-200/80 dark:divide-zinc-800 p-4 shadow-xs">
        <div className="p-3">
          <p className="text-xs font-semibold text-zinc-500 uppercase tracking-wider">
            Total transactions
          </p>
          <p className="text-2xl font-bold font-mono text-zinc-900 dark:text-zinc-100 mt-1">
            {metrics.count}
          </p>
        </div>

        <div className="p-3">
          <p className="text-xs font-semibold text-zinc-500 uppercase tracking-wider">
            Income
          </p>
          <p className="text-2xl font-bold font-mono text-emerald-600 dark:text-emerald-400 mt-1">
            {fmt(metrics.income)}
          </p>
        </div>

        <div className="p-3">
          <p className="text-xs font-semibold text-zinc-500 uppercase tracking-wider">
            Expenses
          </p>
          <p className="text-2xl font-bold font-mono text-zinc-900 dark:text-zinc-100 mt-1">
            {fmt(metrics.expense)}
          </p>
        </div>
      </div>

      {/* ── 3. Tabs (Transactions / Upcoming) ── */}
      <div className="flex items-center gap-2">
        <div className="inline-flex p-1 bg-zinc-100 dark:bg-zinc-800 rounded-xl">
          <button
            onClick={() => setActiveTab('transactions')}
            className={`px-3.5 py-1.5 text-xs font-semibold rounded-lg transition-all ${
              activeTab === 'transactions'
                ? 'bg-white dark:bg-zinc-700 text-zinc-900 dark:text-white shadow-xs'
                : 'text-zinc-500 hover:text-zinc-800 dark:hover:text-zinc-200'
            }`}
          >
            Transactions
          </button>
          <button
            onClick={() => setActiveTab('upcoming')}
            className={`px-3.5 py-1.5 text-xs font-semibold rounded-lg transition-all ${
              activeTab === 'upcoming'
                ? 'bg-white dark:bg-zinc-700 text-zinc-900 dark:text-white shadow-xs'
                : 'text-zinc-500 hover:text-zinc-800 dark:hover:text-zinc-200'
            }`}
          >
            Upcoming
          </button>
        </div>
      </div>

      {/* ── 4. Card Filter Pills Bar (Sure Style) ── */}
      <div className="flex items-center gap-2 overflow-x-auto pb-1 pt-0.5 scrollbar-none -mx-4 px-4 sm:mx-0 sm:px-0">
        <button
          onClick={() => {
            const p = new URLSearchParams(searchParams);
            p.delete('account_id');
            setSearchParams(p);
          }}
          className={`px-3 py-1.5 rounded-xl text-xs font-semibold whitespace-nowrap transition-all flex items-center gap-1.5 shrink-0 ${
            !accountIdFilter
              ? 'bg-zinc-900 text-white shadow-xs'
              : 'bg-white dark:bg-zinc-800 hover:bg-zinc-50 dark:hover:bg-zinc-700/60 text-zinc-600 dark:text-zinc-300 border border-zinc-200 dark:border-zinc-700'
          }`}
        >
          <Wallet className="w-3.5 h-3.5" />
          <span>全部卡号</span>
          <span className={`text-[10px] font-mono px-1.5 py-0.2 rounded-full font-bold ${!accountIdFilter ? 'bg-white/20 text-white' : 'bg-zinc-100 dark:bg-zinc-700 text-zinc-600 dark:text-zinc-300'}`}>
            {metrics.count}
          </span>
        </button>

        {accounts.map((acc) => {
          const isSelected = accountIdFilter === acc.id;
          const isCredit = acc.account_type === 'credit_card' || acc.classification === 'liability';

          return (
            <button
              key={acc.id}
              onClick={() => {
                const p = new URLSearchParams(searchParams);
                p.set('account_id', acc.id);
                setSearchParams(p);
              }}
              className={`px-3 py-1.5 rounded-xl text-xs font-semibold whitespace-nowrap transition-all flex items-center gap-1.5 shrink-0 border ${
                isSelected
                  ? 'bg-zinc-900 text-white border-zinc-900 shadow-xs'
                  : 'bg-white dark:bg-zinc-800 hover:bg-zinc-50 dark:hover:bg-zinc-700/60 border-zinc-200 dark:border-zinc-700 text-zinc-600 dark:text-zinc-300'
              }`}
            >
              <CreditCard className={`w-3.5 h-3.5 ${isSelected ? 'text-white' : isCredit ? 'text-amber-500' : 'text-emerald-500'}`} />
              <span>{acc.institution_name} *{acc.mask}</span>
              <span className={`text-[10px] font-mono px-1.5 py-0.2 rounded-full font-bold ${isSelected ? 'bg-white/20 text-white' : 'bg-zinc-100 dark:bg-zinc-700 text-zinc-600 dark:text-zinc-300'}`}>
                {acc.transaction_count || 0}
              </span>
            </button>
          );
        })}
      </div>

      {/* ── 5. Search & Filter Bar (Sure Style) ── */}
      <div className="flex items-center gap-3">
        <div className="relative flex-1">
          <Search className="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2 text-zinc-400" />
          <input
            type="text"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search transactions ..."
            className="w-full pl-9 pr-3 py-2 text-sm bg-white dark:bg-zinc-900 border border-zinc-200/80 dark:border-zinc-800 rounded-xl outline-none focus:border-zinc-900 dark:focus:border-white text-zinc-900 dark:text-white placeholder:text-zinc-400 transition-colors shadow-2xs"
          />
        </div>

        <div className="relative shrink-0">
          <div className="flex items-center gap-2 px-3.5 py-2 rounded-xl border border-zinc-200/80 dark:border-zinc-800 bg-white dark:bg-zinc-900 text-zinc-800 dark:text-zinc-200 text-sm hover:bg-zinc-50 dark:hover:bg-zinc-800 shadow-2xs transition-colors cursor-pointer">
            <SlidersHorizontal className="w-4 h-4 text-zinc-500" />
            <span className="font-medium">{typeFilter ? `Filter: ${typeFilter}` : 'Filter'}</span>
          </div>
          <select
            value={typeFilter}
            onChange={(e) => setTypeFilter(e.target.value)}
            className="absolute inset-0 opacity-0 cursor-pointer w-full h-full"
            aria-label="Filter transactions by type"
          >
            <option value="">All types</option>
            <option value="expense">支出 (Expenses)</option>
            <option value="income">收入 (Income)</option>
            <option value="transfer">内部转账 (Transfers)</option>
            <option value="refund">退款冲抵 (Refunds)</option>
          </select>
        </div>
      </div>

      {/* ── 6. Virtualized Transaction List ── */}
      {loading ? (
        <div className="py-24 flex items-center justify-center">
          <span className="w-6 h-6 border-2 border-zinc-900 dark:border-white border-t-transparent rounded-full animate-spin" />
        </div>
      ) : transactions.length === 0 ? (
        <div className="py-24 text-center text-sm text-zinc-400">
          No entries found
        </div>
      ) : (
        <VirtualTransactionList
          items={transactions}
          onSelectTransaction={handleSelectTransaction}
          selectedId={selectedTxn?.id}
          hasMore={hasMore}
          isLoadingMore={isLoadingMore}
          onLoadMore={() => fetchTransactions(false)}
        />
      )}

      {/* Transaction Detail & Split Drawer */}
      <Drawer
        isOpen={drawerOpen}
        onClose={() => setDrawerOpen(false)}
        title={selectedTxn?.name || '交易详情'}
        subtitle={`交易日期: ${selectedTxn?.transacted_at} · 金额: ¥${selectedTxn?.amount}`}
        footer={
          isSplitting ? (
            <>
              <Button variant="tertiary" onClick={() => setIsSplitting(false)}>
                取消拆分
              </Button>
              <Button variant="primary" onClick={handleApplySplit}>
                确认拆分
              </Button>
            </>
          ) : (
            <Button variant="secondary" onClick={() => setDrawerOpen(false)}>
              关闭
            </Button>
          )
        }
      >
        {selectedTxn && (
          <div className="space-y-6">
            <Card className="space-y-2 text-xs font-mono">
              <div className="flex justify-between">
                <span className="text-zinc-400">流水 ID:</span>
                <span className="truncate max-w-[200px]">{selectedTxn.id}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-zinc-400">所属银行卡:</span>
                <span className="font-semibold">{selectedTxn.account_name || '招商银行'} (*{selectedTxn.account_mask})</span>
              </div>
              <div className="flex justify-between">
                <span className="text-zinc-400">商户名称:</span>
                <span className="font-semibold">{selectedTxn.merchant_name || '—'}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-zinc-400">交易类型:</span>
                <span className="font-semibold">{selectedTxn.transaction_type}</span>
              </div>
            </Card>

            {/* Split Section */}
            <div className="border-t border-zinc-200 dark:border-zinc-800 pt-5">
              <div className="flex items-center justify-between mb-4">
                <h4 className="font-semibold text-sm flex items-center gap-2">
                  <Scissors className="w-4 h-4 text-purple-600" />
                  交易分拆 (Split)
                </h4>
                {!isSplitting && !selectedTxn.is_split && (
                  <Button size="sm" variant="outline" onClick={() => setIsSplitting(true)}>
                    拆分此交易
                  </Button>
                )}
              </div>

              {selectedTxn.is_split && splits.length > 0 && (
                <div className="space-y-2">
                  {splits.map((s, idx) => (
                    <div key={idx} className="p-3 bg-zinc-100 dark:bg-zinc-800 rounded-lg flex items-center justify-between text-xs">
                      <div>
                        <span className="font-semibold block">{s.notes || `子项 ${idx + 1}`}</span>
                        <span className="text-zinc-500">拆分金额</span>
                      </div>
                      <span className="font-mono font-bold text-sm text-purple-600">
                        ¥{s.amount}
                      </span>
                    </div>
                  ))}
                </div>
              )}

              {isSplitting && (
                <div className="space-y-3 bg-zinc-50 dark:bg-zinc-800/50 p-4 rounded-xl border border-zinc-200 dark:border-zinc-700">
                  <p className="text-xs text-zinc-500">
                    子项目总金额必须等于交易本金 ¥{Math.abs(Number(selectedTxn.amount)).toFixed(2)}
                  </p>
                  {splitItems.map((item, idx) => (
                    <div key={idx} className="grid grid-cols-2 gap-2">
                      <input
                        type="number"
                        step="0.01"
                        value={item.amount}
                        onChange={(e) => {
                          const updated = [...splitItems];
                          updated[idx].amount = e.target.value;
                          setSplitItems(updated);
                        }}
                        placeholder="金额 ¥"
                        className="px-3 py-2 rounded-md border border-zinc-200 dark:border-zinc-700 bg-white dark:bg-zinc-900 text-xs text-zinc-900 dark:text-white"
                      />
                      <input
                        type="text"
                        value={item.notes}
                        onChange={(e) => {
                          const updated = [...splitItems];
                          updated[idx].notes = e.target.value;
                          setSplitItems(updated);
                        }}
                        placeholder="子分类/备注说明"
                        className="px-3 py-2 rounded-md border border-zinc-200 dark:border-zinc-700 bg-white dark:bg-zinc-900 text-xs text-zinc-900 dark:text-white"
                      />
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>
        )}
      </Drawer>
    </div>
  );
}
