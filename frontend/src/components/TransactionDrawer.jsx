import React, { useState, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import {
  X,
  CreditCard,
  Building2,
  Calendar,
  Clock,
  Tag,
  ArrowRightLeft,
  RotateCcw,
  Unlink,
  Link as LinkIcon,
  CheckCircle2,
  AlertCircle,
  Search,
  ExternalLink,
  Split,
  Trash2,
  ShieldAlert,
} from 'lucide-react';
import { fetchWithAuth } from '../api/fetchWithAuth';
import { useCurrency } from '../CurrencyContext';
import { useToast } from '../ToastContext';

export default function TransactionDrawer({
  transactionId,
  onClose,
  onTransactionUpdated,
}) {
  const { t } = useTranslation();
  const { fmt } = useCurrency();
  const { showToast } = useToast();

  const [loading, setLoading] = useState(true);
  const [txn, setTxn] = useState(null);

  // Refund pairing state
  const [candidates, setCandidates] = useState([]);
  const [candidateSearch, setCandidateSearch] = useState('');
  const [candidatesLoading, setCandidatesLoading] = useState(false);
  const [linkingLoading, setLinkingLoading] = useState(false);

  // Transfer pairing state
  const [transferCandidates, setTransferCandidates] = useState([]);
  const [transferLoading, setTransferLoading] = useState(false);
  const [pairingLoading, setPairingLoading] = useState(false);

  // Load detailed transaction
  const loadTransaction = async () => {
    if (!transactionId) return;
    try {
      setLoading(true);
      const res = await fetchWithAuth(`/api/v1/transactions/${transactionId}`);
      if (res.ok) {
        const data = await res.json();
        setTxn(data);
      } else {
        showToast('获取交易详情失败', 'error');
      }
    } catch (err) {
      console.error('Failed to load transaction detail', err);
      showToast('网络错误，无法加载交易详情', 'error');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadTransaction();
  }, [transactionId]);

  // Load refund candidates if it's an unlinked refund
  const loadRefundCandidates = async (searchQuery = '') => {
    if (!transactionId) return;
    try {
      setCandidatesLoading(true);
      const url = searchQuery
        ? `/api/v1/refunds/${transactionId}/candidates?search=${encodeURIComponent(searchQuery)}`
        : `/api/v1/refunds/${transactionId}/candidates`;
      const res = await fetchWithAuth(url);
      if (res.ok) {
        const data = await res.json();
        setCandidates(data.candidates || []);
      }
    } catch (err) {
      console.error('Failed to load refund candidates', err);
    } finally {
      setCandidatesLoading(false);
    }
  };

  // Load transfer candidates if it's not yet a transfer
  const loadTransferCandidates = async () => {
    if (!transactionId) return;
    try {
      setTransferLoading(true);
      const res = await fetchWithAuth(`/api/v1/transfers/candidates?transaction_id=${transactionId}`);
      if (res.ok) {
        const data = await res.json();
        setTransferCandidates(data.candidates || []);
      }
    } catch (err) {
      console.error('Failed to load transfer candidates', err);
    } finally {
      setTransferLoading(false);
    }
  };

  useEffect(() => {
    if (txn?.transaction_type === 'refund' && !txn?.refund_info?.is_linked) {
      loadRefundCandidates();
    }
  }, [txn]);

  // Handle linking a refund to an expense
  const handleLinkRefund = async (originalId, customAmount = null) => {
    try {
      setLinkingLoading(true);
      const url = customAmount
        ? `/api/v1/refunds/${txn.id}/link/${originalId}?allocated_amount=${customAmount}`
        : `/api/v1/refunds/${txn.id}/link/${originalId}`;
      const res = await fetchWithAuth(url, { method: 'POST' });
      if (res.ok) {
        showToast('已成功将退款与原消费冲抵关联！', 'success');
        loadTransaction();
        if (onTransactionUpdated) onTransactionUpdated();
      } else {
        const err = await res.json();
        showToast(err.detail || '关联失败', 'error');
      }
    } catch (err) {
      console.error('Error linking refund', err);
      showToast('网络请求失败', 'error');
    } finally {
      setLinkingLoading(false);
    }
  };

  // Handle unlinking a refund
  const handleUnlinkRefund = async () => {
    try {
      setLinkingLoading(true);
      const res = await fetchWithAuth(`/api/v1/refunds/${txn.id}/unlink`, { method: 'POST' });
      if (res.ok) {
        showToast('已解除退款冲抵关联', 'info');
        loadTransaction();
        if (onTransactionUpdated) onTransactionUpdated();
      } else {
        showToast('解除关联失败', 'error');
      }
    } catch (err) {
      console.error('Error unlinking refund', err);
      showToast('网络请求失败', 'error');
    } finally {
      setLinkingLoading(false);
    }
  };

  // Handle manual transfer pairing
  const handlePairTransfer = async (counterpartId) => {
    try {
      setPairingLoading(true);
      const isOut = Number(txn.amount) < 0 || txn.transaction_type === 'expense';
      const payload = {
        outflow_transaction_id: isOut ? txn.id : counterpartId,
        inflow_transaction_id: isOut ? counterpartId : txn.id,
      };
      const res = await fetchWithAuth('/api/v1/transfers/manual-pair', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      if (res.ok) {
        showToast('成功撮合并配对为内部转账！', 'success');
        loadTransaction();
        if (onTransactionUpdated) onTransactionUpdated();
      } else {
        const err = await res.json();
        showToast(err.detail || '转账配对失败', 'error');
      }
    } catch (err) {
      console.error('Error pairing transfer', err);
      showToast('网络请求失败', 'error');
    } finally {
      setPairingLoading(false);
    }
  };

  // Handle rejecting a transfer (break pair & blacklist)
  const handleRejectTransfer = async () => {
    if (!txn?.paired_transfer?.transfer_id) return;
    try {
      setPairingLoading(true);
      const res = await fetchWithAuth(
        `/api/v1/transfers/${txn.paired_transfer.transfer_id}/reject`,
        { method: 'POST' }
      );
      if (res.ok) {
        showToast('转账已解除并加入防自动合并黑名单', 'success');
        loadTransaction();
        if (onTransactionUpdated) onTransactionUpdated();
      } else {
        showToast('解除转账失败', 'error');
      }
    } catch (err) {
      console.error('Error rejecting transfer', err);
      showToast('网络请求失败', 'error');
    } finally {
      setPairingLoading(false);
    }
  };

  if (!transactionId) return null;

  return (
    <div className="fixed inset-0 z-50 overflow-hidden flex justify-end">
      {/* Backdrop */}
      <div
        onClick={onClose}
        className="fixed inset-0 bg-black/40 backdrop-blur-xs transition-opacity animate-in fade-in duration-200"
      />

      {/* Drawer Panel */}
      <aside className="relative w-full max-w-lg bg-white dark:bg-zinc-900 shadow-2xl h-full flex flex-col z-10 animate-in slide-in-from-right duration-200 border-l border-zinc-200 dark:border-zinc-800">
        {/* Top Header */}
        <div className="px-6 py-4 border-b border-zinc-200 dark:border-zinc-800 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <span className="text-xs font-semibold uppercase tracking-wider text-zinc-400">
              流水详情 (Transaction)
            </span>
          </div>
          <button
            onClick={onClose}
            className="w-8 h-8 rounded-lg text-zinc-500 hover:text-zinc-900 dark:hover:text-zinc-100 hover:bg-zinc-100 dark:hover:bg-zinc-800 flex items-center justify-center transition-colors"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Drawer Body */}
        <div className="flex-1 overflow-y-auto p-6 space-y-6 custom-scrollbar">
          {loading ? (
            <div className="py-24 flex flex-col items-center justify-center gap-3">
              <div className="w-8 h-8 border-2 border-zinc-900 dark:border-white border-t-transparent rounded-full animate-spin" />
              <span className="text-xs text-zinc-500">正在加载交易与关联数据...</span>
            </div>
          ) : !txn ? (
            <div className="py-24 text-center text-sm text-zinc-400">未找到此交易记录</div>
          ) : (
            <>
              {/* 1. Hero Amount & Merchant */}
              <div className="bg-zinc-50 dark:bg-zinc-800/40 rounded-2xl p-5 border border-zinc-200/80 dark:border-zinc-800/80 space-y-2">
                <div className="flex items-center justify-between">
                  <span className="text-xs font-medium text-zinc-500">
                    {txn.transaction_type === 'refund'
                      ? '退款流水 (Refund)'
                      : txn.transaction_type === 'transfer'
                      ? '内部转账 (Transfer)'
                      : txn.transaction_type === 'income'
                      ? '常规收入 (Income)'
                      : '生活支出 (Expense)'}
                  </span>
                  <span
                    className={`inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-xs font-semibold ${
                      txn.transaction_type === 'refund'
                        ? 'bg-emerald-50 dark:bg-emerald-950/40 text-emerald-600 dark:text-emerald-400 border border-emerald-200 dark:border-emerald-800'
                        : txn.transaction_type === 'transfer'
                        ? 'bg-blue-50 dark:bg-blue-950/40 text-blue-600 dark:text-blue-400 border border-blue-200 dark:border-blue-800'
                        : Number(txn.amount) > 0
                        ? 'bg-emerald-50 dark:bg-emerald-950/40 text-emerald-600 dark:text-emerald-400'
                        : 'bg-zinc-100 dark:bg-zinc-800 text-zinc-700 dark:text-zinc-300'
                    }`}
                  >
                    {txn.transaction_type === 'refund' && <RotateCcw className="w-3 h-3" />}
                    {txn.transaction_type === 'transfer' && <ArrowRightLeft className="w-3 h-3" />}
                    {txn.transaction_type === 'refund' ? '退款冲抵' : txn.transaction_type === 'transfer' ? '转账互转' : txn.status || '已入账'}
                  </span>
                </div>

                <div className="flex items-baseline justify-between pt-1">
                  <div className="text-3xl font-extrabold font-mono tracking-tight text-zinc-900 dark:text-white">
                    {txn.transaction_type === 'transfer'
                      ? `¥${Math.abs(Number(txn.amount)).toFixed(2)}`
                      : txn.transaction_type === 'refund' || Number(txn.amount) > 0
                      ? `+¥${Math.abs(Number(txn.amount)).toFixed(2)}`
                      : `-¥${Math.abs(Number(txn.amount)).toFixed(2)}`}
                  </div>
                </div>

                <div className="text-base font-semibold text-zinc-800 dark:text-zinc-200 pt-1">
                  {txn.name || txn.merchant_name || '未命名交易'}
                </div>
              </div>

              {/* 2. Key Metadata Attributes */}
              <div className="grid grid-cols-2 gap-3 text-xs">
                <div className="p-3 bg-zinc-50 dark:bg-zinc-800/30 rounded-xl border border-zinc-100 dark:border-zinc-800/60">
                  <span className="text-zinc-400 block mb-1">所属账户</span>
                  <div className="font-semibold text-zinc-800 dark:text-zinc-200 flex items-center gap-1.5 truncate">
                    <Building2 className="w-3.5 h-3.5 text-zinc-500 shrink-0" />
                    <span className="truncate">{txn.account_name}</span>
                  </div>
                </div>

                <div className="p-3 bg-zinc-50 dark:bg-zinc-800/30 rounded-xl border border-zinc-100 dark:border-zinc-800/60">
                  <span className="text-zinc-400 block mb-1">交易日期</span>
                  <div className="font-semibold text-zinc-800 dark:text-zinc-200 flex items-center gap-1.5 truncate">
                    <Calendar className="w-3.5 h-3.5 text-zinc-500 shrink-0" />
                    <span>{txn.transacted_at ? txn.transacted_at.slice(0, 10) : '-'}</span>
                  </div>
                </div>

                <div className="p-3 bg-zinc-50 dark:bg-zinc-800/30 rounded-xl border border-zinc-100 dark:border-zinc-800/60">
                  <span className="text-zinc-400 block mb-1">支出分类</span>
                  <div className="font-semibold text-zinc-800 dark:text-zinc-200 flex items-center gap-1.5">
                    <span className="text-sm">{txn.category_icon || '📦'}</span>
                    <span>{txn.category_name}</span>
                  </div>
                </div>

                <div className="p-3 bg-zinc-50 dark:bg-zinc-800/30 rounded-xl border border-zinc-100 dark:border-zinc-800/60">
                  <span className="text-zinc-400 block mb-1">商户归属</span>
                  <div className="font-semibold text-zinc-800 dark:text-zinc-200 truncate">
                    {txn.merchant_name || '平台自营 / 个人'}
                  </div>
                </div>
              </div>

              {/* 3. REFUND SECTION (退款冲抵管理 - 核心诉求) */}
              {txn.transaction_type === 'refund' && (
                <div className="p-4 rounded-xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-800/50 space-y-3">
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-2">
                      <RotateCcw className="w-4 h-4 text-emerald-600 dark:text-emerald-400" />
                      <span className="text-xs font-bold text-zinc-900 dark:text-white">
                        退款冲抵关联 (Refund Allocation)
                      </span>
                    </div>
                    {txn.refund_info?.is_linked ? (
                      <span className="px-2 py-0.5 rounded text-[11px] font-semibold bg-emerald-100 text-emerald-700 dark:bg-emerald-950 dark:text-emerald-300">
                        已关联原消费
                      </span>
                    ) : (
                      <span className="px-2 py-0.5 rounded text-[11px] font-semibold bg-amber-100 text-amber-700 dark:bg-amber-950 dark:text-amber-300">
                        待匹配冲抵
                      </span>
                    )}
                  </div>

                  {/* If linked: display original expense & unlink button */}
                  {txn.refund_info?.is_linked ? (
                    <div className="space-y-2">
                      <div className="p-3 rounded-lg bg-emerald-50/50 dark:bg-emerald-950/20 border border-emerald-200/60 dark:border-emerald-800/60 text-xs space-y-1">
                        <div className="text-zinc-500 text-[11px]">关联冲抵的原消费支出：</div>
                        <div className="font-bold text-zinc-900 dark:text-white text-sm">
                          {txn.refund_info.original_transaction?.name || txn.refund_info.original_transaction?.merchant_name}
                        </div>
                        <div className="flex items-center justify-between text-zinc-600 dark:text-zinc-400 pt-1">
                          <span>消费时间: {txn.refund_info.original_transaction?.transacted_at?.slice(0, 10)}</span>
                          <span className="font-mono font-bold text-zinc-900 dark:text-zinc-100">
                            原金额: ¥{txn.refund_info.original_transaction?.amount}
                          </span>
                        </div>
                        <div className="flex items-center justify-between text-emerald-700 dark:text-emerald-300 pt-1 font-semibold">
                          <span>已冲抵额度:</span>
                          <span className="font-mono">¥{txn.refund_info.allocated_amount}</span>
                        </div>
                      </div>

                      <button
                        onClick={handleUnlinkRefund}
                        disabled={linkingLoading}
                        className="w-full py-2 px-3 rounded-lg border border-rose-200 dark:border-rose-900/60 text-rose-600 dark:text-rose-400 hover:bg-rose-50 dark:hover:bg-rose-950/30 text-xs font-semibold flex items-center justify-center gap-1.5 transition-colors"
                      >
                        <Unlink className="w-3.5 h-3.5" />
                        <span>解除与原消费的冲抵关联</span>
                      </button>
                    </div>
                  ) : (
                    /* If not linked: show intelligent candidate recommendations & manual search */
                    <div className="space-y-3">
                      <p className="text-xs text-zinc-500 leading-relaxed">
                        根据系统蓝图规则，退款用于冲抵当期生活支出。以下为系统过去 90 天内根据商户相似度为您推荐的候选原消费：
                      </p>

                      {/* Search box for any expense */}
                      <div className="flex items-center gap-2">
                        <div className="relative flex-1">
                          <Search className="w-3.5 h-3.5 absolute left-2.5 top-1/2 -translate-y-1/2 text-zinc-400" />
                          <input
                            type="text"
                            placeholder="搜索历史消费商户名或备注..."
                            value={candidateSearch}
                            onChange={(e) => {
                              setCandidateSearch(e.target.value);
                              loadRefundCandidates(e.target.value);
                            }}
                            className="w-full pl-8 pr-3 py-1.5 bg-zinc-100 dark:bg-zinc-900 rounded-lg text-xs border border-zinc-200 dark:border-zinc-700 focus:outline-hidden focus:ring-1 focus:ring-zinc-400"
                          />
                        </div>
                      </div>

                      {/* Candidate list */}
                      <div className="space-y-2 max-h-56 overflow-y-auto custom-scrollbar">
                        {candidatesLoading ? (
                          <div className="py-6 text-center text-xs text-zinc-400">正在检索候选支出...</div>
                        ) : candidates.length === 0 ? (
                          <div className="py-6 text-center text-xs text-zinc-400">
                            未找到同商户候选消费，请输入商户名检索
                          </div>
                        ) : (
                          candidates.map((c) => (
                            <div
                              key={c.id}
                              className="p-2.5 rounded-lg border border-zinc-200 dark:border-zinc-700 hover:border-zinc-300 dark:hover:border-zinc-600 bg-zinc-50/50 dark:bg-zinc-900/50 flex items-center justify-between text-xs transition-colors"
                            >
                              <div className="min-w-0 pr-2">
                                <div className="font-semibold text-zinc-900 dark:text-white truncate">
                                  {c.name || c.merchant_name}
                                </div>
                                <div className="text-[11px] text-zinc-400 flex items-center gap-2">
                                  <span>{c.transacted_at.slice(0, 10)}</span>
                                  <span>剩余可冲抵: ¥{c.remaining_refundable}</span>
                                </div>
                              </div>
                              <button
                                onClick={() => handleLinkRefund(c.id)}
                                disabled={linkingLoading}
                                className="px-3 py-1.5 bg-zinc-900 dark:bg-white text-white dark:text-zinc-900 text-xs font-bold rounded-lg hover:opacity-90 transition-opacity shrink-0 flex items-center gap-1"
                              >
                                <LinkIcon className="w-3 h-3" />
                                <span>关联</span>
                              </button>
                            </div>
                          ))
                        )}
                      </div>
                    </div>
                  )}
                </div>
              )}

              {/* If Expense has been refunded */}
              {txn.transaction_type === 'expense' && txn.refund_info?.has_refunds && (
                <div className="p-4 rounded-xl border border-emerald-200 dark:border-emerald-800 bg-emerald-50/30 dark:bg-emerald-950/20 space-y-2">
                  <div className="flex items-center justify-between text-xs font-bold text-emerald-800 dark:text-emerald-300">
                    <span className="flex items-center gap-1.5">
                      <CheckCircle2 className="w-4 h-4 text-emerald-600" />
                      此笔消费已发生退款冲抵
                    </span>
                    <span className="font-mono">已抵消 ¥{txn.refund_info.total_refunded}</span>
                  </div>
                  <div className="space-y-1">
                    {txn.refund_info.refunds.map((r) => (
                      <div key={r.id} className="text-xs text-zinc-600 dark:text-zinc-400 flex justify-between">
                        <span>{r.name} ({r.transacted_at.slice(0, 10)})</span>
                        <span className="font-mono text-emerald-600 dark:text-emerald-400">¥{r.allocated_amount}</span>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* 4. TRANSFER SECTION (内部转账管理 - 核心诉求) */}
              <div className="p-4 rounded-xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-800/50 space-y-3">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <ArrowRightLeft className="w-4 h-4 text-blue-600 dark:text-blue-400" />
                    <span className="text-xs font-bold text-zinc-900 dark:text-white">
                      内部转账仲裁 (Transfer Arbitration)
                    </span>
                  </div>
                  {txn.transaction_type === 'transfer' ? (
                    <span className="px-2 py-0.5 rounded text-[11px] font-semibold bg-blue-100 text-blue-700 dark:bg-blue-950 dark:text-blue-300">
                      已配对转账
                    </span>
                  ) : (
                    <span className="px-2 py-0.5 rounded text-[11px] font-semibold bg-zinc-100 text-zinc-600 dark:bg-zinc-800 dark:text-zinc-400">
                      单边独立流水
                    </span>
                  )}
                </div>

                {/* If paired transfer: display counterpart & reject button */}
                {txn.paired_transfer ? (
                  <div className="space-y-2">
                    <div className="p-3 rounded-lg bg-blue-50/50 dark:bg-blue-950/20 border border-blue-200/60 dark:border-blue-800/60 text-xs space-y-1">
                      <div className="text-zinc-500 text-[11px]">
                        {txn.paired_transfer.is_outflow ? '流出到对端账户：' : '自对端账户流入：'}
                      </div>
                      <div className="font-bold text-zinc-900 dark:text-white text-sm">
                        {txn.paired_transfer.counterpart?.account_name} · {txn.paired_transfer.counterpart?.name}
                      </div>
                      <div className="flex items-center justify-between text-zinc-600 dark:text-zinc-400 pt-1">
                        <span>记账时间: {txn.paired_transfer.counterpart?.transacted_at?.slice(0, 10)}</span>
                        <span className="font-mono font-bold text-zinc-900 dark:text-zinc-100">
                          ¥{txn.paired_transfer.counterpart?.amount}
                        </span>
                      </div>
                    </div>

                    <button
                      onClick={handleRejectTransfer}
                      disabled={pairingLoading}
                      className="w-full py-2 px-3 rounded-lg border border-rose-200 dark:border-rose-900/60 text-rose-600 dark:text-rose-400 hover:bg-rose-50 dark:hover:bg-rose-950/30 text-xs font-semibold flex items-center justify-center gap-1.5 transition-colors"
                    >
                      <ShieldAlert className="w-3.5 h-3.5" />
                      <span>人工仲裁解除配对（恢复为独立收支并永久拉黑）</span>
                    </button>
                  </div>
                ) : (
                  /* If not transfer: offer pairing */
                  <div className="space-y-2">
                    <button
                      onClick={loadTransferCandidates}
                      className="w-full py-2 px-3 rounded-lg bg-zinc-100 dark:bg-zinc-800 hover:bg-zinc-200 dark:hover:bg-zinc-700 text-zinc-800 dark:text-zinc-200 text-xs font-semibold flex items-center justify-center gap-1.5 transition-colors"
                    >
                      <ArrowRightLeft className="w-3.5 h-3.5" />
                      <span>检索同额对端流水（配对为内部转账）</span>
                    </button>

                    {transferLoading ? (
                      <div className="py-4 text-center text-xs text-zinc-400">正在查找对端交易...</div>
                    ) : transferCandidates.length > 0 ? (
                      <div className="space-y-1.5 pt-1">
                        <div className="text-[11px] text-zinc-400">找到以下同额候选交易：</div>
                        {transferCandidates.map((tc) => (
                          <div
                            key={tc.id}
                            className="p-2 rounded-lg border border-zinc-200 dark:border-zinc-700 flex items-center justify-between text-xs bg-zinc-50 dark:bg-zinc-900/40"
                          >
                            <div>
                              <div className="font-semibold text-zinc-800 dark:text-zinc-200">
                                {tc.account_name} · {tc.name}
                              </div>
                              <div className="text-[11px] text-zinc-400">
                                {tc.transacted_at.slice(0, 10)} · 金额: ¥{tc.amount}
                              </div>
                            </div>
                            <button
                              onClick={() => handlePairTransfer(tc.id)}
                              disabled={pairingLoading}
                              className="px-2.5 py-1 bg-blue-600 hover:bg-blue-700 text-white rounded text-xs font-bold transition-colors"
                            >
                              配对
                            </button>
                          </div>
                        ))}
                      </div>
                    ) : null}
                  </div>
                )}
              </div>

              {/* 5. NOTES & RAW AUDIT */}
              <div className="space-y-2 text-xs">
                <span className="font-semibold text-zinc-700 dark:text-zinc-300">备注说明 (Notes)</span>
                <div className="p-3 bg-zinc-50 dark:bg-zinc-800/30 rounded-xl border border-zinc-100 dark:border-zinc-800/60 text-zinc-600 dark:text-zinc-400 leading-relaxed font-sans">
                  {txn.notes || '暂无额外备注信息'}
                </div>
              </div>
            </>
          )}
        </div>

        {/* Drawer Footer */}
        <div className="px-6 py-4 border-t border-zinc-200 dark:border-zinc-800 flex items-center justify-between">
          <button
            onClick={onClose}
            className="px-4 py-2 rounded-xl text-xs font-semibold text-zinc-600 dark:text-zinc-300 hover:bg-zinc-100 dark:hover:bg-zinc-800 transition-colors"
          >
            关闭抽屉
          </button>
          <div className="text-[11px] font-mono text-zinc-400">
            UUID: {txn?.id?.slice(0, 8)}...
          </div>
        </div>
      </aside>
    </div>
  );
}
