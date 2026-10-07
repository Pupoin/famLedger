import { categoryLabel, tx, useLocale } from "../localization.js";
import { apiErrorMessage } from '../api/errorMessages';
import TransactionAmount from './TransactionAmount';
import { currencySymbol, formatCurrency } from '../utils/currency';
import BookingMoneyInfo from './BookingMoneyInfo';
import React, { useState, useEffect, useRef } from 'react';
import { useTranslation } from 'react-i18next';
import { X, Building2, Clock, Tag, ArrowRightLeft, RotateCcw, Unlink, Link as LinkIcon, CheckCircle2, Search, Scissors, Trash2, Loader2, ShieldAlert, Users, Ban, Check, Lock, Unlock, Edit3, Save, SlidersHorizontal } from 'lucide-react';
import { fetchWithAuth } from '../api/fetchWithAuth';
import { useCurrency } from '../CurrencyContext';
import { useToast } from '../ToastContext';
import { formatDateTime, toLocalISODate, toLocalISOTime, localToUTCISO } from '../utils/dates';
import { getReimbursementSummary, resolveCounterpartyName, formatReimbursementStatus } from '../utils/reimbursement';
import { formatAccountWithEmoji } from '../utils/accountIcons';
import SplitTransactionModal from './SplitTransactionModal';
import DeleteTransactionModal from './DeleteTransactionModal';
import TransferDestinationFields from './TransferDestinationFields';
import RefundEditFields from './RefundEditFields';
import RefundCategoryField, { transactionCategoryLabel } from './RefundCategoryField';
import { buildRefundAllocation } from '../utils/refundAllocation';

export default function TransactionDrawer({
  transactionId,
  onClose,
  onTransactionUpdated,
}) {
  useLocale();
  const { t } = useTranslation();
  const { currencies, currency, privacyMode } = useCurrency();
  const { showToast } = useToast();

  const [loading, setLoading] = useState(true);
  const [txn, setTxn] = useState(null);
  const detailRequest = useRef(0);
  const activeTransactionId = useRef(transactionId);
  activeTransactionId.current = transactionId;
  const refundSectionRef = useRef(null);

  // Refund pairing state
  const [candidates, setCandidates] = useState([]);
  const [candidateSearch, setCandidateSearch] = useState('');
  const candidateRequest = useRef(0);
  const [candidatesLoading, setCandidatesLoading] = useState(false);
  const [candidateError, setCandidateError] = useState('');
  const [recommendationsOnly, setRecommendationsOnly] = useState(true);
  const [linkingLoading, setLinkingLoading] = useState(false);

  // Transfer pairing state
  const [transferCandidates, setTransferCandidates] = useState([]);
  const [transferLoading, setTransferLoading] = useState(false);
  const [pairingLoading, setPairingLoading] = useState(false);
  const [reimbLoading, setReimbLoading] = useState(false);
  const [showSplitModal, setShowSplitModal] = useState(false);

  // Editing state (locked by default, unlock to edit)
  const [isEditing, setIsEditing] = useState(false);
  const [editName, setEditName] = useState('');
  const [editAmount, setEditAmount] = useState('');
  const [editOriginalAmount, setEditOriginalAmount] = useState('');
  const [editOriginalCurrency, setEditOriginalCurrency] = useState('');
  const [editMasterAmount, setEditMasterAmount] = useState('');
  const [editType, setEditType] = useState('expense');
  const [editTransferDirection, setEditTransferDirection] = useState('outflow');
  const [editPeerAccountId, setEditPeerAccountId] = useState('');
  const [editPeerAmount, setEditPeerAmount] = useState('');
  const [editRefundOriginalId, setEditRefundOriginalId] = useState('');
  const [editAllocationAmount, setEditAllocationAmount] = useState('');
  const [editRefundAllocationAmount, setEditRefundAllocationAmount] = useState('');
  const [editDate, setEditDate] = useState('');
  const [editTime, setEditTime] = useState('');
  const [editAccountId, setEditAccountId] = useState('');
  const [editCategoryId, setEditCategoryId] = useState('');
  const [categoryTouched, setCategoryTouched] = useState(false);
  const [editNotes, setEditNotes] = useState('');
  const [editTags, setEditTags] = useState([]);
  const [tagInput, setTagInput] = useState('');
  const [availableTags, setAvailableTags] = useState([]);
  const [allCategories, setAllCategories] = useState([]);
  const [editIsReimbursable, setEditIsReimbursable] = useState(false);
  const [editExcludedFromStats, setEditExcludedFromStats] = useState(false);
  const [editReimbType, setEditReimbType] = useState('corporate');
  const [editCounterparty, setEditCounterparty] = useState('');
  const [editReimbStatus, setEditReimbStatus] = useState('审批中');
  const [allAccounts, setAllAccounts] = useState([]);
  const [saving, setSaving] = useState(false);
  const [showDeleteModal, setShowDeleteModal] = useState(false);
  const [deleteScope, setDeleteScope] = useState(null);
  const [deleting, setDeleting] = useState(false);
  const refundCategoryLocked = txn?.transaction_type === 'refund' && txn.refund_info?.category_editable === false;
  const displayedCategoryName = transactionCategoryLabel(txn);
  const transferOutflow = txn?.funds_direction === 'outflow'
    || (txn?.funds_direction == null && txn?.paired_transfer?.is_outflow === true);

  const handleStartEditing = () => {
    if (!txn) return;
    setEditName(txn.narration || '');
    setEditAmount(txn.amount ? String(Math.abs(Number(txn.amount))) : '');
    setEditOriginalAmount(txn.original_amount || '');
    setEditOriginalCurrency(txn.original_currency || '');
    setEditMasterAmount(txn.master_settlement_amount || '');
    setEditType(txn.transaction_type || 'expense');
    setEditTransferDirection(txn.funds_direction || (['income', 'refund'].includes(txn.transaction_type) ? 'inflow' : 'outflow'));
    setEditPeerAccountId(txn.paired_transfer?.counterpart?.account_id || '');
    setEditPeerAmount(txn.paired_transfer?.counterpart?.amount || '');
    setEditRefundOriginalId('');
    setEditAllocationAmount('');
    setEditRefundAllocationAmount('');

    const rawTime = txn.occurred_at;
    if (rawTime) {
      let s = String(rawTime).trim();
      if (!s.includes('Z') && !s.includes('+') && !s.includes('T')) {
        s = s.replace(' ', 'T') + 'Z';
      } else if (s.includes(' ') && !s.includes('T')) {
        s = s.replace(' ', 'T');
      }
      const d = new Date(s);
      if (!isNaN(d.getTime())) {
        setEditDate(toLocalISODate(d));
        setEditTime(toLocalISOTime(d, true));
      } else {
        const parts = s.replace('T', ' ').split(' ');
        setEditDate(parts[0] || toLocalISODate(new Date()));
        const cleanTime = (parts[1] || '00:00:00').replace(/[^\d:]/g, '').slice(0, 8);
        setEditTime(cleanTime);
      }
    } else if (txn.transacted_at) {
      setEditDate(txn.transacted_at.slice(0, 10));
      setEditTime('00:00:00');
    } else {
      const now = new Date();
      setEditDate(toLocalISODate(now));
      setEditTime(toLocalISOTime(now, true));
    }

    setEditAccountId(txn.account_id || '');
    const matchedCategory = allCategories.find(
      (c) => c.id === txn.category_id || c.name === txn.category_name
    );
    setEditCategoryId(matchedCategory ? matchedCategory.id : (txn.category_id || ''));
    setCategoryTouched(false);
    setEditNotes(txn.notes || '');

    // 初始化多标签 (tags 列表)
    setEditTags(Array.isArray(txn.tags) ? [...txn.tags] : []);
    setTagInput('');

    // 初始化报销信息
    const isReimb = Boolean(txn.is_reimbursable || txn.extra?.reimbursement_type);
    setEditIsReimbursable(isReimb);
    setEditExcludedFromStats(Boolean(txn.excluded_from_stats));
    const rType = txn.extra?.reimbursement_type || 'corporate';
    setEditReimbType(rType);
    const cpName = resolveCounterpartyName(
      txn.counterparty || txn.extra?.counterparty,
      rType === 'corporate' ? '公司' : '张三'
    );
    setEditCounterparty(cpName);
    setEditReimbStatus(formatReimbursementStatus(txn.reimbursement_status, rType === 'corporate'));

    fetchWithAuth('/api/v1/accounts')
      .then((r) => r.json())
      .then((data) => {
        setAllAccounts(Array.isArray(data) ? data : data.accounts || data.items || []);
      })
      .catch(() => {});

    fetchWithAuth('/api/v1/categories')
      .then((r) => r.json())
      .then((data) => {
        const cats = Array.isArray(data) ? data : data.categories || data.items || [];
        if (cats.length > 0) setAllCategories(cats);
      })
      .catch(() => {});

    fetchWithAuth('/api/v1/tags')
      .then((r) => r.json())
      .then((data) => {
        setAvailableTags(data.tags || data.items || []);
      })
      .catch(() => {});

    setIsEditing(true);
  };

  const handleSaveEdit = async (e) => {
    e?.preventDefault();
    if (!editName.trim()) {
      showToast(tx("请输入交易名称"), 'error');
      return;
    }
    if (!editAmount || isNaN(Number(editAmount))) {
      showToast(tx("请输入有效金额"), 'error');
      return;
    }
    const request = detailRequest.current;

    try {
      setSaving(true);
      const reimbursable = ['expense', 'income'].includes(editType) && editIsReimbursable;
      const refundOriginal = candidates.find(row => row.id === editRefundOriginalId);
      const allocation = editType === 'refund' && editRefundOriginalId ? buildRefundAllocation(
        { ...txn, original_amount: editOriginalAmount || txn.original_amount,
          original_currency: editOriginalCurrency || txn.original_currency },
        refundOriginal, editAllocationAmount, editRefundAllocationAmount) : null;
      const originalTime = txn.occurred_at ? new Date(txn.occurred_at) : null;
      const timeChanged = editDate !== (originalTime ? toLocalISODate(originalTime) : txn.transacted_at)
        || editTime !== (originalTime ? toLocalISOTime(originalTime, true) : '00:00:00');
      const payload = {
        ...(editName.trim() !== txn.narration ? { narration: editName.trim() } : {}),
        amount: editAmount,
        ...((String(editOriginalAmount) !== String(txn.original_amount || '') || editOriginalCurrency !== (txn.original_currency || '')) && editOriginalAmount && editOriginalCurrency ? {
          original_amount: editOriginalAmount, original_currency: editOriginalCurrency,
          settlement_amount: editAmount, settlement_currency: allAccounts.find(a => a.id === editAccountId)?.currency || txn.currency
        } : {}),
        ...(editMasterAmount && (String(editMasterAmount) !== String(txn.master_settlement_amount || '') || String(editOriginalAmount) !== String(txn.original_amount || '') || Number(editAmount) !== Number(txn.amount)) ? {
          master_settlement_amount: editMasterAmount,
          master_settlement_currency: (allAccounts.find(a => a.id === editAccountId)?.parent_account)?.currency || txn.master_settlement_currency
        } : {}),
        ...(editType !== txn.transaction_type ? { transaction_type: editType } : {}),
        ...(editType === 'refund' && editRefundOriginalId ? {
          refund_of_transaction_id: editRefundOriginalId,
          allocation_amount: allocation.allocated_amount, allocation_currency: allocation.original_currency,
          refund_original_amount: allocation.refund_original_amount,
        } : {}),
        ...(editType === 'transfer' ? { transfer_direction: editTransferDirection } : {}),
        ...(editType === 'transfer' && editPeerAccountId
          && (!txn.paired_transfer || editPeerAccountId !== txn.paired_transfer.counterpart.account_id)
          ? { [editTransferDirection === 'outflow' ? 'to_account_id' : 'from_account_id']: editPeerAccountId } : {}),
        ...(editType === 'transfer' && editPeerAccountId
          && allAccounts.find(account => account.id === editPeerAccountId)?.currency !== (allAccounts.find(account => account.id === editAccountId)?.currency || txn.currency)
          && editPeerAmount && (!txn.paired_transfer || editPeerAccountId !== txn.paired_transfer.counterpart.account_id
            || Number(editPeerAmount) !== Number(txn.paired_transfer.counterpart.amount) || Number(editAmount) !== Number(txn.amount) || editAccountId !== txn.account_id)
          ? { [editTransferDirection === 'outflow' ? 'destination_amount' : 'source_amount']: editPeerAmount } : {}),
        ...(editType === 'transfer' && editAccountId !== txn.account_id
          && allAccounts.find(account => account.id === editAccountId)?.currency !== txn.currency
          ? { settlement_amount: editAmount, settlement_currency: allAccounts.find(account => account.id === editAccountId)?.currency } : {}),
        ...(timeChanged ? { date: editDate, time: editTime, occurred_at: localToUTCISO(editDate, editTime) } : {}),
        account_id: editAccountId || txn.account_id,
        ...(categoryTouched && !refundCategoryLocked ? { category_id: editCategoryId || null } : {}),
        tags: editTags,
        notes: editNotes.trim(),
        is_reimbursable: reimbursable,
        excluded_from_stats: editExcludedFromStats,
        reimbursement_type: reimbursable ? editReimbType : null,
        counterparty: reimbursable
          ? (editCounterparty.trim() || (editReimbType === 'corporate' ? '公司' : '张三'))
          : null,
        reimbursement_status: reimbursable ? editReimbStatus : null,
      };

      const res = await fetchWithAuth(`/api/v1/transactions/${txn.id}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });

      if (res.ok) {
        const updated = await res.json();
        if (request === detailRequest.current) {
          setTxn(updated);
          setIsEditing(false);
        }
        showToast(tx("交易明细修改成功"), 'success');
        if (onTransactionUpdated) onTransactionUpdated();
        window.dispatchEvent(new CustomEvent('transaction-updated', { detail: { id: txn.id } }));
        window.dispatchEvent(new CustomEvent('accounts-updated'));
        return request === detailRequest.current ? updated : null;
      } else {
        const err = await res.json().catch(() => ({}));
        showToast(tx(apiErrorMessage(err.detail, '修改交易失败')), 'error');
      }
    } catch (err) {
      console.error('Failed to update transaction', err);
      showToast(tx(err.message || "网络请求失败"), 'error');
    } finally {
      setSaving(false);
    }
  };

  // Load detailed transaction
  const loadTransaction = async () => {
    if (!transactionId || activeTransactionId.current !== transactionId) return;
    const request = ++detailRequest.current;
    try {
      setLoading(true);
      const res = await fetchWithAuth(`/api/v1/transactions/${transactionId}`);
      if (request !== detailRequest.current || activeTransactionId.current !== transactionId) return;
      if (res.ok) {
        const data = await res.json();
        if (request === detailRequest.current) setTxn(data);
      } else {
        showToast(tx("获取交易详情失败"), 'error');
      }
    } catch (err) {
      if (request !== detailRequest.current) return;
      console.error('Failed to load transaction detail', err);
      showToast(tx("网络错误，无法加载交易详情"), 'error');
    } finally {
      if (request === detailRequest.current) setLoading(false);
    }
  };

  useEffect(() => {
    setShowDeleteModal(false);
    setDeleteScope(null);
    setIsEditing(false);
    setShowSplitModal(false);
    setCandidates([]);
    setCandidateSearch('');
    setCandidateError('');
    setRecommendationsOnly(true);
    setEditRefundOriginalId('');
    candidateRequest.current += 1;
    loadTransaction();
    return () => { detailRequest.current += 1; };
  }, [transactionId, currency]);

  // Categories are needed by the split dialog even when the editor stays locked.
  useEffect(() => {
    let active = true;
    fetchWithAuth('/api/v1/categories').then(async response => {
      if (!response.ok) throw new Error('分类加载失败');
      const data = await response.json();
      if (active) setAllCategories(Array.isArray(data) ? data : data.categories || data.items || []);
    }).catch(() => { if (active) showToast(tx('分类加载失败'), 'error'); });
    return () => { active = false; };
  }, [transactionId]);

  const loadRefundCandidates = async (searchQuery = '', onlyRecommended = recommendationsOnly) => {
    if (!transactionId) return;
    const request = ++candidateRequest.current;
    try {
      setCandidatesLoading(true);
      setCandidateError('');
      const params = new URLSearchParams({ recommendations_only: String(onlyRecommended) });
      if (searchQuery.trim()) params.set('search', searchQuery.trim());
      if (txn?.transaction_type !== 'refund') params.set('preview_refund', 'true');
      const url = `/api/v1/refunds/${transactionId}/candidates?${params}`;
      const res = await fetchWithAuth(url);
      if (res.ok) {
        const data = await res.json();
        if (request === candidateRequest.current) setCandidates(data.candidates || []);
      } else {
        const data = await res.json().catch(() => ({}));
        if (request === candidateRequest.current) {
          setCandidates([]);
          setCandidateError(tx(apiErrorMessage(data.detail, '读取退款候选失败')));
        }
      }
    } catch (err) {
      console.error('Failed to load refund candidates', err);
      if (request === candidateRequest.current) { setCandidates([]); setCandidateError(tx('读取退款候选失败')); }
    } finally {
      if (request === candidateRequest.current) setCandidatesLoading(false);
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
    if ((isEditing ? editType === 'refund' : txn?.transaction_type === 'refund') && !txn?.refund_info?.is_fully_allocated) {
      loadRefundCandidates(candidateSearch);
    }
  }, [txn, isEditing, editType]);

  // Handle linking a refund to an expense
  const handleLinkRefund = async () => {
    const request = detailRequest.current;
    try {
      setLinkingLoading(true);
      const original = candidates.find(c => c.id === editRefundOriginalId);
      const payload = buildRefundAllocation(txn, original, editAllocationAmount, editRefundAllocationAmount);
      const res = await fetchWithAuth(`/api/v1/refunds/${txn.id}/allocate`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload),
      });
      if (res.ok) {
        showToast(tx("已成功将退款与原消费冲抵关联！"), 'success');
        window.dispatchEvent(new CustomEvent('transaction-updated'));
        if (request === detailRequest.current) {
          setEditRefundOriginalId(''); setEditAllocationAmount(''); setEditRefundAllocationAmount('');
          await loadTransaction();
        }
        if (onTransactionUpdated) onTransactionUpdated();
      } else {
        const err = await res.json().catch(() => ({}));
        showToast(tx(apiErrorMessage(err.detail, '关联失败')), 'error');
      }
    } catch (err) {
      console.error('Error linking refund', err);
      showToast(tx(err.message || "网络请求失败"), 'error');
    } finally {
      setLinkingLoading(false);
    }
  };

  // Handle unlinking a refund
  const handleUnlinkRefund = async () => {
    const request = detailRequest.current;
    try {
      setLinkingLoading(true);
      const res = await fetchWithAuth(`/api/v1/refunds/${txn.id}/unlink`, { method: 'POST' });
      if (res.ok) {
        showToast(tx("已解除退款冲抵关联"), 'info');
        window.dispatchEvent(new CustomEvent('transaction-updated'));
        if (request === detailRequest.current) {
          setEditRefundOriginalId(''); setEditAllocationAmount(''); setEditRefundAllocationAmount('');
          await loadTransaction();
        }
        if (onTransactionUpdated) onTransactionUpdated();
      } else {
        const data = await res.json().catch(() => ({}));
        showToast(tx(apiErrorMessage(data.detail, '解除关联失败')), 'error');
      }
    } catch (err) {
      console.error('Error unlinking refund', err);
      showToast(tx("网络请求失败"), 'error');
    } finally {
      setLinkingLoading(false);
    }
  };

  const renderRefundFields = (editing) => <RefundEditFields
    transaction={editing ? { ...txn, original_amount: editOriginalAmount || txn.original_amount,
      original_currency: editOriginalCurrency || txn.original_currency } : txn}
    candidates={candidates} loading={candidatesLoading} error={candidateError}
    search={candidateSearch} onSearch={query => {
      setCandidateSearch(query); setEditRefundOriginalId(''); loadRefundCandidates(query);
    }}
    originalId={editRefundOriginalId} onOriginalChange={id => {
      setEditRefundOriginalId(id); setEditAllocationAmount(''); setEditRefundAllocationAmount('');
    }}
    originalAmount={editAllocationAmount} onOriginalAmountChange={setEditAllocationAmount}
    refundAmount={editRefundAllocationAmount} onRefundAmountChange={setEditRefundAllocationAmount}
    currency={editing ? editOriginalCurrency || txn.original_currency : txn.original_currency}
    onUnlink={handleUnlinkRefund} unlinking={linkingLoading || saving} privacyMode={privacyMode}
    onAllocate={editing ? undefined : handleLinkRefund}
    canManage={!loading && txn?.id === transactionId && txn?.deletion_info?.can_edit !== false && !txn?.extra?.scheduled_occurrence_id}
    recommendationsOnly={recommendationsOnly} onRecommendationsChange={enabled => {
      const query = enabled ? '' : candidateSearch;
      setRecommendationsOnly(enabled); setCandidateSearch(query); setEditRefundOriginalId('');
      setEditAllocationAmount(''); setEditRefundAllocationAmount('');
      loadRefundCandidates(query, enabled);
    }} />;

  // Handle manual transfer pairing
  const handlePairTransfer = async (counterpartId) => {
    try {
      setPairingLoading(true);
      const isOut = txn.funds_direction === 'outflow';
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
        showToast(tx("成功撮合并配对为内部转账！"), 'success');
        loadTransaction();
        if (onTransactionUpdated) onTransactionUpdated();
      } else {
        const err = await res.json();
        showToast(tx(apiErrorMessage(err.detail, '转账配对失败')), 'error');
      }
    } catch (err) {
      console.error('Error pairing transfer', err);
      showToast(tx("网络请求失败"), 'error');
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
        showToast(tx("转账已解除并加入防自动合并黑名单"), 'success');
        loadTransaction();
        if (onTransactionUpdated) onTransactionUpdated();
      } else {
        showToast(tx("解除转账失败"), 'error');
      }
    } catch (err) {
      console.error('Error rejecting transfer', err);
      showToast(tx("网络请求失败"), 'error');
    } finally {
      setPairingLoading(false);
    }
  };

  // Handle updating reimbursement settings
  const handleUpdateReimbursement = async (updates) => {
    try {
      setReimbLoading(true);
      const res = await fetchWithAuth(`/api/v1/transactions/${txn.id}/reimbursement`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(updates),
      });
      if (res.ok) {
        showToast(tx("报销设置已更新"), 'success');
        loadTransaction();
        if (onTransactionUpdated) onTransactionUpdated();
      } else {
        showToast(tx("更新报销失败"), 'error');
      }
    } catch (err) {
      console.error('Error updating reimbursement', err);
      showToast(tx("网络请求失败"), 'error');
    } finally {
      setReimbLoading(false);
    }
  };

  // Handle deleting this transaction
  const handleDeleteTransaction = async (scope) => {
    if (!txn?.id || deleting || txn.id !== transactionId) return;
    const transferId = txn.deletion_info?.transfer_id || txn.paired_transfer?.transfer_id;
    if (transferId && !['single', 'pair'].includes(scope)) return;
    const request = detailRequest.current;
    try {
      setDeleting(true);
      const params = new URLSearchParams({ scope });
      if (transferId) params.set('expected_transfer_id', transferId);
      const res = await fetchWithAuth(`/api/v1/transactions/${txn.id}?${params}`, {
        method: 'DELETE',
      });
      if (res.ok) {
        showToast(tx("交易已成功删除"), 'success');
        if (request === detailRequest.current) { setShowDeleteModal(false); onClose(); }
        if (onTransactionUpdated) onTransactionUpdated();
        window.dispatchEvent(new CustomEvent('transaction-deleted', { detail: { id: txn.id } }));
        window.dispatchEvent(new CustomEvent('transaction-added'));
        window.dispatchEvent(new CustomEvent('accounts-updated'));
      } else {
        const err = await res.json().catch(() => ({}));
        showToast(tx(apiErrorMessage(err.detail, '删除交易失败')), 'error');
        if (res.status === 409 && request === detailRequest.current) {
          setDeleteScope(null);
          loadTransaction();
        }
      }
    } catch {
      showToast(tx("网络请求错误，请稍后重试"), 'error');
    } finally {
      setDeleting(false);
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
        <div data-testid="transaction-drawer-header" className="px-6 py-4 border-b border-zinc-200 dark:border-zinc-800 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <span className="text-xs font-semibold uppercase tracking-wider text-zinc-400">{tx("流水详情 (Transaction)")}</span>
          </div>
          <div className="flex items-center gap-2">
            {txn && (
              <button
                type="button"
                data-testid="toggle-edit-lock-btn"
                disabled={loading || txn.id !== transactionId || txn.deletion_info?.can_edit === false || !!txn?.extra?.scheduled_occurrence_id}
                onClick={() => {
                  if (isEditing) {
                    setIsEditing(false);
                  } else {
                    handleStartEditing();
                  }
                }}
                className={`p-1.5 rounded-lg transition-colors cursor-pointer ${
                  isEditing
                    ? 'bg-amber-100 text-amber-800 dark:bg-amber-950/60 dark:text-amber-300 border border-amber-300 dark:border-amber-700'
                    : 'text-zinc-500 hover:text-zinc-900 dark:hover:text-zinc-100 hover:bg-zinc-100 dark:hover:bg-zinc-800'
                }`}
                title={isEditing ? tx("编辑中 (点击锁定)") : tx("点击解锁编辑")}
              >
                {isEditing ? (
                  <Unlock className="w-4 h-4 text-amber-600 dark:text-amber-400" />
                ) : (
                  <Lock className="w-4 h-4" />
                )}
              </button>
            )}
            <button
              onClick={onClose}
              className="w-8 h-8 rounded-lg text-zinc-500 hover:text-zinc-900 dark:hover:text-zinc-100 hover:bg-zinc-100 dark:hover:bg-zinc-800 flex items-center justify-center transition-colors cursor-pointer"
            >
              <X className="w-5 h-5" />
            </button>
          </div>
        </div>

        {/* Drawer Body */}
        <div className="flex-1 overflow-y-auto p-6 space-y-6 custom-scrollbar">
          {loading || (txn && txn.id !== transactionId) ? (
            <div className="py-24 flex flex-col items-center justify-center gap-3">
              <div className="w-8 h-8 border-2 border-zinc-900 dark:border-white border-t-transparent rounded-full animate-spin" />
              <span className="text-xs text-zinc-500">{tx("正在加载交易与关联数据...")}</span>
            </div>
          ) : !txn ? (
            <div className="py-24 text-center text-sm text-zinc-400">{tx("未找到此交易记录")}</div>
          ) : (
            <>
              {/* 0. 编辑模式表单 (允许修改：交易时间、分类、账户、记账类型、金额、名称、备注) */}
              {isEditing && (
                <form onSubmit={handleSaveEdit} className="p-4 rounded-xl border-2 border-blue-500/80 bg-blue-50/20 dark:bg-blue-950/20 space-y-4 shadow-sm animate-in fade-in duration-150">
                  <div className="flex items-center justify-between pb-2 border-b border-blue-200/60 dark:border-blue-900/60">
                    <div className="flex items-center gap-2">
                      <Edit3 className="w-4 h-4 text-blue-600 dark:text-blue-400" />
                      <span className="text-xs font-bold text-zinc-900 dark:text-white">{tx("编辑交易信息")}</span>
                    </div>
                    <span className="text-[11px] text-blue-600 dark:text-blue-400 font-medium">{tx("已解锁编辑")}</span>
                  </div>

                  {/* 1. 记账类型选择 */}
                  <div className="space-y-1.5">
                    <label className="text-[11px] font-semibold text-zinc-500 dark:text-zinc-400">{tx("记账类型 (收支属性)")}</label>
                    <div className="grid grid-cols-4 gap-1.5">
                      {[
                        { id: 'expense', label: '支出', icon: '🛒' },
                        { id: 'income', label: '收入', icon: '💰' },
                        { id: 'transfer', label: '转账', icon: '⇄' },
                        { id: 'refund', label: '退款', icon: '↺' },
                      ].map((t) => (
                        <button
                          key={t.id}
                          type="button"
                          data-testid={`edit-type-${t.id}`}
                          disabled={t.id !== txn.transaction_type && (Boolean(txn.paired_transfer)
                            || Boolean(txn.deletion_info?.has_refund_links || txn.deletion_info?.linked_refund_count)
                            || Boolean(txn.is_split && !['expense', 'refund'].includes(t.id)))}
                          onClick={() => {
                            setEditType(t.id);
                            if (!['expense', 'income'].includes(t.id) && editIsReimbursable) {
                              setEditIsReimbursable(false);
                              setEditExcludedFromStats(false);
                            }
                            if (t.id !== editType && t.id !== 'transfer') {
                              const selected = allCategories.find(category => category.id === editCategoryId);
                              if (selected?.category_type !== (t.id === 'refund' ? 'expense' : t.id)) setEditCategoryId('');
                              setCategoryTouched(true);
                            }
                          }}
                          className={`py-2 px-2 rounded-lg text-xs font-bold transition flex items-center justify-center gap-1 cursor-pointer disabled:opacity-40 disabled:cursor-not-allowed ${
                            editType === t.id
                              ? 'bg-zinc-900 text-white dark:bg-white dark:text-zinc-900 shadow-xs'
                              : 'bg-white dark:bg-zinc-800 text-zinc-600 dark:text-zinc-400 border border-zinc-200 dark:border-zinc-700 hover:bg-zinc-50'
                          }`}
                        >
                          <span>{t.icon}</span>
                          <span>{tx(t.label)}</span>
                        </button>
                      ))}
                    </div>
                    {(txn.paired_transfer || txn.deletion_info?.has_refund_links || txn.deletion_info?.linked_refund_count || txn.is_split) &&
                      <p className="text-xs text-zinc-500 dark:text-zinc-400">{tx('请先解除拆分或关联，再切换交易类型。')}</p>}
                  </div>

                  {/* 2. 交易名称与金额 */}
                  <div className="grid grid-cols-2 gap-3">
                    <div className="space-y-1">
                      <label className="text-[11px] font-semibold text-zinc-500 dark:text-zinc-400">{tx("账户实际结算金额 (")} {allAccounts.find(account => account.id === editAccountId)?.currency || txn.currency})</label>
                      <input
                        type="number"
                        step="0.01"
                        required
                        data-testid="edit-amount-input"
                        value={editAmount}
                        onChange={(e) => setEditAmount(e.target.value)}
                        placeholder="0.00"
                        className="w-full px-3 py-1.5 text-xs rounded-lg border border-zinc-300 dark:border-zinc-700 bg-white dark:bg-zinc-900 font-mono font-bold text-zinc-900 dark:text-white focus:outline-hidden focus:ring-1 focus:ring-blue-500"
                      />
                    </div>
                    <div className="space-y-1">
                      <label className="text-[11px] font-semibold text-zinc-500 dark:text-zinc-400">{tx("交易名称 / 商户")}</label>
                      <input
                        type="text"
                        required
                        data-testid="edit-name-input"
                        value={editName}
                        onChange={(e) => setEditName(e.target.value)}
                        placeholder={tx("如：星巴克咖啡")}
                        className="w-full px-3 py-1.5 text-xs rounded-lg border border-zinc-300 dark:border-zinc-700 bg-white dark:bg-zinc-900 text-zinc-900 dark:text-white focus:outline-hidden focus:ring-1 focus:ring-blue-500"
                      />
                    </div>
                  </div>

                  <div className="grid grid-cols-2 gap-3">
                    <label className="text-xs">{tx("已核实原币金额")} <input type="number" min="0.0001" step="0.0001" value={editOriginalAmount} onChange={e => setEditOriginalAmount(e.target.value)} className="w-full border rounded p-2 dark:bg-zinc-900" /></label>
                    <label className="text-xs">{tx("原币币种")} <select value={editOriginalCurrency} onChange={e => setEditOriginalCurrency(e.target.value)} className="w-full border rounded p-2 dark:bg-zinc-900"><option value="">{tx("尚未核实")}</option>{(currencies || []).map(c => <option key={c.code} value={c.code}>{c.code}</option>)}</select></label>
                  </div>
                  {(txn.master_account_id || allAccounts.find(a => a.id === editAccountId)?.parent_account_id) && <label className="block text-xs">{tx("主卡银行结算金额（")} {allAccounts.find(a => a.id === editAccountId)?.parent_account?.currency || txn.master_settlement_currency}）<input type="number" min="0.0001" step="0.0001" value={editMasterAmount} onChange={e => setEditMasterAmount(e.target.value)} className="w-full border rounded p-2 dark:bg-zinc-900" /></label>}
                  <p className="text-xs text-zinc-500">{tx("仅按银行账单或原始记录确认。已分配退款的流水请先解除关联再修改金额。")}</p>
                  {/* 3. 交易时间 (精确到秒) */}
                  <div className="space-y-1">
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <label className="text-[11px] font-semibold text-zinc-500 dark:text-zinc-400">{tx("交易时间 (日期与时分秒)")}</label>
                      <button
                        type="button"
                        onClick={() => {
                          const now = new Date();
                          setEditDate(toLocalISODate(now));
                          setEditTime(toLocalISOTime(now, true));
                        }}
                        className="text-[11px] text-blue-600 dark:text-blue-400 hover:underline flex items-center gap-0.5 cursor-pointer"
                      >
                        <Clock className="w-3 h-3" />
                        <span>{tx("设为此时此刻")}</span>
                      </button>
                    </div>
                    <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                      <input
                        type="date"
                        required
                        data-testid="edit-date-input"
                        value={editDate}
                        onChange={(e) => setEditDate(e.target.value)}
                        className="w-full min-w-0 max-w-full px-3 py-1.5 text-xs rounded-lg border border-zinc-300 dark:border-zinc-700 bg-white dark:bg-zinc-900 text-zinc-900 dark:text-white font-mono focus:outline-hidden focus:ring-1 focus:ring-blue-500"
                      />
                      <input
                        type="time"
                        step="1"
                        required
                        data-testid="edit-time-input"
                        value={editTime}
                        onChange={(e) => setEditTime(e.target.value)}
                        className="w-full min-w-0 max-w-full px-3 py-1.5 text-xs rounded-lg border border-zinc-300 dark:border-zinc-700 bg-white dark:bg-zinc-900 text-zinc-900 dark:text-white font-mono focus:outline-hidden focus:ring-1 focus:ring-blue-500"
                      />
                    </div>
                  </div>

                  {/* 4. 账户与分类选择 */}
                  {editType !== 'transfer' && <div className="grid grid-cols-2 gap-3">
                    <div className="space-y-1">
                      <label className="text-[11px] font-semibold text-zinc-500 dark:text-zinc-400">{tx('所属账户')}</label>
                      <select
                        data-testid="edit-account-select"
                        value={editAccountId}
                        onChange={(e) => setEditAccountId(e.target.value)}
                        className="w-full px-2.5 py-1.5 text-xs rounded-lg border border-zinc-300 dark:border-zinc-700 bg-white dark:bg-zinc-900 text-zinc-900 dark:text-white focus:outline-hidden focus:ring-1 focus:ring-blue-500"
                      >
                        {allAccounts.length > 0 ? (
                          allAccounts.map((a) => (
                            <option key={a.id} value={a.id} disabled={a.can_edit === false}>
                              {formatAccountWithEmoji(a)}
                            </option>
                          ))
                        ) : (
                          <option value={txn.account_id}>{txn.account_name}</option>
                        )}
                      </select>
                    </div>

                    <RefundCategoryField transaction={txn} categories={allCategories} value={editCategoryId}
                      transactionType={editType} onChange={value => { setEditCategoryId(value); setCategoryTouched(true); }} />
                  </div>}

                  {editType === 'transfer' && <TransferDestinationFields transaction={txn} accounts={allAccounts}
                    sourceAccountId={editTransferDirection === 'outflow' ? editAccountId : editPeerAccountId}
                    destinationId={editTransferDirection === 'outflow' ? editPeerAccountId : editAccountId}
                    direction={editTransferDirection} onDirectionChange={setEditTransferDirection}
                    onSourceChange={id => {
                      if (editTransferDirection === 'outflow') setEditAccountId(id);
                      else { setEditPeerAccountId(id); setEditPeerAmount(id === txn.paired_transfer?.counterpart.account_id ? txn.paired_transfer.counterpart.amount : ''); }
                    }}
                    onDestinationChange={id => {
                      if (editTransferDirection === 'inflow') setEditAccountId(id);
                      else { setEditPeerAccountId(id); setEditPeerAmount(id === txn.paired_transfer?.counterpart.account_id ? txn.paired_transfer.counterpart.amount : ''); }
                    }} peerAmount={editPeerAmount} onAmountChange={setEditPeerAmount} />}
                  {editType === 'refund' && renderRefundFields(true)}

                  {['expense', 'refund'].includes(editType) && <button type="button"
                    disabled={saving || linkingLoading} data-testid="edit-transaction-split-btn" onClick={async event => {
                      if (event.currentTarget.form?.reportValidity() === false) return;
                      const updated = await handleSaveEdit();
                      if (updated) {
                        if (updated.refund_info?.category_editable === false) {
                          setTimeout(() => refundSectionRef.current?.scrollIntoView({ block: 'start', behavior: 'smooth' }), 0);
                        } else setShowSplitModal(true);
                      }
                    }} className="px-3 py-2 rounded-lg border border-zinc-300 dark:border-zinc-700 text-xs font-semibold text-zinc-700 dark:text-zinc-300 disabled:opacity-50">
                    {tx(editType === 'refund' ? '保存并拆分退款' : '保存并拆分支出')}
                  </button>}

                  {/* 4.1 交易标签 (可多选) */}
                  <div className="space-y-1.5 p-3 rounded-xl bg-zinc-50/80 dark:bg-zinc-800/40 border border-zinc-200/80 dark:border-zinc-700/60">
                    <div className="flex items-center justify-between">
                      <label className="text-[11px] font-bold text-zinc-700 dark:text-zinc-300 flex items-center gap-1">
                        <Tag className="w-3.5 h-3.5 text-zinc-400" />
                        <span>{tx("交易标签 (多选)")}</span>
                      </label>
                      <span className="text-[11px] text-zinc-400">{tx("已选")} {editTags.length} {tx("个")}</span>
                    </div>

                    {/* 已选标签列表 */}
                    <div className="flex flex-wrap gap-1.5 items-center min-h-[28px]">
                      {editTags.map((tg) => (
                        <span
                          key={tg}
                          className="inline-flex items-center gap-1 px-2 py-0.5 rounded-md text-[11px] font-semibold bg-zinc-200 dark:bg-zinc-700 text-zinc-800 dark:text-zinc-200 shadow-2xs"
                        >
                          <span>#{tg}</span>
                          <button
                            type="button"
                            onClick={() => setEditTags(editTags.filter((t) => t !== tg))}
                            className="text-zinc-400 hover:text-zinc-700 dark:hover:text-white cursor-pointer ml-0.5"
                          >
                            ✕
                          </button>
                        </span>
                      ))}

                      {/* 输入新标签 */}
                      <input
                        type="text"
                        data-testid="edit-tag-input"
                        value={tagInput}
                        onChange={(e) => setTagInput(e.target.value)}
                        onKeyDown={(e) => {
                          if (e.key === 'Enter') {
                            e.preventDefault();
                            const val = tagInput.trim();
                            if (val) {
                              setEditTags((prev) => (prev.includes(val) ? prev : [...prev, val]));
                              setTagInput('');
                            }
                          }
                        }}
                        placeholder={tx("+ 输入回车添加")}
                        className="text-[11px] px-2 py-1 w-28 bg-white dark:bg-zinc-900 border border-zinc-200 dark:border-zinc-700 rounded-md outline-none text-zinc-800 dark:text-zinc-200 placeholder:text-zinc-400 focus:ring-1 focus:ring-blue-500"
                      />
                    </div>

                    {/* 可选系统已有标签快捷点击 */}
                    {availableTags.filter((t) => !editTags.includes(t.name)).length > 0 && (
                      <div className="pt-2 border-t border-zinc-200/50 dark:border-zinc-700/50 flex flex-wrap gap-1 items-center">
                        <span className="text-[11px] text-zinc-400">{tx("快捷选取:")}</span>
                        {availableTags
                          .filter((t) => !editTags.includes(t.name))
                          .slice(0, 10)
                          .map((t) => (
                            <button
                              key={t.id || t.name}
                              type="button"
                              onClick={() => setEditTags((prev) => (prev.includes(t.name) ? prev : [...prev, t.name]))}
                              className="px-1.5 py-0.5 rounded text-[11px] bg-white dark:bg-zinc-800 border border-zinc-200 dark:border-zinc-700 text-zinc-600 dark:text-zinc-300 hover:border-zinc-400 cursor-pointer"
                            >
                              +{t.name}
                            </button>
                          ))}
                      </div>
                    )}
                  </div>

                  {/* 4.5 报销与代垫设置 (编辑模式) */}
                  {['expense', 'income'].includes(editType) && <div className="p-3 rounded-xl border border-blue-200/90 dark:border-blue-900/90 bg-white/80 dark:bg-zinc-900/80 space-y-2.5 shadow-2xs">
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <label className="text-[11px] font-bold text-zinc-800 dark:text-zinc-200 flex items-center gap-1.5 cursor-pointer select-none">
                        <input
                          type="checkbox"
                          data-testid="edit-reimb-checkbox"
                          checked={editIsReimbursable}
                          onChange={(e) => { setEditIsReimbursable(e.target.checked); setEditExcludedFromStats(e.target.checked); }}
                          className="rounded border-zinc-300 text-blue-600 focus:ring-blue-500 cursor-pointer"
                        />
                        <span>{tx("标记为公费报销 / 朋友代垫款")}</span>
                      </label>
                      <span className="text-[11px] text-zinc-400 font-mono">
                        {editExcludedFromStats ? tx("🚫 不计入家庭支出") : tx("计入家庭净支出")}
                      </span>
                    </div>

                    {editIsReimbursable && (
                      <div className="space-y-2.5 pt-2 border-t border-zinc-100 dark:border-zinc-800 animate-in fade-in duration-100">
                        {/* 报销类型选择 */}
                        <div className="space-y-1">
                          <label className="text-[11px] font-semibold text-zinc-500 dark:text-zinc-400">{tx("报销性质")}</label>
                          <div className="grid grid-cols-2 gap-1.5">
                            <button
                              type="button"
                              data-testid="edit-reimb-type-corporate"
                              onClick={() => {
                                setEditReimbType('corporate');
                                if (!editCounterparty || editCounterparty === '张三') setEditCounterparty('公司');
                                setEditReimbStatus('审批中');
                              }}
                              className={`py-1.5 px-2 rounded-lg text-xs font-semibold flex items-center justify-center gap-1 border transition cursor-pointer ${
                                editReimbType === 'corporate'
                                  ? 'bg-blue-50 border-blue-500 text-blue-700 dark:bg-blue-950/40 dark:text-blue-300 font-bold'
                                  : 'bg-white dark:bg-zinc-800 border-zinc-200 dark:border-zinc-700 text-zinc-600 dark:text-zinc-400 hover:bg-zinc-50'
                              }`}
                            >
                              <span>🏢</span>
                              <span>{tx("公司公费报销")}</span>
                            </button>
                            <button
                              type="button"
                              data-testid="edit-reimb-type-personal"
                              onClick={() => {
                                setEditReimbType('personal_advance');
                                if (!editCounterparty || editCounterparty === '公司') setEditCounterparty('张三');
                                setEditReimbStatus('待还款');
                              }}
                              className={`py-1.5 px-2 rounded-lg text-xs font-semibold flex items-center justify-center gap-1 border transition cursor-pointer ${
                                editReimbType === 'personal_advance'
                                  ? 'bg-amber-50 border-amber-500 text-amber-700 dark:bg-amber-950/40 dark:text-amber-300 font-bold'
                                  : 'bg-white dark:bg-zinc-800 border-zinc-200 dark:border-zinc-700 text-zinc-600 dark:text-zinc-400 hover:bg-zinc-50'
                              }`}
                            >
                              <span>👤</span>
                              <span>{tx("朋友代垫借款")}</span>
                            </button>
                          </div>
                        </div>

                        {/* 往来对象输入框 (解决用户找不到“张三”可编辑的地方) */}
                        <div className="space-y-1">
                          <label className="text-[11px] font-semibold text-zinc-500 dark:text-zinc-400">
                            {editReimbType === 'corporate' ? tx("报销单位 / 公司部门") : tx("欠款人 / 往来对象姓名 (如：张三、李四)")}
                          </label>
                          <input
                            type="text"
                            data-testid="edit-reimb-counterparty-input"
                            value={editCounterparty}
                            onChange={(e) => setEditCounterparty(e.target.value)}
                            placeholder={editReimbType === 'corporate' ? tx("如：公司财务部") : tx("如：张三、李四")}
                            className="w-full px-2.5 py-1.5 text-xs rounded-lg border border-zinc-300 dark:border-zinc-700 bg-white dark:bg-zinc-900 text-zinc-900 dark:text-white focus:outline-hidden focus:ring-1 focus:ring-blue-500 font-medium"
                          />
                        </div>

                        {/* 处理流转状态选择 */}
                        <div className="space-y-1">
                          <label className="text-[11px] font-semibold text-zinc-500 dark:text-zinc-400">{tx("处理进度与状态")}</label>
                          <div className="grid grid-cols-3 gap-1">
                            {(editReimbType === 'personal_advance'
                              ? ["待还款", "部分已还", "已结清"]
                              : ["未提报", "审批中", "已打款"]
                            ).map((st) => (
                              <button
                                key={st}
                                type="button"
                                data-testid={`edit-reimb-status-${st}`}
                                onClick={() => setEditReimbStatus(st)}
                                className={`py-1 text-xs rounded-md font-medium transition cursor-pointer ${
                                  editReimbStatus === st
                                    ? 'bg-zinc-900 text-white dark:bg-white dark:text-zinc-900 font-bold'
                                    : 'bg-zinc-100 dark:bg-zinc-800 text-zinc-600 dark:text-zinc-400 hover:bg-zinc-200'
                                }`}
                              >
                                {tx(st)}
                              </button>
                            ))}
                          </div>
                        </div>
                      </div>
                    )}
                  </div>}

                  {/* 5. 备注 */}
                  {editType !== 'transfer' && <label className="flex items-center gap-2 text-xs text-zinc-600 dark:text-zinc-300">
                    <input type="checkbox" data-testid="edit-excluded-from-stats" checked={editExcludedFromStats}
                      onChange={event => setEditExcludedFromStats(event.target.checked)} className="rounded accent-blue-600" />
                    {tx('不计入收支统计')}
                  </label>}
                  <div className="space-y-1">
                    <label className="text-[11px] font-semibold text-zinc-500 dark:text-zinc-400">{tx("备注说明")}</label>
                    <textarea
                      rows={2}
                      data-testid="edit-notes-input"
                      value={editNotes}
                      onChange={(e) => setEditNotes(e.target.value)}
                      placeholder={tx("输入交易备注信息...")}
                      className="w-full px-3 py-1.5 text-xs rounded-lg border border-zinc-300 dark:border-zinc-700 bg-white dark:bg-zinc-900 text-zinc-900 dark:text-white focus:outline-hidden focus:ring-1 focus:ring-blue-500 resize-none"
                    />
                  </div>

                  {/* 6. 保存与取消按钮 */}
                  <div className="pt-2 flex items-center justify-end gap-2 border-t border-blue-200/60 dark:border-blue-900/60">
                    <button
                      type="button"
                      onClick={() => setIsEditing(false)}
                      className="px-3 py-1.5 rounded-lg border border-zinc-300 dark:border-zinc-700 text-zinc-700 dark:text-zinc-300 text-xs font-semibold hover:bg-zinc-100 dark:hover:bg-zinc-800 transition cursor-pointer"
                    >{tx("取消")}</button>
                    <button
                      type="submit"
                      data-testid="save-transaction-edit-btn"
                      disabled={saving}
                      className="px-4 py-1.5 bg-blue-600 hover:bg-blue-700 text-white rounded-lg text-xs font-bold transition flex items-center gap-1.5 shadow-xs cursor-pointer"
                    >
                      <Save className="w-3.5 h-3.5" />
                      <span>{saving ? tx("正在保存...") : tx("保存修改")}</span>
                    </button>
                  </div>
                </form>
              )}

              <BookingMoneyInfo transaction={txn} detailed privacy={privacyMode} />
              {/* 1. Compact Hero & Key Info Bar (紧凑单卡片两行高密度，突出退款冲抵与核心信息) */}
              <div className="bg-zinc-50 dark:bg-zinc-800/50 rounded-xl p-3.5 border border-zinc-200/80 dark:border-zinc-800 space-y-2">
                {/* Row 1: 金额 + 类型徽章 */}
                <div className="flex items-center gap-2.5">
                    <span className="text-2xl font-extrabold font-mono tracking-tight text-zinc-900 dark:text-white">
                      <TransactionAmount transaction={txn} detailed privacy={privacyMode} />
                    </span>
                    <span
                      className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-semibold ${
                        txn.transaction_type === 'refund'
                          ? 'bg-emerald-50 dark:bg-emerald-950/40 text-emerald-600 dark:text-emerald-400 border border-emerald-200 dark:border-emerald-800'
                          : txn.transaction_type === 'transfer'
                          ? 'bg-blue-50 dark:bg-blue-950/40 text-blue-600 dark:text-blue-400 border border-blue-200 dark:border-blue-800'
                          : txn.transaction_type === 'income'
                          ? 'bg-emerald-50 dark:bg-emerald-950/40 text-emerald-600 dark:text-emerald-400 border border-emerald-200 dark:border-emerald-800'
                          : txn.transaction_type === 'adjustment'
                          ? 'bg-purple-50 dark:bg-purple-950/40 text-purple-600 dark:text-purple-400 border border-purple-200 dark:border-purple-800'
                          : 'bg-zinc-100 dark:bg-zinc-800 text-zinc-700 dark:text-zinc-300'
                      }`}
                    >
                      {txn.transaction_type === 'refund' && <RotateCcw className="w-3 h-3" />}
                      {txn.transaction_type === 'transfer' && <ArrowRightLeft className="w-3 h-3" />}
                      {txn.transaction_type === 'adjustment' && <SlidersHorizontal className="w-3 h-3" />}
                      {txn.transaction_type === 'refund'
                        ? tx("退款冲抵")
                        : txn.transaction_type === 'transfer'
                        ? tx("转账互转")
                        : txn.transaction_type === 'income'
                        ? tx("日常收入")
                        : txn.transaction_type === 'adjustment'
                        ? tx("余额对账")
                        : tx("日常支出")}
                    </span>
                  </div>

                {/* Row 2: 商户/名称 + 账户 + 分类 (转账模式下精简展示，避免与下方路径重复) */}
                <div className="flex items-center justify-between gap-2 text-xs text-zinc-600 dark:text-zinc-400 pt-1.5 border-t border-zinc-200/60 dark:border-zinc-800/60">
                  <div className="font-semibold text-zinc-900 dark:text-zinc-100 truncate pr-2">
                    {txn.narration || (txn.transaction_type === 'transfer' ? tx("内部转账") : tx("未命名交易"))}
                  </div>
                  {txn.transaction_type !== 'transfer' && (
                    <div className="flex items-center gap-1.5 shrink-0 text-zinc-500 dark:text-zinc-400">
                      <span>{txn.category_icon || '📦'}</span>
                      <span>{displayedCategoryName || tx("未分类")}</span>
                    </div>
                  )}
                </div>
              </div>

              {!refundCategoryLocked && txn.extra?.classification && <p className="text-xs text-zinc-500" data-testid="classification-rule">
                {txn.extra.classification.reason === 'no_match' ? tx('未命中分类规则，归入其他') : `${tx('分类规则')}: #${txn.extra.classification.priority} ${txn.extra.classification.rule_name}`}
              </p>}

              {/* 1.2 交易核心明细卡片 (精确日期与时分秒、账户、分类、入账时间) */}
              {txn.extra?.scheduled_occurrence_id && <div data-testid="drawer-plan-link" className="rounded-xl border border-zinc-200 dark:border-zinc-800 p-3 space-y-1 text-xs">
                <strong>{tx('计划关联流水')}</strong>
                <p>{tx({principal:'本金',receipt:'本金',transfer:'内部转账',interest:'利息',fee:'手续费',deferred_interest:'延期利息',deferred_interest_paid:'延期利息',capitalized_interest:'计入本金的利息'}[txn.extra.component] || '计划')}</p>
                {txn.scheduled_payment?.kind === 'loan' && <div className="flex flex-wrap gap-x-3 gap-y-1 font-mono">
                  {['principal','interest','fee'].map((key,index)=><span key={key}>{tx(['本金','利息','手续费'][index])} {privacyMode ? '••••••' : `${txn.scheduled_payment[key]} ${txn.scheduled_payment.currency}`}</span>)}
                </div>}
                <p className="text-zinc-500">{tx('修改或撤销请进入对应计划。')}</p>
              </div>}
              <div className="bg-zinc-50/80 dark:bg-zinc-800/40 rounded-xl p-4 border border-zinc-200/80 dark:border-zinc-800 space-y-3 text-xs">
                <div className="text-xs font-bold text-zinc-900 dark:text-white pb-2 border-b border-zinc-200/60 dark:border-zinc-800/60 flex items-center justify-between">
                  <span>{tx("交易核心明细")}</span>
                </div>
                <div className="grid grid-cols-2 gap-y-3 gap-x-4">
                  <div className="col-span-2 min-w-0" data-testid="drawer-transaction-date">
                    <span className="text-zinc-400 block text-[11px] mb-0.5">{tx("交易时间 (日期与时分秒)")}</span>
                    <span className="font-mono font-semibold text-zinc-900 dark:text-zinc-100 flex items-start gap-1.5">
                      <Clock className="w-3.5 h-3.5 text-zinc-500 shrink-0" />
                      <span className="min-w-0 break-words">{formatDateTime(txn.occurred_at || txn.transacted_at)}</span>
                    </span>
                  </div>
                  <div>
                    <span className="text-zinc-400 block text-[11px] mb-0.5">
                      {txn.transaction_type === 'transfer' ? (transferOutflow ? tx("转出账户 (本端)") : tx("转入账户 (本端)")) : tx("所属账户")}
                    </span>
                    <div className="flex items-center gap-1.5 flex-wrap min-w-0">
                      <span className="font-medium text-zinc-900 dark:text-zinc-100 flex items-center gap-1.5 truncate">
                        <Building2 className="w-3.5 h-3.5 text-zinc-500 shrink-0" />
                        <span className="truncate">{txn.account_name}</span>
                      </span>
                      {txn.account_owner_name && !txn.account_is_owner && (
                        <span
                          title={tx("由 {p0} 共享", {p0: (txn.account_owner_name)})}
                          className="inline-flex items-center gap-1 px-1.5 py-0.2 rounded text-[11px] font-medium shrink-0 bg-purple-50 dark:bg-purple-950/60 text-purple-600 dark:text-purple-300 border border-purple-200 dark:border-purple-800"
                        >
                          <Users className="w-2.5 h-2.5" />
                          <span>{tx("{p0} 共享", {p0: (txn.account_owner_name)})}</span>
                        </span>
                      )}
                    </div>
                  </div>
                  {txn.transaction_type === 'transfer' && (
                    <div>
                      <span className="text-zinc-400 block text-[11px] mb-0.5">
                        {transferOutflow ? tx("转入账户 (对端)") : tx("转出账户 (对端)")}
                      </span>
                      <div className="flex items-center gap-1.5 flex-wrap min-w-0">
                        <span className="font-semibold text-blue-600 dark:text-blue-400 flex items-center gap-1.5 truncate">
                          <Building2 className="w-3.5 h-3.5 text-blue-500 shrink-0" />
                          <span className="truncate">{txn.paired_transfer?.counterpart?.account_name || tx("外部银行账户")}</span>
                        </span>
                        {txn.paired_transfer?.counterpart?.owner_name && !txn.paired_transfer.counterpart.is_owner && (
                          <span
                            data-testid="drawer-counterpart-owner-badge"
                            title={tx("由 {p0} 共享", {p0: (txn.paired_transfer.counterpart.owner_name)})}
                            className="inline-flex items-center gap-1 px-1.5 py-0.2 rounded text-[11px] font-medium shrink-0 bg-purple-50 dark:bg-purple-950/60 text-purple-600 dark:text-purple-300 border border-purple-200 dark:border-purple-800"
                          >
                            <Users className="w-2.5 h-2.5" />
                            <span>{tx("{p0} 共享", {p0: (txn.paired_transfer.counterpart.owner_name)})}</span>
                          </span>
                        )}
                      </div>
                    </div>
                  )}
                  {txn.transaction_type === 'transfer' ? (
                    <div>
                      <span className="text-zinc-400 block text-[11px] mb-0.5">{tx("记账属性")}</span>
                      <span className="font-medium text-purple-600 dark:text-purple-400 flex items-center gap-1.5">
                        <span>⇄</span>
                        <span>{tx("内部转账互转 (不计家庭收支)")}</span>
                      </span>
                    </div>
                  ) : (
                    <>
                      <div>
                        <span className="text-zinc-400 block text-[11px] mb-0.5">{tx(refundCategoryLocked ? '退款分类（随原消费）' : txn.transaction_type === 'refund' && txn.refund_info?.is_linked ? '未关联部分的分类' : '交易分类')}</span>
                        <span className="font-medium text-zinc-900 dark:text-zinc-100 flex items-center gap-1.5">
                          <span>{txn.category_icon || '📦'}</span>
                          <span>{displayedCategoryName || tx("未分类")}</span>
                        </span>
                        {txn.transaction_type === 'refund' && txn.refund_info?.is_linked && <p className="text-[11px] text-zinc-500 mt-1">
                          {!refundCategoryLocked && <span className="block">{tx('已关联部分分类')}: {txn.refund_info.linked_categories?.map(c => categoryLabel(c.name)).join(' / ') || tx('随原消费分类')}</span>}
                          {tx('已关联退款随原消费分类；修改分类请编辑原消费。')}
                        </p>}
                      </div>
                      <div>
                        <span className="text-zinc-400 block text-[11px] mb-0.5">{tx("记账类型")}</span>
                        <span className="font-medium text-zinc-900 dark:text-zinc-100">
                          {txn.transaction_type === 'refund'
                            ? tx("退款冲抵")
                            : txn.transaction_type === 'income'
                            ? tx("收入存入")
                            : tx("消费支出")}
                        </span>
                      </div>
                    </>
                  )}

                  <div className="col-span-2 pt-2 border-t border-zinc-200/50 dark:border-zinc-800/40">
                    <dl className="space-y-1 text-[11px] mb-3">
                      <div><dt className="text-zinc-400">{tx("交易 ID")}</dt><dd className="font-mono break-all select-text" data-testid="transaction-id">{txn.id}</dd></div>
                      <div><dt className="text-zinc-400">{tx("来源流水号（external_id）")}</dt><dd className="font-mono break-all select-text" data-testid="transaction-external-id">{txn.external_id || tx("未提供")}</dd></div>
                    </dl>
                    <span className="text-zinc-400 block text-[11px] mb-1.5 flex items-center gap-1">
                      <Tag className="w-3 h-3 text-zinc-400" />
                      <span>{tx("交易标签 (Tags)")}</span>
                    </span>
                    {txn.tags && txn.tags.length > 0 ? (
                      <div className="flex flex-wrap gap-1.5" data-testid="drawer-tags-list">
                        {txn.tags.map((tg) => (
                          <span
                            key={tg}
                            className="inline-flex items-center px-2 py-0.5 rounded-md text-[11px] font-semibold bg-zinc-100 dark:bg-zinc-800 text-zinc-700 dark:text-zinc-300 border border-zinc-200/80 dark:border-zinc-700/80 shadow-2xs"
                          >
                            #{tg}
                          </span>
                        ))}
                      </div>
                    ) : (
                      <span className="text-[11px] text-zinc-400 italic">{tx("暂无标签")}</span>
                    )}
                  </div>

                </div>
              </div>

              {/* 1.4 拆分账单 / 拆分退款 (Transaction Split) */}
              {!isEditing && (txn.transaction_type === 'expense' || txn.transaction_type === 'refund') && (
                <div className="p-4 rounded-xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-800/50 space-y-3 shadow-xs">
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-2">
                      <div className="w-6 h-6 rounded-md bg-purple-50 dark:bg-purple-950/60 text-purple-600 dark:text-purple-400 flex items-center justify-center">
                        <Scissors className="w-3.5 h-3.5" />
                      </div>
                      <span className="text-xs font-bold text-zinc-900 dark:text-white">
                        {txn.transaction_type === 'refund' ? tx("拆分退款 (Split Refund)") : tx("拆分账单 (Split)")}
                      </span>
                      {txn.is_split && (
                        <span className="px-1.5 py-0.2 rounded text-[10px] font-semibold bg-purple-100 dark:bg-purple-900/60 text-purple-700 dark:text-purple-300">{tx("已拆为")} {txn.splits?.length || 2} {tx("项")}</span>
                      )}
                    </div>
                    <button
                      type="button"
                      disabled={!!txn?.extra?.scheduled_occurrence_id || txn.deletion_info?.can_edit === false}
                      data-testid="drawer-split-btn"
                      onClick={() => refundCategoryLocked
                        ? refundSectionRef.current?.scrollIntoView({ block: 'start', behavior: 'smooth' })
                        : setShowSplitModal(true)}
                      className="px-2.5 py-1 rounded-lg border border-zinc-200 dark:border-zinc-700 text-xs font-semibold text-zinc-700 dark:text-zinc-200 hover:bg-zinc-50 dark:hover:bg-zinc-700/60 transition cursor-pointer"
                    >
                      {refundCategoryLocked ? tx('调整退款分配') : txn.is_split ? tx("调整拆分") : txn.transaction_type === 'refund' ? tx("✂️ 拆分此退款") : tx("✂️ 拆分此账单")}
                    </button>
                  </div>

                  {refundCategoryLocked ? <div className="space-y-2 text-xs text-zinc-500 dark:text-zinc-400">
                    <p>{tx('退款已全部关联原消费，分类按原消费拆分；调整分配请先解除关联。')}</p>
                    <p>{txn.refund_info.linked_categories?.map(category => `${category.icon || '📦'} ${categoryLabel(category.name)}`).join(' / ')}</p>
                  </div> : txn.is_split && txn.splits && txn.splits.length > 0 ? (
                    <div className="space-y-1.5 pt-2 border-t border-zinc-100 dark:border-zinc-800/60">
                      {txn.splits.map((sp, idx) => {
                        const cat = allCategories.find(
                          (c) => String(c.id) === String(sp.category_id)
                        );
                        const totalAmt = Math.abs(parseFloat(txn.amount));
                        const pct = totalAmt > 0
                          ? Math.round((parseFloat(sp.amount) / totalAmt) * 100)
                          : 0;
                        return (
                          <div
                            key={sp.id || idx}
                            className="flex items-center justify-between p-2 rounded-lg bg-zinc-50 dark:bg-zinc-900/60 border border-zinc-150 dark:border-zinc-800 text-xs"
                          >
                            <div className="flex items-center gap-2 min-w-0 pr-2">
                              <span className="text-sm shrink-0">{cat?.icon || '📦'}</span>
                              <div className="min-w-0">
                                <div className="font-semibold text-zinc-800 dark:text-zinc-200 truncate">
                                  {categoryLabel(cat?.name) || tx("默认分类")}
                                </div>
                                {sp.notes && (
                                  <div className="text-[11px] text-zinc-400 truncate">{sp.notes}</div>
                                )}
                              </div>
                            </div>
                            <div className="text-right shrink-0">
                              <span className="font-mono font-bold text-zinc-900 dark:text-zinc-100">
                                {privacyMode ? '••••••' : sp.display_amount == null ? tx("待换算 {p0}", {p0: (sp.display_currency)}) : `${formatCurrency(sp.display_amount, currencySymbol(sp.display_currency))} ${sp.display_currency}`}
                              </span>
                              <span className="text-[10.5px] text-zinc-400 block font-mono">
                                {pct}%
                              </span>
                            </div>
                          </div>
                        );
                      })}
                    </div>
                  ) : (
                    <p className="text-[11px] text-zinc-400">{tx("若一笔账单包含多种消费品类（如超市购物包含食品与日用百货），可将其拆分为多个子项分别归类统计。")}</p>
                  )}
                </div>
              )}

              {/* 1.5 REIMBURSEMENT SECTION (仅消费支出或代垫收入展示，转账不属于报销范畴) */}
              {!isEditing && ['expense', 'income'].includes(txn.transaction_type) && (() => {
                const reimbSummary = getReimbursementSummary(txn);
                const isReimb = reimbSummary.isReimbursable;
                const isCorp = reimbSummary.isCorporate;
                const currentCp = reimbSummary.counterparty;
                const currentSt = reimbSummary.status;

                return (
                  <div className="p-4 rounded-xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-800/50 space-y-3.5 shadow-xs">
                    <div data-testid="drawer-reimbursement-header" className="flex flex-col items-start gap-2 sm:flex-row sm:items-center sm:justify-between">
                      <div className="flex items-center gap-2 min-w-0">
                        <span className="text-base shrink-0">{isCorp ? '🏢' : '👤'}</span>
                        <span className="text-xs font-bold text-zinc-900 dark:text-white min-w-0 break-words">{tx("公费报销 / 朋友代垫 (Reimbursement)")}</span>
                      </div>
                      {/* 开启/关闭报销属性 开关 */}
                      <button
                        type="button"
                        data-testid="drawer-reimb-toggle-btn"
                        disabled={reimbLoading}
                        onClick={() => {
                          const nextReimb = !isReimb;
                          handleUpdateReimbursement({
                            is_reimbursable: nextReimb,
                            reimbursement_type: nextReimb ? (txn.extra?.reimbursement_type || 'corporate') : null,
                            reimbursement_status: nextReimb ? (txn.reimbursement_status || '审批中') : null,
                            counterparty: nextReimb ? currentCp : null,
                          });
                        }}
                        className={`max-w-full px-2.5 py-1 rounded-full text-xs font-semibold flex items-center gap-1.5 transition-all cursor-pointer ${
                          isReimb
                            ? 'bg-zinc-900 text-white dark:bg-white dark:text-zinc-900'
                            : 'bg-zinc-100 text-zinc-600 dark:bg-zinc-800 dark:text-zinc-400 hover:bg-zinc-200'
                        }`}
                      >
                        <span>{isReimb ? tx("已设为报销/代垫") : tx("未设报销")}</span>
                      </button>
                    </div>

                    {isReimb ? (
                      <div className="space-y-3 pt-1 border-t border-zinc-100 dark:border-zinc-800 text-xs">
                        {/* 往来对象展示与修改入口 (解决“张三”看不到可编辑的地方) */}
                        <div className="flex items-center justify-between p-2.5 rounded-lg bg-zinc-50 dark:bg-zinc-800/80 border border-zinc-200/70 dark:border-zinc-700/70">
                          <div className="flex items-center gap-2">
                            <span className="text-zinc-400 font-medium">
                              {isCorp ? tx("报销单位:") : tx("往来对象:")}
                            </span>
                            <span
                              data-testid="drawer-reimb-counterparty-display"
                              className="font-bold text-zinc-900 dark:text-zinc-100"
                            >
                              {currentCp}
                            </span>
                          </div>
                          <button
                            type="button"
                            onClick={handleStartEditing}
                            className="text-xs text-blue-600 dark:text-blue-400 font-semibold hover:underline flex items-center gap-1 cursor-pointer"
                          >
                            <Edit3 className="w-3 h-3" />
                            <span>{tx("修改姓名")}</span>
                          </button>
                        </div>

                        {/* 报销类型选择 */}
                        <div className="space-y-1">
                          <label className="text-[11px] font-semibold text-zinc-400">{tx("报销性质")}</label>
                          <div className="grid grid-cols-2 gap-2">
                            <button
                              type="button"
                              disabled={reimbLoading}
                              onClick={() => handleUpdateReimbursement({
                                is_reimbursable: true,
                                reimbursement_type: 'corporate',
                                reimbursement_status: '审批中',
                                counterparty: currentCp === '张三' ? '公司' : currentCp,
                              })}
                              className={`p-2 rounded-lg border text-left flex items-center gap-2 transition cursor-pointer ${
                                isCorp
                                  ? 'border-blue-500 bg-blue-50/50 dark:bg-blue-950/30 text-blue-700 dark:text-blue-300 font-semibold'
                                  : 'border-zinc-200 dark:border-zinc-700 text-zinc-600 dark:text-zinc-400 hover:bg-zinc-50'
                              }`}
                            >
                              <span className="text-sm">🏢</span>
                              <div>
                                <p className="font-semibold">{tx("公司公费差旅")}</p>
                                <p className="text-[11px] text-zinc-400 font-normal">{tx("待报销·")} {isCorp ? currentCp : tx("公司")}</p>
                              </div>
                            </button>

                            <button
                              type="button"
                              disabled={reimbLoading}
                              onClick={() => handleUpdateReimbursement({
                                is_reimbursable: true,
                                reimbursement_type: 'personal_advance',
                                reimbursement_status: '待还款',
                                counterparty: currentCp === '公司' ? '张三' : currentCp,
                              })}
                              className={`p-2 rounded-lg border text-left flex items-center gap-2 transition cursor-pointer ${
                                !isCorp
                                  ? 'border-amber-500 bg-amber-50/50 dark:bg-amber-950/30 text-amber-700 dark:text-amber-300 font-semibold'
                                  : 'border-zinc-200 dark:border-zinc-700 text-zinc-600 dark:text-zinc-400 hover:bg-zinc-50'
                              }`}
                            >
                              <span className="text-sm">👤</span>
                              <div>
                                <p className="font-semibold">{tx("朋友AA垫付借款")}</p>
                                <p className="text-[11px] text-zinc-400 font-normal">{tx("待收回·")} {!isCorp ? currentCp : tx("朋友")}</p>
                              </div>
                            </button>
                          </div>
                        </div>

                        {/* 流转状态选择 */}
                        <div className="space-y-1">
                          <label className="text-[11px] font-semibold text-zinc-400">{tx("处理进度与状态")}</label>
                          <div className="grid grid-cols-3 gap-1.5">
                            {(!isCorp
                              ? ["待还款", "部分已还", "已结清"]
                              : ["未提报", "审批中", "已打款"]
                            ).map((st) => {
                              const isCur = currentSt === st;
                              return (
                                <button
                                  key={st}
                                  type="button"
                                  disabled={reimbLoading}
                                  onClick={() => handleUpdateReimbursement({ reimbursement_status: st })}
                                  className={`py-1.5 px-2 rounded-lg font-medium text-center transition flex items-center justify-center gap-1 cursor-pointer ${
                                    isCur
                                      ? 'bg-zinc-900 text-white dark:bg-white dark:text-zinc-900 font-bold shadow-xs'
                                      : 'bg-zinc-100 dark:bg-zinc-800 text-zinc-600 dark:text-zinc-400 hover:bg-zinc-200'
                                  }`}
                                >
                                  <span>{tx(st)}</span>
                                  {isCur && <Check className="w-3 h-3 text-emerald-400" />}
                                </button>
                              );
                            })}
                          </div>
                        </div>

                        {/* 排除在支出统计之外开关 */}
                        <div className="pt-2 border-t border-zinc-100 dark:border-zinc-800 flex items-center justify-between">
                          <span className="flex items-center gap-1.5 text-zinc-600 dark:text-zinc-400">
                            <Ban className="w-3.5 h-3.5 text-zinc-400" />
                            <span>{tx("不计入家庭支出统计 (垫付/报销不计消费)")}</span>
                          </span>
                          <button
                            type="button"
                            disabled={reimbLoading}
                            onClick={() => handleUpdateReimbursement({ excluded_from_stats: !txn.excluded_from_stats })}
                            className={`w-4 h-4 rounded border flex items-center justify-center text-[11px] transition cursor-pointer ${
                              txn.excluded_from_stats
                                ? 'bg-zinc-900 text-white border-zinc-900 dark:bg-white dark:text-zinc-900'
                                : 'border-zinc-300 dark:border-zinc-600'
                            }`}
                          >
                            {txn.excluded_from_stats && <Check className="w-3 h-3" />}
                          </button>
                        </div>
                      </div>
                    ) : (
                      <p className="text-xs text-zinc-400 leading-relaxed">{tx("可将此笔支出标记为公费差旅报销或朋友借款代垫。标记后可在流水列表直接查看流转徽章并一键切换进度。")}</p>
                    )}
                  </div>
                );
              })()}

              {/* Refund allocation stays operable without entering the generic editor. */}
              {!isEditing && txn.transaction_type === 'refund' && <section ref={refundSectionRef}>
                {txn.extra?.refund_match && <p className="mb-2 text-xs text-zinc-500 dark:text-zinc-400">
                  {tx('自动匹配评分')}: {Number(txn.extra.refund_match.score).toFixed(3)} · {tx(txn.extra.refund_match.status === 'matched' ? '已自动关联' : '保留待确认')}
                </p>}
                {txn.refund_info?.needs_allocation_review && <p className="mb-2 text-xs text-amber-700 dark:text-amber-400">{tx('历史关联缺少已核实的金额，请重新核对关联。')}</p>}
                {renderRefundFields(false)}
              </section>}

              {/* If Expense has been refunded */}
              {txn.transaction_type === 'expense' && txn.refund_info?.has_refunds && (
                <div className="p-4 rounded-xl border border-emerald-200 dark:border-emerald-800 bg-emerald-50/30 dark:bg-emerald-950/20 space-y-2">
                  <div className="flex items-center justify-between text-xs font-bold text-emerald-800 dark:text-emerald-300">
                    <span className="flex items-center gap-1.5">
                      <CheckCircle2 className="w-4 h-4 text-emerald-600" /> {tx("此笔消费已发生退款冲抵")}</span>
                    <span className="font-mono">{tx("已抵消")} {txn.refund_info.total_refunded} {txn.refund_info.currency}</span>
                  </div>
                  <div className="space-y-1">
                    {txn.refund_info.refunds.map((r) => (
                      <div key={r.id} className="text-xs text-zinc-600 dark:text-zinc-400 flex justify-between">
                        <span>{r.narration} ({formatDateTime(r.occurred_at || r.transacted_at)})</span>
                        <span className="font-mono text-emerald-600 dark:text-emerald-400">{r.allocated_amount} {txn.refund_info.currency}</span>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* 4. TRANSFER SECTION (内部转账与配对管理) */}
              {!isEditing && txn.transaction_type === 'transfer' && <div className="p-4 rounded-xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-800/50 space-y-3">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <ArrowRightLeft className="w-4 h-4 text-blue-600 dark:text-blue-400" />
                    <span className="text-xs font-bold text-zinc-900 dark:text-white">{tx("转账配对管理")}</span>
                  </div>
                  {txn.paired_transfer ? (
                    <span className="px-2 py-0.5 rounded text-[11px] font-semibold bg-emerald-50 text-emerald-700 dark:bg-emerald-950/50 dark:text-emerald-300 border border-emerald-200/80 dark:border-emerald-800/80">{tx("✓ 已双向配对 (互抵不计收支)")}</span>
                  ) : (
                    <span className="px-2 py-0.5 rounded text-[11px] font-semibold bg-zinc-100 text-zinc-600 dark:bg-zinc-800 dark:text-zinc-400">{tx("单边独立流水")}</span>
                  )}
                </div>

                {/* If paired transfer: display counterpart & reject button */}
                {txn.paired_transfer ? (
                  <div className="space-y-2">
                    <div className="p-3 rounded-lg bg-zinc-50 dark:bg-zinc-800/40 border border-zinc-200/80 dark:border-zinc-800 text-xs space-y-1.5">
                      <div className="flex items-center justify-between">
                        <span className="text-zinc-500 dark:text-zinc-400 text-[11px]">
                          {txn.paired_transfer.is_outflow ? tx("对端入账流水") : tx("对端出账流水")}
                        </span>
                        <span className="text-[11px] text-zinc-400 font-mono">{tx("对端记账:")} {formatDateTime(txn.paired_transfer.counterpart?.occurred_at || txn.paired_transfer.counterpart?.transacted_at)}
                        </span>
                      </div>
                      <div className="font-semibold text-zinc-900 dark:text-white flex items-center justify-between">
                        <div className="flex items-center gap-1.5 truncate">
                          <span className="truncate">{txn.paired_transfer.counterpart?.account_name} · {txn.paired_transfer.counterpart?.name}</span>
                          {txn.paired_transfer.counterpart?.owner_name && !txn.paired_transfer.counterpart.is_owner && (
                            <span
                              title={tx("由 {p0} 共享", {p0: (txn.paired_transfer.counterpart.owner_name)})}
                              className="inline-flex items-center gap-1 px-1.5 py-0.2 rounded text-[11px] font-normal bg-purple-50 dark:bg-purple-950/60 text-purple-600 dark:text-purple-300 border border-purple-200 dark:border-purple-800"
                            >
                              <Users className="w-2.5 h-2.5" />
                              <span>{tx("{p0} 共享", {p0: (txn.paired_transfer.counterpart.owner_name)})}</span>
                            </span>
                          )}
                        </div>
                        <span className="font-mono font-bold text-zinc-900 dark:text-zinc-100 ml-2">
                          {txn.paired_transfer.counterpart?.amount} {txn.paired_transfer.counterpart?.currency}
                        </span>
                      </div>
                    </div>

                    <button
                      onClick={handleRejectTransfer}
                      disabled={pairingLoading}
                      className="w-full py-2 px-3 rounded-lg border border-rose-200 dark:border-rose-900/60 text-rose-600 dark:text-rose-400 hover:bg-rose-50 dark:hover:bg-rose-950/30 text-xs font-semibold flex items-center justify-center gap-1.5 transition-colors cursor-pointer"
                    >
                      <ShieldAlert className="w-3.5 h-3.5" />
                      <span>{tx("解除配对（恢复为独立收支并防重撮合）")}</span>
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
                      <span>{tx("检索同额对端流水（配对为内部转账）")}</span>
                    </button>

                    {transferLoading ? (
                      <div className="py-4 text-center text-xs text-zinc-400">{tx("正在查找对端交易...")}</div>
                    ) : transferCandidates.length > 0 ? (
                      <div className="space-y-1.5 pt-1">
                        <div className="text-[11px] text-zinc-400">{tx("找到以下同额候选交易：")}</div>
                        {transferCandidates.map((tc) => (
                          <div
                            key={tc.id}
                            className="p-2 rounded-lg border border-zinc-200 dark:border-zinc-700 flex items-center justify-between text-xs bg-zinc-50 dark:bg-zinc-900/40"
                          >
                            <div>
                              <div className="font-semibold text-zinc-800 dark:text-zinc-200">
                                {tc.owner_name && !tc.is_owner ? `${tc.owner_name} · ` : ''}{tc.account_name} · {tc.name}
                              </div>
                              <div className="text-[11px] text-zinc-400">
                                {formatDateTime(tc.occurred_at || tc.transacted_at)} {tx("· 入账金额:")} {tc.amount} {tc.currency}
                              </div>
                            </div>
                            <button
                              onClick={() => handlePairTransfer(tc.id)}
                              disabled={pairingLoading}
                              className="px-2.5 py-1 bg-blue-600 hover:bg-blue-700 text-white rounded text-xs font-bold transition-colors"
                            >{tx("配对")}</button>
                          </div>
                        ))}
                      </div>
                    ) : null}
                  </div>
                )}
              </div>}

              {/* 5. NOTES & RAW AUDIT */}
              <div className="space-y-2 text-xs">
                <span className="font-semibold text-zinc-700 dark:text-zinc-300">{tx("备注说明 (Notes)")}</span>
                <div className="p-3 bg-zinc-50 dark:bg-zinc-800/30 rounded-xl border border-zinc-100 dark:border-zinc-800/60 text-zinc-600 dark:text-zinc-400 leading-relaxed font-sans">
                  {txn.notes || tx("暂无额外备注信息")}
                </div>
              </div>
            </>
          )}
        </div>

        {/* Drawer Footer */}
        <div className="px-6 py-4 border-t border-zinc-200 dark:border-zinc-800 flex items-center justify-between gap-3">
          <button
            disabled={loading || !txn || txn.id !== transactionId || txn.deletion_info?.can_delete === false || deleting || !!txn?.extra?.scheduled_occurrence_id}
            data-testid="drawer-delete-transaction-footer-btn"
            onClick={() => { setDeleteScope(null); setShowDeleteModal(true); }}
            className="flex items-center gap-1.5 px-3 py-2 rounded-xl text-xs font-semibold text-rose-600 dark:text-rose-400 hover:bg-rose-50 dark:hover:bg-rose-950/30 transition-colors"
          >
            <Trash2 className="w-3.5 h-3.5" />
            <span>{tx("删除该笔交易")}</span>
          </button>
          <div className="flex items-center gap-3">
            <button
              onClick={onClose}
              className="px-4 py-2 rounded-xl text-xs font-semibold text-zinc-600 dark:text-zinc-300 hover:bg-zinc-100 dark:hover:bg-zinc-800 transition-colors"
            >{tx("关闭")}</button>
          </div>
        </div>
      </aside>

      {showDeleteModal && <DeleteTransactionModal transaction={txn} scope={deleteScope}
        onScopeChange={setDeleteScope} onConfirm={handleDeleteTransaction}
        onClose={() => setShowDeleteModal(false)} deleting={deleting} privacyMode={privacyMode} />}

      {/* 拆分账单弹窗 */}
      <SplitTransactionModal
        isOpen={showSplitModal}
        onClose={() => setShowSplitModal(false)}
        transaction={txn}
        categories={allCategories.filter(category => !category.category_type || category.category_type === 'expense' || category.name === '其他')}
        onSuccess={() => {
          loadTransaction();
          if (onTransactionUpdated) onTransactionUpdated();
          window.dispatchEvent(new CustomEvent('transaction-updated'));
        }}
      />
    </div>
  );
}
