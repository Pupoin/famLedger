import React, { useState, useEffect, useCallback } from 'react';
import { useTranslation } from 'react-i18next';
import {
  Search,
  Filter,
  Plus,
  Scissors,
  ArrowLeftRight,
  RotateCcw,
  Sparkles,
  RefreshCw,
  CheckCircle,
} from 'lucide-react';
import { VirtualTransactionList } from '../components/ds/VirtualTransactionList';
import { Button, Card, Pill, Drawer } from '../components/ds/DesignSystem';
import { fetchWithAuth } from '../api/fetchWithAuth';

export default function TransactionsPage() {
  const { t } = useTranslation();
  const [transactions, setTransactions] = useState([]);
  const [loading, setLoading] = useState(true);
  const [isLoadingMore, setIsLoadingMore] = useState(false);
  const [hasMore, setHasMore] = useState(false);
  const [nextCursor, setNextCursor] = useState(null);

  // Filters
  const [search, setSearch] = useState('');
  const [typeFilter, setTypeFilter] = useState('');

  // Drawer details
  const [selectedTxn, setSelectedTxn] = useState(null);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [splits, setSplits] = useState([]);
  const [isSplitting, setIsSplitting] = useState(false);
  const [splitItems, setSplitItems] = useState([
    { amount: '', notes: '' },
    { amount: '', notes: '' },
  ]);

  const fetchTransactions = useCallback(async (reset = false) => {
    try {
      if (reset) {
        setLoading(true);
      } else {
        setIsLoadingMore(true);
      }

      const params = new URLSearchParams();
      params.append('limit', '50');
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
  }, [search, typeFilter]);

  useEffect(() => {
    fetchTransactions(true);
  }, [fetchTransactions]);

  const handleSelectTransaction = async (txn) => {
    setSelectedTxn(txn);
    setDrawerOpen(true);
    setIsSplitting(false);

    // If split, fetch splits
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

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold tracking-tight text-on-surface">
            交易明细
          </h1>
          <p className="text-sm text-on-surface-variant mt-1">
            60FPS 虚拟滚动低内存筛选引擎，支持转账/退款联动与多项拆分
          </p>
        </div>

        {/* Filter Toolbar */}
        <div className="flex items-center gap-3">
          <div className="relative">
            <Search className="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2 text-on-surface-variant" />
            <input
              type="text"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="搜索商户、摘要..."
              className="pl-9 pr-3 py-2 rounded-lg border border-outline/20 bg-surface-container text-on-surface text-sm focus-ring w-48 sm:w-64"
            />
          </div>

          <select
            value={typeFilter}
            onChange={(e) => setTypeFilter(e.target.value)}
            className="px-3 py-2 rounded-lg border border-outline/20 bg-surface-container text-on-surface text-sm focus-ring"
          >
            <option value="">全部类型</option>
            <option value="expense">支出</option>
            <option value="income">收入</option>
            <option value="transfer">内部转账</option>
            <option value="refund">退款冲抵</option>
          </select>
        </div>
      </div>

      {/* Main Virtualized List Container */}
      {loading ? (
        <div className="py-24 flex items-center justify-center">
          <span className="w-8 h-8 border-3 border-primary border-t-transparent rounded-full animate-spin" />
        </div>
      ) : transactions.length === 0 ? (
        <div className="py-24 text-center text-on-surface-variant">
          暂无匹配交易流水
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
            {/* Meta info card */}
            <Card className="space-y-2 text-xs font-mono">
              <div className="flex justify-between">
                <span className="text-on-surface-variant">流水 ID:</span>
                <span className="text-on-surface truncate max-w-[200px]">{selectedTxn.id}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-on-surface-variant">商户名称:</span>
                <span className="text-on-surface font-semibold">{selectedTxn.merchant_name || '—'}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-on-surface-variant">交易类型:</span>
                <span className="text-on-surface font-semibold">{selectedTxn.transaction_type}</span>
              </div>
              {selectedTxn.transfer_id && (
                <div className="flex justify-between text-blue-600 font-semibold">
                  <span>转账关联 ID:</span>
                  <span className="truncate max-w-[200px]">{selectedTxn.transfer_id}</span>
                </div>
              )}
              {selectedTxn.refund_of_transaction_id && (
                <div className="flex justify-between text-amber-600 font-semibold">
                  <span>原消费关联 ID:</span>
                  <span className="truncate max-w-[200px]">{selectedTxn.refund_of_transaction_id}</span>
                </div>
              )}
            </Card>

            {/* Split Section */}
            <div className="border-t border-outline/15 pt-5">
              <div className="flex items-center justify-between mb-4">
                <h4 className="font-semibold text-sm text-on-surface flex items-center gap-2">
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
                    <div key={idx} className="p-3 bg-surface-container rounded-lg flex items-center justify-between text-xs">
                      <div>
                        <span className="font-semibold text-on-surface block">{s.notes || `子项 ${idx + 1}`}</span>
                        <span className="text-on-surface-variant">拆分金额</span>
                      </div>
                      <span className="font-mono font-bold text-sm text-purple-600">
                        ¥{s.amount}
                      </span>
                    </div>
                  ))}
                </div>
              )}

              {isSplitting && (
                <div className="space-y-3 bg-surface-container/50 p-4 rounded-xl border border-outline/15">
                  <p className="text-xs text-on-surface-variant">
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
                        className="px-3 py-2 rounded-md border border-outline/20 bg-surface-container-lowest text-xs text-on-surface"
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
                        className="px-3 py-2 rounded-md border border-outline/20 bg-surface-container-lowest text-xs text-on-surface"
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
