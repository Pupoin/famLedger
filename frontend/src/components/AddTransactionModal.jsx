import { categoryLabel, tx, useLocale } from "../localization.js";
import { apiErrorMessage } from '../api/errorMessages';
import { currencySymbol } from '../utils/currency';
import React, { useState, useEffect, useRef, useCallback } from 'react';
import { createPortal } from 'react-dom';
import { X, Minus, Plus, RotateCcw, ArrowRightLeft, ChevronDown, Search } from 'lucide-react';
import { fetchWithAuth } from '../api/fetchWithAuth';
import { useCurrency } from '../CurrencyContext';
import { useToast } from '../ToastContext';
import { toLocalISODate, toLocalISOTime, localToUTCISO } from '../utils/dates';
import { createTransactionExternalId } from '../utils/transactionIds';
import { formatAccountDisplayName } from '../utils/accountIcons';
import AccountSelectDropdown from './AccountSelectDropdown';
import { transferSourceAccounts, transferDestinationAccounts } from '../utils/transferAccounts';

// 四种交易类型 tab 配置
const TABS = [
  { id: 'expense',  labelZh: '支出',  labelEn: 'Expense',  Icon: Minus,           color: 'text-zinc-900 dark:text-white',   bg: 'bg-zinc-900 dark:bg-white' },
  { id: 'income',   labelZh: '收入',  labelEn: 'Income',   Icon: Plus,            color: 'text-emerald-700 dark:text-emerald-300', bg: 'bg-emerald-600' },
  { id: 'refund',   labelZh: '退款',  labelEn: 'Refund',   Icon: RotateCcw,       color: 'text-blue-700 dark:text-blue-300',  bg: 'bg-blue-600' },
  { id: 'transfer', labelZh: '转账',  labelEn: 'Transfer', Icon: ArrowRightLeft,  color: 'text-purple-700 dark:text-purple-300', bg: 'bg-purple-600' },
];



export default function AddTransactionModal({ open, onClose, onSuccess, defaultAccountId, defaultType }) {
  useLocale();
  const { symbol, currencies, currency: defaultCurrency } = useCurrency();
  const { showToast } = useToast();
  const [activeTab, setActiveTab] = useState(defaultType || 'expense');
  const [accounts, setAccounts] = useState([]);
  const [categories, setCategories] = useState([]);
  const [showDetails, setShowDetails] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [bankAmount, setBankAmount] = useState('');
  const [masterBankAmount, setMasterBankAmount] = useState('');
  useEffect(() => { setBankAmount(''); setMasterBankAmount(''); }, [open]);
  const descRef = useRef(null);
  const externalId = useRef(null);
  const onCloseRef = useRef(onClose);
  useEffect(() => { onCloseRef.current = onClose; }, [onClose]);
  useEffect(() => { if (open) externalId.current = createTransactionExternalId(); }, [open]);

  const [form, setForm] = useState(() => {
    const now = new Date();
    return {
      name: '',
      account_id: defaultAccountId || '',
      to_account_id: '',  // 转账目标账户
      amount: '',
      currency: defaultCurrency || 'CNY',
      category: '',
      category_id: '',
      date: toLocalISODate(now),
      time: toLocalISOTime(now, true),
      notes: '',
    };
  });

  const [reimbursementType, setReimbursementType] = useState('none'); // 'none' | 'corporate' | 'personal_advance'
  const [counterparty, setCounterparty] = useState('');
  const [selectedTags, setSelectedTags] = useState([]);
  const [tagInput, setTagInput] = useState('');
  const [systemTags, setSystemTags] = useState([]);

  // 退款关联原消费状态
  const [selectedOriginalTxn, setSelectedOriginalTxn] = useState(null);
  const [candidateExpenses, setCandidateExpenses] = useState([]);
  const [loadingCandidates, setLoadingCandidates] = useState(false);
  const [refundSearchQuery, setRefundSearchQuery] = useState('');

  const [serverError, setServerError] = useState('');
  const [errors, setErrors] = useState({});

  // ── 移动端物理返回键 / 侧滑手势 / 浏览器后退拦截：按下返回时退出新建交易界面 ──
  useEffect(() => {
    if (!open) return;

    const stateKey = 'add_transaction_modal_open';
    if (!window.history.state || !window.history.state[stateKey]) {
      window.history.pushState({ [stateKey]: true }, '');
    }

    let closedByPop = false;

    const handlePopState = () => {
      closedByPop = true;
      onCloseRef.current();
    };

    window.addEventListener('popstate', handlePopState);

    return () => {
      window.removeEventListener('popstate', handlePopState);
      if (!closedByPop && window.history.state && window.history.state[stateKey]) {
        window.history.back();
      }
    };
  }, [open]);

  // 根据当前 activeTab (支出/退款 vs 收入) 联动筛选展示分类
  const visibleCategories = React.useMemo(() => {
    const pool = categories;
    const targetType = activeTab === 'income' ? 'income' : 'expense';
    return pool.filter((c) => c.name === '其他' || (c.category_type || 'expense') === targetType);
  }, [categories, activeTab]);

  const currentSelectedAccount = React.useMemo(() => {
    return accounts.find((a) => a.id === form.account_id);
  }, [accounts, form.account_id]);

  const isCurrentAccountReadOnly = currentSelectedAccount && currentSelectedAccount.can_edit === false;

  // 拉取可供退款冲抵的候选历史支出
  const fetchRefundCandidates = useCallback(async (query = '') => {
    try {
      setLoadingCandidates(true);
      const params = new URLSearchParams({ limit: '20', days: '180' });
      if (query && query.trim()) params.set('search', query.trim());
      if (form.account_id) params.set('account_id', form.account_id);
      const res = await fetchWithAuth(`/api/v1/refunds/candidates?${params.toString()}`);
      if (res.ok) {
        const data = await res.json();
        setCandidateExpenses(data.candidates || []);
      }
    } catch {
      // 静默失败
    } finally {
      setLoadingCandidates(false);
    }
  }, [form.account_id]);

  // 当处于退款 Tab 且未锁定原消费时，防抖拉取候选支出
  useEffect(() => {
    if (open && activeTab === 'refund' && !selectedOriginalTxn) {
      const timer = setTimeout(() => {
        fetchRefundCandidates(refundSearchQuery);
      }, 200);
      return () => clearTimeout(timer);
    }
  }, [open, activeTab, selectedOriginalTxn, refundSearchQuery, fetchRefundCandidates]);

  // 选中某笔原消费：智能填充描述、金额与分类
  const handleSelectOriginalTxn = (cand) => {
    setSelectedOriginalTxn(cand);
    setForm((prev) => {
      const updates = { ...prev };
      if (!prev.name.trim() || prev.name.trim() === '退款' || prev.name.trim() === '退款冲抵') {
        updates.name = `${cand.narration || '原消费'} 退款`;
      }
      if (!prev.amount || parseFloat(prev.amount) <= 0) {
        updates.amount = cand.remaining_refundable || cand.original_amount || cand.amount;
        updates.currency = cand.original_currency || cand.currency;
      }
      if (!prev.account_id && cand.account_id) {
        updates.account_id = cand.account_id;
      }
      if (cand.category_name) {
        updates.category = cand.category_name;
      }
      if (cand.category_id) {
        updates.category_id = cand.category_id;
      }
      return updates;
    });
  };

  const handleClearOriginalTxn = () => {
    setSelectedOriginalTxn(null);
  };

  // 切换类型 Tab 时重置分类，防止支出分类被带入收入
  const handleTabChange = (newTab) => {
    if (newTab === activeTab) return;
    setActiveTab(newTab);
    setSelectedOriginalTxn(null);
    setRefundSearchQuery('');
    setForm((prev) => ({
      ...prev,
      category: '',
      category_id: '',
    }));
  };

  // 重置表单为当前时刻
  const resetForm = useCallback(() => {
    const now = new Date();
    setForm({
      name: '',
      account_id: defaultAccountId || '',
      to_account_id: '',
      amount: '',
      currency: defaultCurrency || 'CNY',
      category: '',
      category_id: '',
      date: toLocalISODate(now),
      time: toLocalISOTime(now, true),
      notes: '',
    });
    setReimbursementType('none');
    setCounterparty('');
    setSelectedTags([]);
    setTagInput('');
    setSelectedOriginalTxn(null);
    setRefundSearchQuery('');
    setCandidateExpenses([]);
    setActiveTab(defaultType || 'expense');
    setShowDetails(false);
  }, [defaultCurrency, defaultAccountId, defaultType]);

  // 打开时拉取账户、标签及家庭分类全量列表，并自动 focus 描述输入框
  useEffect(() => {
    if (!open) return;
    (async () => {
      try {
        const [resAcc, resTags, resCats] = await Promise.all([
          fetchWithAuth('/api/v1/accounts'),
          fetchWithAuth('/api/v1/tags'),
          fetchWithAuth('/api/v1/categories?category_type=all'),
        ]);
        if (resAcc.ok) {
          const data = await resAcc.json();
          const accList = Array.isArray(data) ? data : data.accounts || data.items || [];
          setAccounts(accList);
          const curAcc = accList.find((a) => a.id === (defaultAccountId || form.account_id));
          if (curAcc && curAcc.currency) {
            setForm((prev) => ({ ...prev, currency: curAcc.currency }));
          }
        }
        if (resTags.ok) {
          const tagData = await resTags.json();
          setSystemTags(tagData.tags || tagData.items || []);
        }
        if (resCats.ok) {
          const catData = await resCats.json();
          setCategories(catData.categories || catData.items || []);
        }
      } catch { /* 静默失败 */ }
    })();
    // 仅在当前未主动聚焦其他输入框时对焦描述输入框，防止抢夺用户焦点
    const timer = setTimeout(() => {
      if (document.activeElement === document.body || document.activeElement === descRef.current) {
        descRef.current?.focus();
      }
    }, 50);
    return () => clearTimeout(timer);
  }, [open]);

  // 打开后重置表单
  useEffect(() => {
    if (open) resetForm();
  }, [open, resetForm]);

  // ESC 关闭
  useEffect(() => {
    if (!open) return;
    const handler = (e) => { if (e.key === 'Escape') onClose(); };
    document.addEventListener('keydown', handler);
    return () => document.removeEventListener('keydown', handler);
  }, [open, onClose]);

  if (!open) return null;

  const handleChange = (e) => {
    const { name, value } = e.target;
    setForm((prev) => {
      const next = { ...prev, [name]: value };
      if (name === 'account_id') {
        const targetAcc = accounts.find((a) => a.id === value);
        if (targetAcc && targetAcc.currency) {
          next.currency = targetAcc.currency;
        }
      }
      return next;
    });
    if (serverError) setServerError('');
    if (errors[name]) setErrors((prev) => ({ ...prev, [name]: null }));
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    setServerError('');
    const newErrors = {};
    if (!form.name.trim()) newErrors.name = '请填写交易描述';
    if (!form.amount || isNaN(parseFloat(form.amount)) || parseFloat(form.amount) <= 0) {
      newErrors.amount = '请输入有效金额';
    }

    // 检查所选账户是否有记账权限
    if (isCurrentAccountReadOnly) {
      const errMsg = `您对所选账户【${currentSelectedAccount?.name || '该账户'}】仅有只读权限，无法录入新交易`;
      showToast(tx(errMsg), 'error');
      setServerError(errMsg);
      return;
    }

    if (Object.keys(newErrors).length > 0) {
      setErrors(newErrors);
      showToast(tx(Object.values(newErrors)[0]), 'error');
      return;
    }

    try {
      setSubmitting(true);

      const payload = {
        external_id: externalId.current,
        narration: form.name.trim(),
        amount: form.amount,
        currency: form.currency || currentSelectedAccount?.currency || 'CNY',
        ...(bankAmount && currentSelectedAccount ? { settlement_amount: bankAmount, settlement_currency: currentSelectedAccount.currency, settlement_source: "manual_confirmation" } : {}),
        ...(masterBankAmount && currentSelectedAccount?.parent_account_id ? { master_settlement_amount: masterBankAmount, master_settlement_currency: (accounts.find(a => a.id === currentSelectedAccount.parent_account_id) || currentSelectedAccount.parent_account)?.currency } : {}),
        transaction_type: activeTab,
        occurred_at: localToUTCISO(form.date, form.time),
        notes: form.notes || null,
      };

      // 账户标识
      if (form.account_id) payload.account = form.account_id;

      // 退款关联原消费 (冲抵原支出)
      if (activeTab === 'refund' && selectedOriginalTxn) {
        payload.refund_of_transaction_id = selectedOriginalTxn.id;
        if (selectedOriginalTxn.original_currency && selectedOriginalTxn.original_currency !== form.currency) {
          const quantity = window.prompt(`确认冲抵原消费金额（${selectedOriginalTxn.original_currency}）`);
          if (quantity === null) { setSubmitting(false); return; }
          payload.allocation_amount = quantity;
          payload.allocation_currency = selectedOriginalTxn.original_currency;
          payload.refund_original_amount = form.amount;
        }
      }

      // 分类（单选分类：仅支出和收入）
      if (activeTab !== 'transfer' && (form.category || form.category_id)) {
        if (form.category) payload.category_name = form.category;
        if (form.category_id) {
          payload.category_id = form.category_id;
        }
      }

      // 标签与报销设置
      const tags = [...selectedTags];
      if (activeTab === 'expense' && reimbursementType !== 'none') {
        if (!tags.includes('待报销')) tags.push('待报销');
        payload.extra = {
          reimbursement_type: reimbursementType,
          excluded_from_stats: true,
          ...(counterparty.trim() ? { counterparty: { name: counterparty.trim() } } : {}),
        };
      }
      if (activeTab !== 'transfer' && tags.length > 0) {
        payload.tags = tags;
      }

      // 转账特殊处理：调用专用接口，原子创建两笔流水+配对
      if (activeTab === 'transfer') {
        if (!form.to_account_id) {
          showToast(tx("请选择转入账户"), 'error');
          setServerError('请选择转入账户');
          setSubmitting(false);
          return;
        }
        if (!form.account_id) {
          showToast(tx("请选择转出账户"), 'error');
          setServerError('请选择转出账户');
          setSubmitting(false);
          return;
        }
        if (isCurrentAccountReadOnly) {
          const errMsg = `您对转出账户【${currentSelectedAccount?.name}】仅有只读权限，无法发起转账`;
          showToast(tx(errMsg), 'error');
          setServerError(errMsg);
          setSubmitting(false);
          return;
        }
        const transferPayload = {
          from_account_id: form.account_id,
          to_account_id: form.to_account_id,
          amount: parseFloat(form.amount),
          narration: form.name.trim() || '内部转账',
          name: form.name.trim() || '内部转账',
          transacted_at: form.date,
          time: form.time || undefined,
          occurred_at: localToUTCISO(form.date, form.time),
          notes: form.notes || null,
          currency: currentSelectedAccount?.currency || form.currency || 'CNY',
        };
        const res = await fetchWithAuth('/api/v1/transfers/create', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(transferPayload),
        });
        if (res.ok) {
          showToast(tx("转账已创建"), 'success');
          window.dispatchEvent(new CustomEvent('transaction-added'));
          window.dispatchEvent(new CustomEvent('accounts-updated'));
          onClose();
          if (onSuccess) onSuccess();
        } else {
          const err = await res.json().catch(() => ({}));
          const errMsg = apiErrorMessage(err.detail, res.status === 403 ? '您对此账户没有转账权限' : '转账失败，请重试');
          showToast(tx(errMsg), 'error');
          setServerError(errMsg);
        }
        setSubmitting(false);
        return;
      }

      const res = await fetchWithAuth('/api/v1/transactions', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });

      if (res.ok) {
        const result = await res.json();
        showToast(tx(result.status === 'pending_fx' ? '已保存待换汇，尚未入账' : '交易已添加'), 'success');
        window.dispatchEvent(new Event('pending-fx-changed'));
        window.dispatchEvent(new CustomEvent('transaction-added'));
        window.dispatchEvent(new CustomEvent('accounts-updated'));
        onClose();
        if (onSuccess) onSuccess();
      } else {
        const err = await res.json().catch(() => ({}));
        const errMsg = apiErrorMessage(err.detail, res.status === 403 ? '您对此账户仅有只读权限，无法录入新交易' : '添加失败，请重试');
        showToast(tx(errMsg), 'error');
        setServerError(errMsg);
      }
    } catch {
      showToast(tx("网络错误，请稍后重试"), 'error');
      setServerError('网络请求发生错误，请稍后重试');
    } finally {
      setSubmitting(false);
    }
  };

  const activeTabCfg = TABS.find((t) => t.id === activeTab);

  const modalContent = (
    <div
      className="fixed inset-0 z-[9999] flex items-end sm:items-center justify-center p-0 sm:p-4 bg-black/50 backdrop-blur-xs overscroll-none animate-in fade-in duration-200"
      onClick={(e) => { if (e.target === e.currentTarget) onClose(); }}
    >
      <div className="relative w-full sm:max-w-lg bg-white dark:bg-zinc-900 rounded-t-3xl sm:rounded-2xl shadow-2xl overflow-hidden h-[86dvh] max-h-[86dvh] sm:h-auto sm:max-h-[85vh] flex flex-col animate-in slide-in-from-bottom-4 sm:slide-in-from-bottom-0 sm:zoom-in-95 duration-200">
        {/* 移动端顶部抽屉小把手 */}
        <div className="w-10 h-1 bg-zinc-300 dark:bg-zinc-700 rounded-full mx-auto my-2 shrink-0 sm:hidden" />

        {/* ── 标题栏 (固定不被挤压) ── */}
        <div className="shrink-0 flex items-center justify-between px-5 pt-2 sm:pt-5 pb-3 border-b border-zinc-100 dark:border-zinc-800">
          <h2 className="text-base font-bold text-zinc-900 dark:text-white">{tx("新建交易")}</h2>
          <button
            type="button"
            onClick={onClose}
            className="p-1.5 rounded-full text-zinc-400 hover:text-zinc-600 dark:hover:text-zinc-200 hover:bg-zinc-100 dark:hover:bg-zinc-800 transition-colors cursor-pointer"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* ── 类型 Tabs (固定不被挤压) ── */}
        <div className="shrink-0 px-5 pt-3">
          <div className="flex gap-1.5 p-1 rounded-xl bg-zinc-100 dark:bg-zinc-800/70">
            {TABS.map((tab) => {
              const isActive = activeTab === tab.id;
              const Icon = tab.Icon;
              return (
                <button
                  key={tab.id}
                  type="button"
                  onClick={() => handleTabChange(tab.id)}
                  className={`flex-1 flex items-center justify-center gap-1 py-2 rounded-lg text-xs font-semibold transition-all ${
                    isActive
                      ? 'bg-white dark:bg-zinc-700 text-zinc-900 dark:text-white shadow-sm'
                      : 'text-zinc-500 dark:text-zinc-400 hover:text-zinc-700 dark:hover:text-zinc-200'
                  }`}
                >
                  <Icon className="w-3.5 h-3.5" />
                  <span>{tx(tab.labelZh)}</span>
                </button>
              );
            })}
          </div>
        </div>

        {/* ── 表单正文 (独立可滚动，min-h-0 确保不向上撑爆容器) ── */}
        <form
          id="add-transaction-form"
          onSubmit={handleSubmit}
          className="flex-1 min-h-0 overflow-y-auto px-5 py-4 space-y-4 overscroll-contain"
        >
          {/* 权限或接口报错提示横幅 */}
          {serverError && (
            <div className="p-3 rounded-xl bg-red-50 dark:bg-red-950/40 border border-red-200 dark:border-red-800 text-xs text-red-700 dark:text-red-300 flex items-center gap-2 animate-in fade-in">
              <span className="text-base shrink-0">⚠️</span>
              <span className="flex-1 font-medium">{tx(serverError)}</span>
              <button
                type="button"
                onClick={() => setServerError('')}
                className="text-red-400 hover:text-red-600 font-bold ml-1 cursor-pointer"
              >
                ✕
              </button>
            </div>
          )}

          {/* ── 退款专属：选择/匹配原消费 ── */}
          {activeTab === 'refund' && (
            <div className="p-3.5 rounded-2xl bg-blue-50/50 dark:bg-blue-950/20 border border-blue-200/80 dark:border-blue-900/50 space-y-2.5">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-1.5 text-xs font-bold text-blue-900 dark:text-blue-300">
                  <RotateCcw className="w-3.5 h-3.5" />
                  <span>{tx("匹配原消费 (退款冲抵)")}</span>
                </div>
                {selectedOriginalTxn ? (
                  <button
                    type="button"
                    onClick={handleClearOriginalTxn}
                    className="text-[11px] text-zinc-500 hover:text-red-500 transition-colors"
                  >{tx("解除关联")}</button>
                ) : (
                  <span className="text-[11px] text-blue-600/70 dark:text-blue-400/70">{tx("可选 · 自动冲抵支出与分类")}</span>
                )}
              </div>

              {selectedOriginalTxn ? (
                /* 已选中原消费卡片 */
                <div className="p-3 rounded-xl bg-white dark:bg-zinc-900 border border-blue-300 dark:border-blue-800 shadow-xs flex items-center justify-between gap-3">
                  <div className="min-w-0 flex-1">
                    <div className="font-semibold text-xs text-zinc-900 dark:text-white truncate">
                      {selectedOriginalTxn.narration}
                    </div>
                    <div className="text-[11px] text-zinc-500 dark:text-zinc-400 flex flex-wrap items-center gap-2 mt-0.5">
                      <span>📅 {selectedOriginalTxn.transacted_at}</span>
                      {selectedOriginalTxn.category_name && (
                        <span className="px-1.5 py-0.2 rounded bg-zinc-100 dark:bg-zinc-800 text-[11px] text-zinc-700 dark:text-zinc-300">
                          {categoryLabel(selectedOriginalTxn.category_name)}
                        </span>
                      )}
                      <span className="text-emerald-600 dark:text-emerald-400 font-mono font-medium">{tx("剩余可退: ¥")} {selectedOriginalTxn.remaining_refundable}
                      </span>
                    </div>
                  </div>
                  <button
                    type="button"
                    onClick={handleClearOriginalTxn}
                    className="p-1.5 rounded-lg text-zinc-400 hover:text-zinc-600 dark:hover:text-zinc-200 hover:bg-zinc-100 dark:hover:bg-zinc-800"
                    title={tx("更换原消费")}
                  >
                    <X className="w-4 h-4" />
                  </button>
                </div>
              ) : (
                /* 搜索与候选列表 */
                <div className="space-y-2">
                  <div className="relative">
                    <Search className="w-3.5 h-3.5 text-zinc-400 absolute left-3 top-1/2 -translate-y-1/2 pointer-events-none" />
                    <input
                      type="text"
                      value={refundSearchQuery}
                      onChange={(e) => setRefundSearchQuery(e.target.value)}
                      placeholder={tx("搜索近期历史消费商户或流水...")}
                      className="w-full pl-8 pr-7 py-2 text-xs rounded-xl border border-zinc-200 dark:border-zinc-700 bg-white dark:bg-zinc-900 text-zinc-900 dark:text-zinc-100 placeholder-zinc-400 focus:outline-none focus:ring-1 focus:ring-blue-500"
                    />
                    {refundSearchQuery && (
                      <button
                        type="button"
                        onClick={() => setRefundSearchQuery('')}
                        className="absolute right-2.5 top-1/2 -translate-y-1/2 text-zinc-400 hover:text-zinc-600 dark:hover:text-zinc-200"
                      >
                        <X className="w-3.5 h-3.5" />
                      </button>
                    )}
                  </div>

                  <div className="max-h-40 overflow-y-auto space-y-1.5 pr-0.5 scrollbar-thin">
                    {loadingCandidates ? (
                      <div className="py-3 text-center text-xs text-zinc-400">{tx("检索候选消费中...")}</div>
                    ) : candidateExpenses.length === 0 ? (
                      <div className="py-3 text-center text-xs text-zinc-400">
                        {refundSearchQuery ? tx("未找到相关支出消费") : tx("暂无近 180 天未退款消费")}
                      </div>
                    ) : (
                      candidateExpenses.map((cand) => (
                        <div
                          key={cand.id}
                          data-testid="refund-candidate-item"
                          onClick={() => handleSelectOriginalTxn(cand)}
                          className="p-2.5 rounded-xl bg-white dark:bg-zinc-900 border border-zinc-200/60 dark:border-zinc-800 hover:border-blue-400 dark:hover:border-blue-500 cursor-pointer transition-colors flex items-center justify-between text-xs group"
                        >
                          <div className="min-w-0 pr-2">
                            <div className="font-medium text-zinc-900 dark:text-zinc-100 truncate group-hover:text-blue-600 dark:group-hover:text-blue-400 transition-colors">
                              {cand.narration}
                            </div>
                            <div className="text-[11px] text-zinc-400 flex items-center gap-1.5 mt-0.5">
                              <span>{cand.transacted_at}</span>
                              {cand.category_name && <span>· {categoryLabel(cand.category_name)}</span>}
                              {cand.account_name && <span>· {cand.account_name}</span>}
                            </div>
                          </div>
                          <div className="text-right shrink-0">
                            <div className="font-mono font-semibold text-zinc-800 dark:text-zinc-200">
                              {cand.amount} {cand.currency}
                            </div>
                            <div className="text-[11px] font-mono text-emerald-600 dark:text-emerald-400">{tx("可退:")} {cand.remaining_refundable} {cand.original_currency || cand.currency}
                            </div>
                          </div>
                        </div>
                      ))
                    )}
                  </div>
                </div>
              )}
            </div>
          )}

          {/* 描述 */}
          <div>
            <label className="block text-xs font-semibold text-zinc-700 dark:text-zinc-300 mb-1.5">{tx("描述")} <span className="text-red-500">*</span>
            </label>
            <input
              ref={descRef}
              type="text"
              name="name"
              value={form.name}
              onChange={handleChange}
              placeholder={tx("例如：超市购物、家庭电费、工作午餐")}
              autoComplete="off"
              className={`w-full px-3.5 py-2.5 rounded-xl border text-sm text-zinc-900 dark:text-zinc-100 placeholder-zinc-400 transition focus:outline-none ${
                errors.name
                  ? 'border-red-500 ring-1 ring-red-500 bg-red-50/20 dark:bg-red-950/20'
                  : 'border-zinc-200 dark:border-zinc-700 bg-white dark:bg-zinc-800 focus:ring-2 focus:ring-zinc-900 dark:focus:ring-white'
              }`}
            />
            {errors.name && (
              <p className="text-xs text-red-500 mt-1 font-medium">{tx(errors.name)}</p>
            )}
          </div>

          {/* 账户 */}
          <div>
            <label className="block text-xs font-semibold text-zinc-700 dark:text-zinc-300 mb-1.5">{tx("账户")}</label>
            <AccountSelectDropdown
              name="account_id"
              value={form.account_id}
              onChange={handleChange}
              accounts={activeTab === 'transfer' ? transferSourceAccounts(accounts) : accounts}
              selectedAccountFallback={currentSelectedAccount}
              placeholder={tx("选择账户")}
              isReadOnly={isCurrentAccountReadOnly}
              showSharedTip={true}
              testId="add-modal-account-select"
            />
            {/* 只读账户即时警告提示 */}
            {isCurrentAccountReadOnly && (
              <div className="mt-2 p-2.5 rounded-xl bg-amber-50 dark:bg-amber-950/40 border border-amber-300 dark:border-amber-800 text-xs text-amber-800 dark:text-amber-300 flex items-start gap-2 animate-in fade-in">
                <span className="text-sm shrink-0">⚠️</span>
                <span>{tx("您对此账户（")} <strong>{formatAccountDisplayName(currentSelectedAccount)}</strong> {tx("）仅有只读权限，无法录入新交易。请切换至您有名下或有编辑权限的账户。")}</span>
              </div>
            )}
          </div>

          {/* 转账目标账户（仅转账类型显示） */}
          {activeTab === 'transfer' && (
            <div>
              <label className="block text-xs font-semibold text-zinc-700 dark:text-zinc-300 mb-1.5">{tx("目标账户")}</label>
              <AccountSelectDropdown
                name="to_account_id"
                value={form.to_account_id}
                onChange={handleChange}
                accounts={transferDestinationAccounts(accounts, form.account_id)}
                placeholder={tx("选择目标账户")}
                testId="add-modal-to-account-select"
              />
              {accounts.find(account => account.id === form.to_account_id)?.can_edit === false && (
                <p className="mt-2 text-xs text-amber-700 dark:text-amber-300">{tx('只读共享账户仅允许转入，不能转出或修改已有流水。')}</p>
              )}
            </div>
          )}

          {/* 金额 + 货币 */}
          <div>
            <label className="block text-xs font-semibold text-zinc-700 dark:text-zinc-300 mb-1.5">{tx("金额")} <span className="text-red-500">*</span>
            </label>
            <div className="flex gap-2">
              <div className="relative flex-1">
                <span className="absolute left-3.5 top-1/2 -translate-y-1/2 text-sm font-medium text-zinc-500 dark:text-zinc-400">
                  {currencySymbol(form.currency)}
                </span>
                <input
                  type="number"
                  name="amount"
                  value={form.amount}
                  onChange={handleChange}
                  placeholder="0.00"
                  min="0"
                  step="0.01"
                  className={`w-full pl-8 pr-3.5 py-2 rounded-xl border text-xs sm:text-sm text-zinc-900 dark:text-zinc-100 transition focus:outline-none ${
                    errors.amount
                      ? 'border-red-500 ring-1 ring-red-500 bg-red-50/20 dark:bg-red-950/20'
                      : 'border-zinc-200 dark:border-zinc-700 bg-white dark:bg-zinc-800 focus:ring-2 focus:ring-zinc-900 dark:focus:ring-white'
                  }`}
                />
              </div>
              <div className="relative w-28">
                <select
                  name="currency"
                  value={form.currency}
                  onChange={handleChange}
                  className="w-full px-3 py-2 pr-8 rounded-xl border border-zinc-200 dark:border-zinc-700 bg-white dark:bg-zinc-800 text-xs text-zinc-900 dark:text-zinc-100 focus:outline-none focus:ring-2 focus:ring-zinc-900 dark:focus:ring-white appearance-none transition"
                >
                  {(currencies || ['CNY', 'USD', 'EUR', 'HKD', 'JPY']).map((c) => {
                    const code = typeof c === 'object' ? c.code : c;
                    return (
                      <option key={code} value={code}>
                        {code}
                      </option>
                    );
                  })}
                </select>
                <ChevronDown className="absolute right-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-zinc-400 pointer-events-none" />
              </div>
            </div>
            {errors.amount && (
              <p className="text-xs text-red-500 mt-1 font-medium">{tx(errors.amount)}</p>
            )}
          </div>

          {activeTab !== 'transfer' && currentSelectedAccount && <div className="space-y-2">
            <label className="block text-xs">{tx("银行实际结算金额（")} {currentSelectedAccount.currency} {tx("，可选）")} <input type="number" min="0.0001" step="0.0001" value={bankAmount} onChange={e => setBankAmount(e.target.value)} className="w-full border rounded p-2 dark:bg-zinc-800" />
            </label>
            {currentSelectedAccount.parent_account_id && (accounts.find(a => a.id === currentSelectedAccount.parent_account_id) || currentSelectedAccount.parent_account)?.currency !== currentSelectedAccount.currency && <label className="block text-xs">{tx("主卡实际结算金额（")} {(accounts.find(a => a.id === currentSelectedAccount.parent_account_id) || currentSelectedAccount.parent_account)?.currency} {tx("，可选）")} <input type="number" min="0.0001" step="0.0001" value={masterBankAmount} onChange={e => setMasterBankAmount(e.target.value)} className="w-full border rounded p-2 dark:bg-zinc-800" />
            </label>}
            <p className="text-xs text-zinc-500">{tx("未填写银行金额时按交易日期换汇；汇率不可用则保存为待换汇。")}</p>
          </div>}
          {/* 分类（单选，转账不显示） */}
          {activeTab !== 'transfer' && (
            <div>
              <div className="flex items-center justify-between mb-1.5">
                <label className="block text-xs font-semibold text-zinc-700 dark:text-zinc-300">
                  {activeTab === 'income' ? tx("收入分类") : tx("支出分类")} {tx("(单选)")}</label>
                <span className="text-[11px] text-zinc-400">{tx("共")} {visibleCategories.length} {tx("个分类")}</span>
              </div>
              <div className="relative">
                <select
                  name="category"
                  value={form.category_id || (categories.find((c) => c.name === form.category)?.id) || ''}
                  onChange={(e) => {
                    const selectedVal = e.target.value;
                    const pool = categories;
                    const selectedCat = pool.find(
                      (c) => String(c.id) === String(selectedVal) || c.name === selectedVal
                    );
                    setForm((prev) => ({
                      ...prev,
                      category_id: selectedCat ? selectedCat.id : selectedVal,
                      category: selectedCat ? selectedCat.name : selectedVal,
                    }));
                  }}
                  data-testid="add-modal-category-select"
                  className="w-full px-3 py-2 pr-10 rounded-xl border border-zinc-200 dark:border-zinc-700 bg-white dark:bg-zinc-800 text-xs text-zinc-900 dark:text-zinc-100 focus:outline-none focus:ring-2 focus:ring-zinc-900 dark:focus:ring-white appearance-none transition"
                >
                  <option value="">{activeTab === 'income' ? tx("选择收入分类") : tx("选择支出分类")}</option>
                  {visibleCategories.map((cat) => (
                    <option key={cat.id} value={cat.id}>
                      {cat.icon ? `${cat.icon} ` : ''}{categoryLabel(cat.name)}
                    </option>
                  ))}
                </select>
                <ChevronDown className="absolute right-3 top-1/2 -translate-y-1/2 w-4 h-4 text-zinc-400 pointer-events-none" />
              </div>
            </div>
          )}

          {/* 标签（多选，转账不显示） */}
          {activeTab !== 'transfer' && (
            <div>
              <div className="flex items-center justify-between mb-1.5">
                <label className="block text-xs font-semibold text-zinc-700 dark:text-zinc-300">{tx("交易标签 (多选)")}</label>
                <span className="text-[11px] text-zinc-400">{tx("已选")} {selectedTags.length} {tx("个")}</span>
              </div>

              <div className="p-2.5 rounded-xl border border-zinc-200 dark:border-zinc-700 bg-white dark:bg-zinc-800 space-y-2">
                <div className="flex flex-wrap gap-1.5 items-center min-h-[26px]">
                  {selectedTags.map((tg) => (
                    <span
                      key={tg}
                      className="inline-flex items-center gap-1 px-2 py-0.5 rounded-lg text-xs font-medium bg-zinc-100 dark:bg-zinc-700 text-zinc-800 dark:text-zinc-200"
                    >
                      <span>#{tg}</span>
                      <button
                        type="button"
                        onClick={() => setSelectedTags(selectedTags.filter((t) => t !== tg))}
                        className="text-zinc-400 hover:text-zinc-700 dark:hover:text-white cursor-pointer"
                      >
                        ✕
                      </button>
                    </span>
                  ))}
                  <input
                    type="text"
                    data-testid="add-modal-tag-input"
                    value={tagInput}
                    onChange={(e) => setTagInput(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter') {
                        e.preventDefault();
                        const val = tagInput.trim();
                        if (val) {
                          setSelectedTags((prev) => (prev.includes(val) ? prev : [...prev, val]));
                          setTagInput('');
                        }
                      }
                    }}
                    placeholder={tx("+ 回车添加标签")}
                    className="text-xs px-2 py-0.5 w-28 bg-transparent outline-none text-zinc-900 dark:text-white placeholder:text-zinc-400"
                  />
                </div>

                {systemTags.filter((t) => !selectedTags.includes(t.name)).length > 0 && (
                  <div className="pt-2 border-t border-zinc-100 dark:border-zinc-700/60 flex flex-wrap gap-1 items-center">
                    <span className="text-[11px] text-zinc-400">{tx("推荐标签:")}</span>
                    {systemTags
                      .filter((t) => !selectedTags.includes(t.name))
                      .slice(0, 8)
                      .map((t) => (
                        <button
                          key={t.id || t.name}
                          type="button"
                          onClick={() => setSelectedTags((prev) => (prev.includes(t.name) ? prev : [...prev, t.name]))}
                          className="px-1.5 py-0.5 rounded text-[11px] bg-zinc-50 dark:bg-zinc-900 border border-zinc-200 dark:border-zinc-700 text-zinc-600 dark:text-zinc-300 hover:border-zinc-400 cursor-pointer"
                        >
                          +{t.name}
                        </button>
                      ))}
                  </div>
                )}
              </div>
            </div>
          )}

          {/* 报销 / 代垫属性 (公费报销 / 朋友代垫) */}
          {activeTab === 'expense' && (
            <div className="space-y-1.5">
              <label className="block text-xs font-semibold text-zinc-700 dark:text-zinc-300">{tx("报销 / 代垫归属")}</label>
              <div className="grid grid-cols-3 gap-2">
                {[
                  { id: 'none', label: '个人自费', icon: '👤' },
                  { id: 'corporate', label: '公费报销', icon: '🏢' },
                  { id: 'personal_advance', label: '朋友代垫', icon: '👥' },
                ].map((item) => (
                  <button
                    key={item.id}
                    type="button"
                    data-testid={`reimb-type-${item.id}`}
                    aria-pressed={reimbursementType === item.id}
                    onClick={() => setReimbursementType(item.id)}
                    className={`min-w-0 flex flex-col sm:flex-row items-center justify-center gap-1 sm:gap-1.5 py-2 px-2.5 rounded-xl border text-xs font-medium leading-tight transition cursor-pointer ${
                      reimbursementType === item.id
                        ? 'bg-zinc-900 text-white border-transparent dark:bg-blue-950/50 dark:text-blue-200 dark:border-blue-500 shadow-xs font-bold'
                        : 'bg-white dark:bg-zinc-800 border-zinc-200 dark:border-zinc-700 text-zinc-600 dark:text-zinc-300 hover:bg-zinc-50 dark:hover:bg-zinc-700'
                    }`}
                  >
                    <span>{item.icon}</span>
                    <span className="min-w-0 break-words text-center">{tx(item.label)}</span>
                  </button>
                ))}
              </div>

              {reimbursementType !== 'none' && (
                <div className="pt-1.5 space-y-1 animate-in fade-in slide-in-from-top-1 duration-150">
                  <input
                    type="text"
                    data-testid="reimb-counterparty-input"
                    value={counterparty}
                    onChange={(e) => setCounterparty(e.target.value)}
                    placeholder={
                      reimbursementType === 'corporate'
                        ? tx("报销主体（如：公司财务、市场部项目等）")
                        : tx("代垫对象（如：张三、朋友名字）")
                    }
                    className="w-full px-3.5 py-2 rounded-xl border border-zinc-200 dark:border-zinc-700 bg-white dark:bg-zinc-800 text-xs text-zinc-900 dark:text-zinc-100 placeholder-zinc-400 focus:outline-none focus:ring-1 focus:ring-zinc-900"
                  />
                  <p className="text-[11px] text-amber-600 dark:text-amber-400 font-medium">
                    {reimbursementType === 'corporate'
                      ? tx("💡 已自动标记为「待报销」，此笔消费默认不计入家庭净支出")
                      : tx("💡 已自动标记为「待还款」，此笔消费默认不计入家庭净支出")}
                  </p>
                </div>
              )}
            </div>
          )}

          {/* 交易时间（详细日期和时分秒，默认当前时间） */}
          <div className="space-y-1.5">
            <div className="flex items-center justify-between">
              <label className="block text-xs font-semibold text-zinc-700 dark:text-zinc-300">{tx("交易时间")} <span className="text-red-500">*</span>
              </label>
              <button
                type="button"
                data-testid="txn-now-btn"
                onClick={() => {
                  const n = new Date();
                  setForm((prev) => ({
                    ...prev,
                    date: toLocalISODate(n),
                    time: toLocalISOTime(n, true),
                  }));
                }}
                className="text-[11px] font-medium text-zinc-500 hover:text-zinc-900 dark:text-zinc-400 dark:hover:text-white transition cursor-pointer flex items-center gap-1 px-1.5 py-0.5 rounded hover:bg-zinc-100 dark:hover:bg-zinc-800"
                title={tx("重置为当前最新时间")}
              >
                <span>⏱️</span>
                <span>{tx("设为此时此刻")}</span>
              </button>
            </div>

            <div className="grid grid-cols-1 sm:grid-cols-5 gap-2">
              {/* 日期 (占 3 列) */}
              <div className="min-w-0 sm:col-span-3">
                <input
                  type="date"
                  name="date"
                  data-testid="txn-date-input"
                  required
                  value={form.date}
                  onChange={handleChange}
                  className="w-full px-3 py-2.5 rounded-xl border border-zinc-200 dark:border-zinc-700 bg-white dark:bg-zinc-800 text-sm text-zinc-900 dark:text-zinc-100 font-mono focus:outline-none focus:ring-2 focus:ring-zinc-900 dark:focus:ring-white transition"
                />
              </div>

              {/* 时分秒 (占 2 列，step="1" 支持精确到秒) */}
              <div className="min-w-0 sm:col-span-2">
                <input
                  type="time"
                  step="1"
                  name="time"
                  data-testid="txn-time-input"
                  required
                  value={form.time}
                  onChange={handleChange}
                  className="w-full px-3 py-2.5 rounded-xl border border-zinc-200 dark:border-zinc-700 bg-white dark:bg-zinc-800 text-sm text-zinc-900 dark:text-zinc-100 font-mono focus:outline-none focus:ring-2 focus:ring-zinc-900 dark:focus:ring-white transition"
                />
              </div>
            </div>

            {/* 详细时间提示（显示精确日期与时分秒） */}
            <div className="flex flex-col gap-1 sm:flex-row sm:items-center sm:justify-between text-[11px] text-zinc-400 dark:text-zinc-500 px-0.5">
              <span className="min-w-0 break-words font-mono" data-testid="txn-datetime-display">{tx("详细时间：")} {form.date} {form.time}
              </span>
              <span>{tx("(支持修改时分秒)")}</span>
            </div>
          </div>

          {/* 详情（折叠区域） */}
          <div className="border border-zinc-100 dark:border-zinc-800 rounded-xl overflow-hidden">
            <button
              type="button"
              onClick={() => setShowDetails((v) => !v)}
              className="w-full flex items-center justify-between px-4 py-3 text-sm font-medium text-zinc-700 dark:text-zinc-300 hover:bg-zinc-50 dark:hover:bg-zinc-800/50 transition-colors"
            >
              <span>{tx("详情 (备注等)")}</span>
              <ChevronDown className={`w-4 h-4 text-zinc-400 transition-transform ${showDetails ? 'rotate-180' : ''}`} />
            </button>
            {showDetails && (
              <div className="px-4 pb-4 pt-1 border-t border-zinc-100 dark:border-zinc-800 space-y-3">
                {/* 备注 */}
                <div>
                  <label className="block text-xs font-semibold text-zinc-700 dark:text-zinc-300 mb-1.5">{tx("备注")}</label>
                  <textarea
                    name="notes"
                    value={form.notes}
                    onChange={handleChange}
                    placeholder={tx("添加备注...")}
                    rows={2}
                    className="w-full px-3.5 py-2.5 rounded-xl border border-zinc-200 dark:border-zinc-700 bg-white dark:bg-zinc-800 text-sm text-zinc-900 dark:text-zinc-100 placeholder-zinc-400 focus:outline-none focus:ring-2 focus:ring-zinc-900 dark:focus:ring-white transition resize-none"
                  />
                </div>
              </div>
            )}
          </div>
        </form>

        {/* ── 提交按钮 (固定不被挤压) ── */}
        <div className="shrink-0 px-5 pb-[max(1.25rem,env(safe-area-inset-bottom))] pt-3 border-t border-zinc-100 dark:border-zinc-800">
          <button
            type="submit"
            form="add-transaction-form"
            onClick={handleSubmit}
            disabled={submitting}
            className={`w-full py-3.5 rounded-xl text-sm font-bold tracking-wide transition-all shadow-sm active:scale-[0.98] disabled:opacity-60 disabled:cursor-not-allowed ${
              isCurrentAccountReadOnly
                ? 'bg-amber-600 hover:bg-amber-700 text-white'
                : 'bg-zinc-900 text-white hover:bg-zinc-800 dark:bg-blue-600 dark:hover:bg-blue-700'
            }`}
          >
            {submitting ? (
              <span className="flex items-center justify-center gap-2">
                <span className="w-4 h-4 border-2 border-current border-t-transparent rounded-full animate-spin" /> {tx("正在提交...")}</span>
            ) : isCurrentAccountReadOnly ? (
              tx("⚠️ 所选账户仅有只读权限 (无法添加)")
            ) : (
              tx("添加交易")
            )}
          </button>
        </div>
      </div>
    </div>
  );

  return createPortal(modalContent, document.body);
}
