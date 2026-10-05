import { categoryLabel, tx, useLocale } from "../localization.js";
import React, { useState, useEffect, useMemo } from 'react';
import { RotateCcw, Calendar, Layers, Tag, Clock, Hash, LayoutGrid, Bookmark, Store, Search } from 'lucide-react';
import { useAuth } from '../auth/AuthContext';
import CalendarDateInput from './CalendarDateInput';

const parseCommaList = (val) => {
  if (!val) return [];
  if (Array.isArray(val)) return val;
  return String(val)
    .split(',')
    .map((s) => s.trim())
    .filter(Boolean);
};

const initialDraft = (filters = {}) => ({
  account_ids: parseCommaList(filters?.account_id),
  account_masks: parseCommaList(filters?.account_mask),
  institution_names: parseCommaList(filters?.institution_name),
  transaction_types: parseCommaList(filters?.transaction_type),
  category_names: parseCommaList(filters?.category_name),
  is_refund: Boolean(filters?.is_refund),
  has_refund: Boolean(filters?.has_refund),
  refund_state:
    filters?.refund_state ||
    (filters?.is_refund ? 'unmatched' : filters?.has_refund ? 'matched' : 'all'),
  statuses: parseCommaList(filters?.status),
  tags: parseCommaList(filters?.tag),
  merchants: parseCommaList(filters?.merchant),
  amount_operator: filters?.amount_operator || 'equal',
  amount: filters?.amount || '',
  min_amount: filters?.min_amount || '',
  max_amount: filters?.max_amount || '',
  start_date: filters?.start_date || '',
  end_date: filters?.end_date || '',
});

export default function TransactionFilterModal({
  isOpen,
  onClose,
  currentFilters = {},
  onApply,
  onReset,
  accounts = [],
  filterOptions = null,
}) {
  useLocale();
  const { user: currentUser } = useAuth();
  const [activeTab, setActiveTab] = useState('account');
  const [searchQuery, setSearchQuery] = useState('');

  // Draft filters state supporting multi-selection
  const [draft, setDraft] = useState(() => initialDraft(currentFilters));

  useEffect(() => {
    if (isOpen) {
      setDraft(initialDraft(currentFilters));
      setSearchQuery('');
    }
  }, [isOpen, currentFilters]);

  // Tab definitions matching Sure layout with active badge counts
  const tabs = [
    { id: 'account', label: '账户', icon: Layers, count: draft.account_ids.length },
    { id: 'date', label: '日期', icon: Calendar, count: draft.start_date || draft.end_date ? 1 : 0 },
    { id: 'type', label: '类型', icon: Tag, count: draft.transaction_types.length },
    { id: 'refund', label: '退款', icon: RotateCcw, count: draft.refund_state !== 'all' ? 1 : 0 },
    { id: 'status', label: '状态', icon: Clock, count: draft.statuses.length },
    { id: 'amount', label: '金额', icon: Hash, count: draft.amount ? 1 : 0 },
    { id: 'category', label: '分类', icon: LayoutGrid, count: draft.category_names.length },
    { id: 'tag', label: '标签', icon: Bookmark, count: draft.tags.length },
    { id: 'merchant', label: '商户', icon: Store, count: draft.merchants.length },
  ];

  const categories = filterOptions?.categories || [
    { name: '餐饮美食', icon: '🍴' },
    { name: '超市便利', icon: '🛒' },
    { name: '生活缴费', icon: '⚡' },
    { name: '交通出行', icon: '🚗' },
    { name: '购物消费', icon: '🛍️' },
    { name: '个人/转账', icon: '👤' },
    { name: '其他', icon: '🍪' },
  ];

  const availableTags = filterOptions?.tags || ['日常', '必要', '餐饮', '固定支出', '报销', '娱乐'];
  const availableMerchants = filterOptions?.merchants || [
    '杭州鑫牛餐饮管理有限公司',
    '优联服务',
    '赵自宽',
    '饿了么',
    '京东商城',
    '物美超市',
  ];

  // Accounts list from options or props, with user-aware badge
  const accountsList = useMemo(() => {
    const list = filterOptions?.accounts?.length ? filterOptions.accounts : accounts;
    return list.map((a) => {
      const mask = a.mask || (a.name.match(/\d{4}/) ? a.name.match(/\d{4}/)[0] : a.name.slice(-4));
      let badge = a.badge;
      if (!badge) {
        const isMine =
          a.is_mine ||
          (currentUser &&
            (a.owner_id === currentUser.id ||
              a.owner === currentUser.username ||
              a.owner === currentUser.display_name));
        if (isMine) {
          badge = a.is_shared ? '我的 · 已共享' : '我的';
        } else {
          badge = a.owner ? `${a.owner}共享给我` : '我的';
        }
      }
      return { ...a, mask, badge };
    });
  }, [filterOptions, accounts, currentUser]);

  // Filtered accounts based on search
  const filteredAccounts = useMemo(() => {
    if (!searchQuery) return accountsList;
    const q = searchQuery.toLowerCase();
    return accountsList.filter(
      (a) =>
        a.name.toLowerCase().includes(q) ||
        a.mask.includes(q) ||
        (a.institution_name && a.institution_name.toLowerCase().includes(q))
    );
  }, [accountsList, searchQuery]);

  // Date preset helper
  const applyDatePreset = (preset) => {
    const today = new Date();
    const yyyy = today.getFullYear();
    const mm = String(today.getMonth() + 1).padStart(2, '0');
    const dd = String(today.getDate()).padStart(2, '0');
    const todayStr = `${yyyy}-${mm}-${dd}`;

    if (preset === 'MTD') {
      setDraft((p) => ({ ...p, start_date: `${yyyy}-${mm}-01`, end_date: todayStr }));
    } else if (preset === '30D') {
      const d = new Date(today);
      d.setDate(d.getDate() - 30);
      setDraft((p) => ({ ...p, start_date: d.toISOString().slice(0, 10), end_date: todayStr }));
    } else if (preset === 'YTD') {
      setDraft((p) => ({ ...p, start_date: `${yyyy}-01-01`, end_date: todayStr }));
    } else if (preset === 'ALL') {
      setDraft((p) => ({ ...p, start_date: '', end_date: '' }));
    }
  };

  const handleApply = () => {
    const result = {
      account_id: draft.account_ids.join(','),
      account_mask: draft.account_masks.join(','),
      institution_name: draft.institution_names.join(','),
      transaction_type: draft.transaction_types.join(','),
      category_name: draft.category_names.join(','),
      status: draft.statuses.join(','),
      tag: draft.tags.join(','),
      merchant: draft.merchants.join(','),
      refund_state: draft.refund_state,
      amount_operator: draft.amount_operator,
      amount: draft.amount,
      min_amount: draft.min_amount,
      max_amount: draft.max_amount,
      start_date: draft.start_date,
      end_date: draft.end_date,
    };

    if (result.refund_state === 'unmatched') {
      result.is_refund = true;
      result.has_refund = false;
    } else if (result.refund_state === 'matched') {
      result.is_refund = false;
      result.has_refund = true;
    } else {
      result.is_refund = false;
      result.has_refund = false;
    }

    if (result.amount_operator && result.amount) {
      const amt = parseFloat(result.amount);
      if (!isNaN(amt)) {
        if (result.amount_operator === 'greater') {
          result.min_amount = amt;
          result.max_amount = '';
        } else if (result.amount_operator === 'less') {
          result.min_amount = '';
          result.max_amount = amt;
        } else {
          result.min_amount = amt;
          result.max_amount = amt;
        }
      }
    }

    onApply(result);
    onClose();
  };

  const handleReset = () => {
    setDraft(initialDraft({}));
    onReset();
    onClose();
  };

  const hasAnyFilter = Boolean(
    draft.account_ids.length > 0 ||
      draft.account_masks.length > 0 ||
      draft.institution_names.length > 0 ||
      draft.transaction_types.length > 0 ||
      draft.category_names.length > 0 ||
      draft.refund_state !== 'all' ||
      draft.statuses.length > 0 ||
      draft.tags.length > 0 ||
      draft.merchants.length > 0 ||
      draft.amount ||
      draft.start_date ||
      draft.end_date
  );

  if (!isOpen) return null;

  return (
    <div role="dialog" aria-modal="true" className="fixed inset-0 z-50 flex items-center justify-center p-3 sm:p-4 bg-black/50 backdrop-blur-xs animate-in fade-in duration-150">
      <div className="relative w-full max-w-xl bg-white dark:bg-zinc-900 rounded-2xl shadow-2xl border border-zinc-200 dark:border-zinc-800 flex flex-col h-[520px] max-h-[90vh] overflow-hidden">
        {/* Main 2-Column Layout */}
        <div className="flex flex-1 overflow-hidden">
          {/* Left Column: Category Tabs (w-44) */}
          <div className="w-40 sm:w-44 shrink-0 flex flex-col p-2 border-r border-zinc-200 dark:border-zinc-800 bg-zinc-50/50 dark:bg-zinc-900/50 space-y-1 overflow-y-auto">
            {tabs.map((tab) => {
              const Icon = tab.icon;
              const isActive = activeTab === tab.id;
              return (
                <button
                  key={tab.id}
                  data-testid={`filter-tab-${tab.id}`}
                  type="button"
                  onClick={() => {
                    setActiveTab(tab.id);
                    setSearchQuery('');
                  }}
                  className={`w-full px-3 py-2.5 flex items-center justify-between rounded-xl text-sm font-medium transition-colors text-left ${
                    isActive
                      ? 'bg-zinc-200/70 dark:bg-zinc-800 text-zinc-900 dark:text-white shadow-2xs font-semibold'
                      : 'text-zinc-600 dark:text-zinc-400 hover:bg-zinc-100 dark:hover:bg-zinc-800/50 hover:text-zinc-900 dark:hover:text-zinc-200'
                  }`}
                >
                  <div className="flex items-center gap-2.5 min-w-0">
                    <Icon className="w-4 h-4 shrink-0" />
                    <span className="truncate">{tx(tab.label)}</span>
                  </div>
                  {tab.count > 0 && (
                    <span className="ml-1.5 px-1.5 py-0.2 rounded-full text-xs font-semibold bg-zinc-900 text-white dark:bg-zinc-100 dark:text-zinc-900 shrink-0">
                      {tab.count}
                    </span>
                  )}
                </button>
              );
            })}
          </div>

          {/* Right Column: Tab Panels */}
          <div className="flex-1 flex flex-col overflow-hidden bg-white dark:bg-zinc-900">
            <div className="flex-1 p-4 overflow-y-auto space-y-4">
              {/* 1. Account Filter (Multi-select) */}
              {activeTab === 'account' && (
                <div className="space-y-3">
                  <div className="relative">
                    <Search className="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2 text-zinc-400" />
                    <input
                      type="text"
                      placeholder={tx("筛选账户")}
                      value={searchQuery}
                      onChange={(e) => setSearchQuery(e.target.value)}
                      className="w-full pl-9 pr-3 py-2 text-sm border border-zinc-200 dark:border-zinc-700 rounded-lg bg-zinc-50/50 dark:bg-zinc-800/50 text-zinc-900 dark:text-zinc-100 placeholder:text-zinc-400 focus:outline-none focus:ring-2 focus:ring-zinc-900 dark:focus:ring-zinc-400"
                    />
                  </div>

                  <div className="space-y-1">
                    <div
                      data-testid="filter-opt-account-all"
                      onClick={() =>
                        setDraft((p) => ({ ...p, account_ids: [], account_masks: [] }))
                      }
                      className="flex items-center gap-2.5 p-2 rounded-lg hover:bg-zinc-50 dark:hover:bg-zinc-800 cursor-pointer text-sm select-none"
                    >
                      <input
                        type="checkbox"
                        checked={
                          draft.account_ids.length === 0 && draft.account_masks.length === 0
                        }
                        readOnly
                        className="rounded border-zinc-300 text-zinc-900 focus:ring-zinc-900 pointer-events-none"
                      />
                      <span className="font-medium text-zinc-900 dark:text-zinc-100">{tx("全部账户")}</span>
                    </div>

                    {filteredAccounts.map((acc) => {
                      const isChecked = draft.account_ids.includes(acc.id);
                      return (
                        <div
                          key={acc.id}
                          data-testid={`filter-opt-account-${acc.id}`}
                          onClick={() =>
                            setDraft((p) => {
                              const exists = p.account_ids.includes(acc.id);
                              const nextIds = exists
                                ? p.account_ids.filter((id) => id !== acc.id)
                                : [...p.account_ids, acc.id];
                              return {
                                ...p,
                                account_ids: nextIds,
                              };
                            })
                          }
                          className="flex items-center justify-between p-2 rounded-lg hover:bg-zinc-50 dark:hover:bg-zinc-800 cursor-pointer text-sm select-none"
                        >
                          <div className="flex items-center gap-2.5 min-w-0 flex-1">
                            <input
                              type="checkbox"
                              checked={isChecked}
                              readOnly
                              className="rounded border-zinc-300 text-zinc-900 focus:ring-zinc-900 pointer-events-none shrink-0"
                            />
                            <span title={acc.name} className="text-sm font-medium text-zinc-800 dark:text-zinc-200 min-w-0 break-words">
                              {acc.name}
                            </span>
                          </div>
                          <span className="text-xs text-zinc-400 dark:text-zinc-500 shrink-0 ml-2">
                            {acc.badge}
                          </span>
                        </div>
                      );
                    })}
                  </div>
                </div>
              )}

              {/* 2. Date Filter */}
              {activeTab === 'date' && (
                <div className="space-y-4">
                  <div className="grid grid-cols-2 gap-2">
                    {[
                      { key: 'ALL', label: '全部' },
                      { key: 'MTD', label: '本月' },
                      { key: '30D', label: '过去 30 天' },
                      { key: 'YTD', label: '今年' },
                    ].map((preset) => (
                      <button
                        key={preset.key}
                        type="button"
                        onClick={() => applyDatePreset(preset.key)}
                        className="p-2.5 rounded-xl border border-zinc-200 dark:border-zinc-700 text-sm font-medium hover:bg-zinc-50 dark:hover:bg-zinc-800 text-zinc-800 dark:text-zinc-200"
                      >
                        {tx(preset.label)}
                      </button>
                    ))}
                  </div>

                  <div className="space-y-2 pt-2">
                    <span className="text-xs font-semibold text-zinc-400 uppercase">{tx("自定义时间")}</span>
                    <div className="space-y-2">
                      <div>
                        <span className="text-xs text-zinc-500 mb-1 block">{tx("起始日期")}</span>
                        <CalendarDateInput
                          label="起始日期"
                          data-testid="filter-start-date"
                          value={draft.start_date}
                          onChange={(e) =>
                            setDraft((p) => ({ ...p, start_date: e.target.value }))
                          }
                          className="w-full px-3 py-2 text-sm border border-zinc-200 dark:border-zinc-700 rounded-lg bg-zinc-50 dark:bg-zinc-800 text-zinc-900 dark:text-zinc-100"
                        />
                      </div>
                      <div>
                        <span className="text-xs text-zinc-500 mb-1 block">{tx("结束日期")}</span>
                        <CalendarDateInput
                          label="结束日期"
                          data-testid="filter-end-date"
                          value={draft.end_date}
                          onChange={(e) =>
                            setDraft((p) => ({ ...p, end_date: e.target.value }))
                          }
                          className="w-full px-3 py-2 text-sm border border-zinc-200 dark:border-zinc-700 rounded-lg bg-zinc-50 dark:bg-zinc-800 text-zinc-900 dark:text-zinc-100"
                        />
                      </div>
                    </div>
                  </div>
                </div>
              )}

              {/* 3. Type Filter (Multi-select) */}
              {activeTab === 'type' && (
                <div className="space-y-2">
                  <div
                    data-testid="filter-opt-type-all"
                    onClick={() => setDraft((p) => ({ ...p, transaction_types: [] }))}
                    className="flex items-center gap-3 p-2.5 rounded-lg hover:bg-zinc-50 dark:hover:bg-zinc-800 cursor-pointer text-sm select-none"
                  >
                    <input
                      type="checkbox"
                      checked={draft.transaction_types.length === 0}
                      readOnly
                      className="rounded border-zinc-300 text-zinc-900 focus:ring-zinc-900 pointer-events-none"
                    />
                    <span className="text-zinc-900 dark:text-zinc-100 font-medium">{tx("全部类型")}</span>
                  </div>

                  {[
                    { value: 'expense', label: '支出' },
                    { value: 'income', label: '收入' },
                    { value: 'transfer', label: '内部转账 / 还贷' },
                    { value: 'adjustment', label: '对账调整' },
                  ].map((item) => {
                    const isChecked = draft.transaction_types.includes(item.value);
                    return (
                      <div
                        key={item.value}
                        data-testid={`filter-opt-type-${item.value}`}
                        onClick={() =>
                          setDraft((p) => {
                            const exists = p.transaction_types.includes(item.value);
                            const nextTypes = exists
                              ? p.transaction_types.filter((t) => t !== item.value)
                              : [...p.transaction_types, item.value];
                            return {
                              ...p,
                              transaction_types: nextTypes,
                            };
                          })
                        }
                        className="flex items-center gap-3 p-2.5 rounded-lg hover:bg-zinc-50 dark:hover:bg-zinc-800 cursor-pointer text-sm select-none"
                      >
                        <input
                          type="checkbox"
                          checked={isChecked}
                          readOnly
                          className="rounded border-zinc-300 text-zinc-900 focus:ring-zinc-900 pointer-events-none"
                        />
                        <span className="text-zinc-900 dark:text-zinc-100 font-medium">
                          {tx(item.label)}
                        </span>
                      </div>
                    );
                  })}
                </div>
              )}

              {/* 4. Refund Filter */}
              {activeTab === 'refund' && (
                <div className="space-y-2">
                  {[
                    { value: 'all', label: '全部' },
                    { value: 'unmatched', label: '未匹配退款' },
                    { value: 'matched', label: '已匹配冲抵退款' },
                  ].map((item) => {
                    const isChecked = draft.refund_state === item.value;
                    return (
                      <label
                        key={item.value}
                        onClick={() => setDraft((p) => ({ ...p, refund_state: item.value }))}
                        className="flex items-center gap-3 p-2.5 rounded-lg hover:bg-zinc-50 dark:hover:bg-zinc-800 cursor-pointer text-sm"
                      >
                        <input
                          type="radio"
                          name="refund_state"
                          checked={isChecked}
                          onChange={() => {}}
                          className="text-zinc-900 focus:ring-zinc-900"
                        />
                        <span className="text-zinc-900 dark:text-zinc-100 font-medium">
                          {tx(item.label)}
                        </span>
                      </label>
                    );
                  })}
                </div>
              )}

              {/* 5. Status Filter (Multi-select) */}
              {activeTab === 'status' && (
                <div className="space-y-2">
                  <div
                    onClick={() => setDraft((p) => ({ ...p, statuses: [] }))}
                    className="flex items-center gap-3 p-2.5 rounded-lg hover:bg-zinc-50 dark:hover:bg-zinc-800 cursor-pointer text-sm select-none"
                  >
                    <input
                      type="checkbox"
                      checked={draft.statuses.length === 0}
                      readOnly
                      className="rounded border-zinc-300 text-zinc-900 focus:ring-zinc-900 pointer-events-none"
                    />
                    <span className="text-zinc-900 dark:text-zinc-100 font-medium">{tx("全部状态")}</span>
                  </div>

                  {[
                    { value: 'cleared', label: '已清算' },
                    { value: 'pending', label: '待入账' },
                  ].map((item) => {
                    const isChecked = draft.statuses.includes(item.value);
                    return (
                      <div
                        key={item.value}
                        onClick={() =>
                          setDraft((p) => {
                            const exists = p.statuses.includes(item.value);
                            const nextStatuses = exists
                              ? p.statuses.filter((s) => s !== item.value)
                              : [...p.statuses, item.value];
                            return {
                              ...p,
                              statuses: nextStatuses,
                            };
                          })
                        }
                        className="flex items-center gap-3 p-2.5 rounded-lg hover:bg-zinc-50 dark:hover:bg-zinc-800 cursor-pointer text-sm select-none"
                      >
                        <input
                          type="checkbox"
                          checked={isChecked}
                          readOnly
                          className="rounded border-zinc-300 text-zinc-900 focus:ring-zinc-900 pointer-events-none"
                        />
                        <span className="text-zinc-900 dark:text-zinc-100 font-medium">
                          {tx(item.label)}
                        </span>
                      </div>
                    );
                  })}
                </div>
              )}

              {/* 6. Amount Filter */}
              {activeTab === 'amount' && (
                <div className="space-y-3">
                  <div>
                    <label className="text-xs text-zinc-500 mb-1 block">{tx("运算符")}</label>
                    <select
                      value={draft.amount_operator}
                      onChange={(e) =>
                        setDraft((p) => ({ ...p, amount_operator: e.target.value }))
                      }
                      className="w-full px-3 py-2 text-xs border border-zinc-200 dark:border-zinc-700 rounded-lg bg-zinc-50 dark:bg-zinc-800 text-zinc-900 dark:text-zinc-100"
                    >
                      <option value="equal">{tx("等于")}</option>
                      <option value="greater">{tx("大于")}</option>
                      <option value="less">{tx("小于")}</option>
                    </select>
                  </div>

                  <div>
                    <label className="text-xs text-zinc-500 mb-1 block">{tx("金额数值 (¥)")}</label>
                    <input
                      type="number"
                      step="0.01"
                      placeholder="0.00"
                      value={draft.amount}
                      onChange={(e) => setDraft((p) => ({ ...p, amount: e.target.value }))}
                      className="w-full px-3 py-2 text-xs border border-zinc-200 dark:border-zinc-700 rounded-lg bg-zinc-50 dark:bg-zinc-800 text-zinc-900 dark:text-zinc-100"
                    />
                  </div>
                </div>
              )}

              {/* 7. Category Filter (Multi-select) */}
              {activeTab === 'category' && (
                <div className="space-y-3">
                  <div className="relative">
                    <Search className="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2 text-zinc-400" />
                    <input
                      type="text"
                      placeholder={tx("筛选分类")}
                      value={searchQuery}
                      onChange={(e) => setSearchQuery(e.target.value)}
                      className="w-full pl-9 pr-3 py-2 text-sm border border-zinc-200 dark:border-zinc-700 rounded-lg bg-zinc-50/50 dark:bg-zinc-800/50 text-zinc-900 dark:text-zinc-100 placeholder:text-zinc-400 focus:outline-none focus:ring-2 focus:ring-zinc-900 dark:focus:ring-zinc-400"
                    />
                  </div>

                  <div className="space-y-1">
                    <div
                      onClick={() => setDraft((p) => ({ ...p, category_names: [] }))}
                      className="flex items-center gap-2.5 p-2 rounded-lg hover:bg-zinc-50 dark:hover:bg-zinc-800 cursor-pointer text-sm select-none"
                    >
                      <input
                        type="checkbox"
                        checked={draft.category_names.length === 0}
                        readOnly
                        className="rounded border-zinc-300 text-zinc-900 focus:ring-zinc-900 pointer-events-none"
                      />
                      <span className="font-medium text-zinc-900 dark:text-zinc-100">{tx("全部分类")}</span>
                    </div>

                    {categories
                      .filter(
                        (c) =>
                          !searchQuery ||
                          c.name.toLowerCase().includes(searchQuery.toLowerCase())
                      )
                      .map((cat) => {
                        const isChecked = draft.category_names.includes(cat.name);
                        return (
                          <div
                            key={cat.id || cat.name}
                            onClick={() =>
                              setDraft((p) => {
                                const exists = p.category_names.includes(cat.name);
                                const nextCats = exists
                                  ? p.category_names.filter((c) => c !== cat.name)
                                  : [...p.category_names, cat.name];
                                return {
                                  ...p,
                                  category_names: nextCats,
                                };
                              })
                            }
                            className="flex items-center gap-2.5 p-2 rounded-lg hover:bg-zinc-50 dark:hover:bg-zinc-800 cursor-pointer text-sm select-none"
                          >
                            <input
                              type="checkbox"
                              checked={isChecked}
                              readOnly
                              className="rounded border-zinc-300 text-zinc-900 focus:ring-zinc-900 pointer-events-none"
                            />
                            <span>{cat.icon}</span>
                            <span className="font-medium text-zinc-800 dark:text-zinc-200">
                              {categoryLabel(cat.name)}
                            </span>
                          </div>
                        );
                      })}
                  </div>
                </div>
              )}

              {/* 8. Tag Filter (Multi-select) */}
              {activeTab === 'tag' && (
                <div className="space-y-3">
                  <div className="relative">
                    <Search className="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2 text-zinc-400" />
                    <input
                      type="text"
                      placeholder={tx("筛选标签")}
                      value={searchQuery}
                      onChange={(e) => setSearchQuery(e.target.value)}
                      className="w-full pl-9 pr-3 py-2 text-sm border border-zinc-200 dark:border-zinc-700 rounded-lg bg-zinc-50/50 dark:bg-zinc-800/50 text-zinc-900 dark:text-zinc-100 placeholder:text-zinc-400 focus:outline-none focus:ring-2 focus:ring-zinc-900 dark:focus:ring-zinc-400"
                    />
                  </div>

                  <div className="space-y-1">
                    <div
                      onClick={() => setDraft((p) => ({ ...p, tags: [] }))}
                      className="flex items-center gap-2.5 p-2 rounded-lg hover:bg-zinc-50 dark:hover:bg-zinc-800 cursor-pointer text-sm select-none"
                    >
                      <input
                        type="checkbox"
                        checked={draft.tags.length === 0}
                        readOnly
                        className="rounded border-zinc-300 text-zinc-900 focus:ring-zinc-900 pointer-events-none"
                      />
                      <span className="font-medium text-zinc-900 dark:text-zinc-100">{tx("全部标签")}</span>
                    </div>

                    {availableTags
                      .filter(
                        (t) =>
                          !searchQuery || t.toLowerCase().includes(searchQuery.toLowerCase())
                      )
                      .map((t) => {
                        const isChecked = draft.tags.includes(t);
                        return (
                          <div
                            key={t}
                            onClick={() =>
                              setDraft((p) => {
                                const exists = p.tags.includes(t);
                                const nextTags = exists
                                  ? p.tags.filter((tag) => tag !== t)
                                  : [...p.tags, t];
                                return {
                                  ...p,
                                  tags: nextTags,
                                };
                              })
                            }
                            className="flex items-center gap-2.5 p-2 rounded-lg hover:bg-zinc-50 dark:hover:bg-zinc-800 cursor-pointer text-sm select-none"
                          >
                            <input
                              type="checkbox"
                              checked={isChecked}
                              readOnly
                              className="rounded border-zinc-300 text-zinc-900 focus:ring-zinc-900 pointer-events-none"
                            />
                            <span className="font-medium text-zinc-800 dark:text-zinc-200">
                              #{t}
                            </span>
                          </div>
                        );
                      })}
                  </div>
                </div>
              )}

              {/* 9. Merchant Filter (Multi-select) */}
              {activeTab === 'merchant' && (
                <div className="space-y-3">
                  <div className="relative">
                    <Search className="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2 text-zinc-400" />
                    <input
                      type="text"
                      placeholder={tx("筛选商户")}
                      value={searchQuery}
                      onChange={(e) => setSearchQuery(e.target.value)}
                      className="w-full pl-9 pr-3 py-2 text-sm border border-zinc-200 dark:border-zinc-700 rounded-lg bg-zinc-50/50 dark:bg-zinc-800/50 text-zinc-900 dark:text-zinc-100 placeholder:text-zinc-400 focus:outline-none focus:ring-2 focus:ring-zinc-900 dark:focus:ring-zinc-400"
                    />
                  </div>

                  <div className="space-y-1">
                    <div
                      onClick={() => setDraft((p) => ({ ...p, merchants: [] }))}
                      className="flex items-center gap-2.5 p-2 rounded-lg hover:bg-zinc-50 dark:hover:bg-zinc-800 cursor-pointer text-sm select-none"
                    >
                      <input
                        type="checkbox"
                        checked={draft.merchants.length === 0}
                        readOnly
                        className="rounded border-zinc-300 text-zinc-900 focus:ring-zinc-900 pointer-events-none"
                      />
                      <span className="font-medium text-zinc-900 dark:text-zinc-100">{tx("全部商户")}</span>
                    </div>

                    {availableMerchants
                      .filter(
                        (m) =>
                          !searchQuery || m.toLowerCase().includes(searchQuery.toLowerCase())
                      )
                      .map((m) => {
                        const isChecked = draft.merchants.includes(m);
                        return (
                          <div
                            key={m}
                            onClick={() =>
                              setDraft((p) => {
                                const exists = p.merchants.includes(m);
                                const nextMerchants = exists
                                  ? p.merchants.filter((mer) => mer !== m)
                                  : [...p.merchants, m];
                                return {
                                  ...p,
                                  merchants: nextMerchants,
                                };
                              })
                            }
                            className="flex items-center gap-2.5 p-2 rounded-lg hover:bg-zinc-50 dark:hover:bg-zinc-800 cursor-pointer text-sm select-none"
                          >
                            <input
                              type="checkbox"
                              checked={isChecked}
                              readOnly
                              className="rounded border-zinc-300 text-zinc-900 focus:ring-zinc-900 pointer-events-none"
                            />
                            <span className="font-medium text-zinc-800 dark:text-zinc-200 truncate">
                              {m}
                            </span>
                          </div>
                        );
                      })}
                  </div>
                </div>
              )}
            </div>

            {/* Bottom Footer */}
            <div className="flex justify-between items-center p-3 border-t border-zinc-200 dark:border-zinc-800 bg-zinc-50 dark:bg-zinc-900/90 shrink-0">
              <div>
                {hasAnyFilter && (
                  <button
                    type="button"
                    data-testid="filter-modal-reset-btn"
                    onClick={handleReset}
                    className="text-xs text-zinc-500 hover:text-zinc-800 dark:hover:text-zinc-200 font-medium cursor-pointer"
                  >{tx("清除所有筛选")}</button>
                )}
              </div>

              <div className="flex items-center gap-2">
                <button
                  type="button"
                  data-testid="filter-modal-cancel-btn"
                  onClick={onClose}
                  className="px-3.5 py-1.5 rounded-lg text-sm font-medium text-zinc-600 dark:text-zinc-400 hover:bg-zinc-200/50 dark:hover:bg-zinc-800 transition-colors cursor-pointer"
                >{tx("取消")}</button>
                <button
                  type="button"
                  data-testid="filter-modal-apply-btn"
                  onClick={handleApply}
                  className="px-4 py-1.5 rounded-lg text-sm font-medium bg-zinc-900 hover:bg-black text-white dark:bg-white dark:hover:bg-zinc-100 dark:text-zinc-900 shadow-xs transition-colors cursor-pointer"
                >{tx("应用")}</button>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
