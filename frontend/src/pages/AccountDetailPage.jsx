import { chartMoney } from '../utils/chartMoney';
import { categoryLabel, dateLabel, tx, useLocale, currentLocale } from "../localization.js";
import React, { useState, useEffect, useMemo, useRef } from 'react';
import { useParams, useNavigate, Link } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { MoreHorizontal, ChevronDown, Plus, Search, SlidersHorizontal, ArrowRightLeft, ChevronRight, RotateCcw, Users } from 'lucide-react';
import { useAuth } from '../auth/AuthContext';
import { fetchWithAuth } from '../api/fetchWithAuth';
import { useCurrency } from '../CurrencyContext';
import { useToast } from '../ToastContext';
import NewBalanceModal from '../components/NewBalanceModal';
import AddTransactionModal from '../components/AddTransactionModal';
import AccountSharingModal from '../components/AccountSharingModal';
import {
  EditAccountModal,
  TransferOwnershipModal,
  DeleteAccountModal,
  ImportTransactionsModal,
} from '../components/AccountModals';
import TransactionDrawer from '../components/TransactionDrawer';
import useTransactionDrawer from '../hooks/useTransactionDrawer';
import TransactionAmount from '../components/TransactionAmount';
import BookingMoneyInfo from '../components/BookingMoneyInfo';
import { totalsByCurrency, formatCurrencyTotals } from '../utils/currency';
import ReimbursementBadge from '../components/ReimbursementBadge';
import ScheduledPlans from '../components/ScheduledPlans';
import { formatDateTime } from '../utils/dates';
import { getAccountTypeConfig, getTransactionInitialBadge } from '../utils/accountIcons';

export default function AccountDetailPage() {
  useLocale();
  const { id } = useParams();
  const navigate = useNavigate();
  const { t } = useTranslation();
  const { fmt, privacyMode } = useCurrency();
  const { showToast } = useToast();
  const { user } = useAuth();

  const [loading, setLoading] = useState(true);
  const [data, setData] = useState(null);
  const [transactions, setTransactions] = useState([]);
  const [period, setPeriod] = useState('MTD'); // MTD | 1M | 3M | 6M | YTD | ALL
  const [periodDropdownOpen, setPeriodDropdownOpen] = useState(false);
  const [activeTab, setActiveTab] = useState(() => new URLSearchParams(window.location.search).get('tab') === 'plans' ? 'plans' : 'activity');
  const [searchQuery, setSearchQuery] = useState('');

  // Dropdowns
  const [showAccountMenu, setShowAccountMenu] = useState(false);
  const [showCreateMenu, setShowCreateMenu] = useState(false);

  // Modals
  const [showNewBalanceModal, setShowNewBalanceModal] = useState(false);
  const [showAddTxnModal, setShowAddTxnModal] = useState(false);
  const [defaultTxnType, setDefaultTxnType] = useState('expense');
  const [editingAccount, setEditingAccount] = useState(null);
  const [sharingAccountId, setSharingAccountId] = useState(null);
  const [transferringAccount, setTransferringAccount] = useState(null);
  const [deletingAccount, setDeletingAccount] = useState(null);
  const [importingAccount, setImportingAccount] = useState(null);
  const [selectedTxnId, setSelectedTxnId] = useTransactionDrawer();
  const loadVersion = useRef(0);

  // Load account detail and trend chart
  const loadAccountData = async (quiet = false) => {
    const version = ++loadVersion.current;
    try {
      if (!quiet) setLoading(true);
      const res = await fetchWithAuth(`/api/v1/accounts/${id}?period=${period}`);
      if (res.ok) {
        const json = await res.json();
        if (version !== loadVersion.current) return;
        setData(json);
      } else {
        if (version !== loadVersion.current) return;
        const error = await res.json().catch(() => ({}));
        showToast(tx(typeof error.detail === 'string' ? error.detail : '加载账户信息失败'), 'error');
      }

      // Load transactions for this account
      const txRes = await fetchWithAuth(`/api/v1/transactions?account_id=${id}&limit=50`);
      if (txRes.ok) {
        const txJson = await txRes.json();
        if (version !== loadVersion.current) return;
        setTransactions((txJson.items || txJson.transactions || []).map(txn =>
          txn.master_account_id === id && txn.master_settlement_amount != null ? {
            ...txn, child_book_amount: txn.amount, child_book_currency: txn.currency,
            amount: txn.master_settlement_amount, currency: txn.master_settlement_currency
          } : txn));
      }
    } catch (err) {
      if (version !== loadVersion.current) return;
      console.error(err);
      showToast(tx("网络请求异常"), 'error');
    } finally {
      if (version === loadVersion.current) setLoading(false);
    }
  };

  useEffect(() => {
    if (id) {
      loadAccountData();
    }
    return () => { loadVersion.current += 1; };
  }, [id, period]);

  const account = data?.account;
  const nativeSymbol = {USD:'$', EUR:'€', GBP:'£', CAD:'C$', AUD:'A$', INR:'₹', JPY:'¥', CNY:'¥', CHF:'CHF', SGD:'S$', HKD:'HK$'}[account?.currency] || account?.currency || '¥';
  const metrics = data?.metrics;
  const chart = data?.chart;
  const balanceNumber = parseFloat(
    metrics?.balance !== undefined && metrics?.balance !== null
      ? metrics.balance
      : (account?.balance || 0)
  );

  // Filtered transactions
  const filteredTransactions = useMemo(() => {
    if (!searchQuery.trim()) return transactions;
    const q = searchQuery.toLowerCase();
    return transactions.filter(
      (t) =>
        (t.narration && t.narration.toLowerCase().includes(q)) ||
        (t.category_name && t.category_name.toLowerCase().includes(q))
    );
  }, [transactions, searchQuery]);

  // Group transactions by date
  const groupedTransactions = useMemo(() => {
    const groups = {};
    filteredTransactions.forEach((txn) => {
      const d = txn.transacted_at;
      if (!groups[d]) {
        groups[d] = {
          date: d,
          items: [],
        };
      }
      groups[d].items.push(txn);
    });

    const result = Object.values(groups);
    result.forEach((g) => {
      g.currencyTotals = totalsByCurrency(g.items, 'net', 'original');
      g.items.sort((a, b) => {
        const timeA = new Date(a.occurred_at || a.created_at || a.transacted_at).getTime() || 0;
        const timeB = new Date(b.occurred_at || b.created_at || b.transacted_at).getTime() || 0;
        return timeA - timeB; // 升序，由早到晚
      });
    });

    return result.sort((a, b) => (a.date < b.date ? 1 : -1));
  }, [filteredTransactions]);

  // ── 交互式折线图：支持左右滑动查看任意日期的精确金额与时间 ──
  const [hoverIndex, setHoverIndex] = useState(null);
  const [isScrubbing, setIsScrubbing] = useState(false);
  const chartSvgRef = useRef(null);
  const [chartWidth, setChartWidth] = useState(800);

  useEffect(() => {
    if (loading || !chartSvgRef.current) return;
    const node = chartSvgRef.current;
    const updateWidth = () => {
      if (node) {
        const w = node.clientWidth;
        if (w > 0) setChartWidth(Math.round(w));
      }
    };
    updateWidth();
    const ro = new ResizeObserver(updateWidth);
    ro.observe(node);
    window.addEventListener('resize', updateWidth);
    return () => {
      ro.disconnect();
      window.removeEventListener('resize', updateWidth);
    };
  }, [loading, data]);

  const chartData = useMemo(() => {
    const rawPoints = chart?.points || [];
    let points = [...rawPoints];
    if (points.length === 1) {
      points = [{ ...points[0], label: points[0].label || '期初' }, { ...points[0], label: '今日' }];
    } else if (points.length === 0) {
      const todayStr = new Date().toISOString().slice(0, 10);
      points = [
        { date: todayStr, label: '期初', balance: balanceNumber },
        { date: todayStr, label: '今日', balance: balanceNumber },
      ];
    }

    const width = chartWidth || 800;
    const height = 180;
    // 精准对齐底部 px-1 (4px) 的首尾文字边缘
    const paddingX = 4;
    const paddingY = 24;

    const balances = points.map((p) => p.balance);
    const minVal = Math.min(...balances);
    const maxVal = Math.max(...balances);
    const range = maxVal - minVal === 0 ? 1 : maxVal - minVal;

    const firstBal = points[0]?.balance || 0;

    // 基于真实时间戳精准计算横向时间跨度
    const startStr = chart?.start_iso || chart?.start_date || points[0]?.date;
    const endStr = chart?.end_iso || chart?.end_date || points[points.length - 1]?.date;
    const startTime = new Date(startStr).getTime();
    const endTime = new Date(endStr).getTime();
    const timeSpan = Math.max(1, endTime - startTime);

    const coords = points.map((p, index) => {
      let progress = 0;
      if (points.length > 1) {
        const pTime = new Date(p.date).getTime();
        if (!isNaN(pTime) && !isNaN(startTime) && timeSpan > 0) {
          progress = Math.max(0, Math.min(1, (pTime - startTime) / timeSpan));
        } else {
          progress = index / (points.length - 1);
        }
      }
      const x = paddingX + progress * (width - 2 * paddingX);
      const y = height - paddingY - ((p.balance - minVal) / range) * (height - 2 * paddingY);
      const changeFromStart = p.balance - firstBal;
      const pctFromStart = firstBal !== 0 ? ((changeFromStart / Math.abs(firstBal)) * 100).toFixed(1) : '0.0';
      return {
        ...p,
        index,
        x,
        y,
        changeFromStart,
        pctFromStart,
      };
    });

    let linePath = `M ${coords[0].x} ${coords[0].y}`;
    for (let i = 1; i < coords.length; i++) {
      linePath += ` L ${coords[i].x} ${coords[i].y}`;
    }

    const areaPath = `${linePath} L ${coords[coords.length - 1].x} ${height} L ${coords[0].x} ${height} Z`;

    return {
      points,
      coords,
      linePath,
      areaPath,
      width,
      height,
      paddingX,
      paddingY,
      minVal,
      maxVal,
    };
  }, [chart, balanceNumber, chartWidth]);

  // 处理滑动或鼠标移动位置（真实像素级距离对齐）
  const updateScrubPosition = (clientX) => {
    if (!chartData || !chartData.coords.length || !chartSvgRef.current) return;
    const rect = chartSvgRef.current.getBoundingClientRect();
    if (!rect || rect.width <= 0) return;

    const relX = Math.max(0, Math.min(rect.width, clientX - rect.left));

    let bestIdx = 0;
    let minDiff = Infinity;
    chartData.coords.forEach((c, idx) => {
      const diff = Math.abs(c.x - relX);
      if (diff < minDiff) {
        minDiff = diff;
        bestIdx = idx;
      }
    });

    setHoverIndex(bestIdx);
  };

  const handlePointerDown = (e) => {
    setIsScrubbing(true);
    updateScrubPosition(e.clientX);
    try {
      e.currentTarget.setPointerCapture(e.pointerId);
    } catch (_) {}
  };

  const handlePointerMove = (e) => {
    updateScrubPosition(e.clientX);
  };

  const handlePointerUp = (e) => {
    setIsScrubbing(false);
    try {
      e.currentTarget.releasePointerCapture(e.pointerId);
    } catch (_) {}
  };

  const handlePointerLeave = () => {
    if (!isScrubbing) {
      setHoverIndex(null);
    }
  };


  if (loading && !data) {
    return (
      <div className="flex flex-col items-center justify-center min-h-[60vh] gap-3">
        <div className="w-7 h-7 border-2 border-zinc-900 border-t-transparent rounded-full animate-spin dark:border-zinc-100" />
        <span className="text-xs text-zinc-400 font-medium">{tx("正在载入账户视图...")}</span>
      </div>
    );
  }

  if (!account) {
    return (
      <div className="p-8 text-center text-zinc-500">
        <p>{tx("未找到该账户信息或您无权访问")}</p>
        <Link to="/" className="mt-4 inline-block text-xs text-zinc-900 dark:text-white underline">{tx("返回主页")}</Link>
      </div>
    );
  }

  const isLiability =
    account.classification === 'liability' ||
    account.account_type === 'credit_card' ||
    account.account_type === 'loan';

  const changePct = metrics?.change_percent || 0.0;
  const isPositiveChange = changePct >= 0;
  const cfg = getAccountTypeConfig(account);
  const AccLogoIcon = cfg.icon;

  return (
    <div className="space-y-4 pb-20 max-w-7xl mx-auto w-full">
      {account?.own_balance != null && Number(account.subcard_settlement_balance) !== 0 && <p className="text-xs text-zinc-500">{tx("主卡自身余额")} {privacyMode ? '••••••' : `${account.own_balance} ${account.currency}`} {tx("· 副卡固定结算合计")} {privacyMode ? '••••••' : `${account.subcard_settlement_balance} ${account.currency}`}</p>}
      {/* ── 1. Top Breadcrumb (Exact 13.png: 主页 > 账户) ── */}
      <div className="hidden lg:flex items-center justify-between text-xs text-zinc-500">
        <div className="flex items-center gap-2">
          <span>{tx("主页")}</span>
          <ChevronRight className="w-3 h-3 text-zinc-300" />
          <span className="text-zinc-900 dark:text-zinc-100 font-medium">{tx("账户")}</span>
        </div>
      </div>

      {/* ── 2. Account Header ── */}
      <div className="flex items-center justify-between gap-3 pt-1">
        <div className="flex items-center gap-3 min-w-0 flex-1">
          {/* Account Category Logo Badge */}
          <div className={`w-10 h-10 rounded-xl border flex items-center justify-center shrink-0 shadow-xs ${cfg.bgColor} ${cfg.borderColor}`}>
            <AccLogoIcon className={`w-5 h-5 ${cfg.color}`} />
          </div>

          <div className="min-w-0 flex-1">
            <h1 className="text-lg sm:text-xl font-bold tracking-tight text-zinc-900 dark:text-zinc-100 font-mono truncate" title={account.name}>
              {account.name}
            </h1>
            <div className="flex items-center gap-1.5 mt-0.5 flex-wrap">
              <span className={`px-2 py-0.5 rounded-full text-[11px] font-semibold border shrink-0 whitespace-nowrap ${cfg.badgeClass}`}>
                {tx(cfg.label)}
              </span>
              {(() => {
                const isSharedFromOther =
                  account.is_owner === false ||
                  (account.owner &&
                    user?.username &&
                    account.owner.toLowerCase() !== user.username.toLowerCase());
                if (isSharedFromOther) {
                  return (
                    <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[11px] font-medium bg-purple-50 dark:bg-purple-950/60 text-purple-600 dark:text-purple-300 border border-purple-200/60 dark:border-purple-800/60 whitespace-nowrap">
                      <Users className="w-2.5 h-2.5" /> {tx("由")} {account.owner} {tx("共享 (")} {account.can_manage ? tx("完全控制") : account.can_edit ? tx("可记账") : tx("只读")})
                    </span>
                  );
                }
                if (account.shared_with_count > 0) {
                  return (
                    <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[11px] font-medium bg-blue-50 dark:bg-blue-950/60 text-blue-600 dark:text-blue-400 border border-blue-200/60 dark:border-blue-800/60 whitespace-nowrap">
                      <Users className="w-2.5 h-2.5" /> {tx("已共享给")} {account.shared_with_count} {tx("位家人")}</span>
                  );
                }
                return null;
              })()}
            </div>
          </div>
        </div>

        {/* Right Actions: Only More Dropdown */}
        <div className="flex items-center shrink-0">
          {/* Account Action Dropdown (Exact 12.png & 13.png) */}
          <div className="relative">
            <button
              type="button"
              data-testid="account-actions-trigger"
              onClick={() => setShowAccountMenu(!showAccountMenu)}
              title={tx("账户操作")}
              className="p-2 rounded-lg text-zinc-500 hover:text-zinc-900 dark:hover:text-white hover:bg-zinc-100 dark:hover:bg-zinc-800 transition-colors cursor-pointer"
            >
              <MoreHorizontal className="w-4 h-4" />
            </button>

            {showAccountMenu && (
              <>
                <div
                  className="fixed inset-0 z-20"
                  onClick={() => setShowAccountMenu(false)}
                />
                <div className="absolute right-0 top-full mt-1 w-44 rounded-xl bg-white dark:bg-zinc-800 border border-zinc-200 dark:border-zinc-700 shadow-xl py-1.5 z-30 text-xs animate-in fade-in zoom-in-95 duration-100">
                  {account.can_manage === true && (
                    <button
                      type="button"
                      onClick={() => {
                        setEditingAccount(account);
                        setShowAccountMenu(false);
                      }}
                      className="w-full text-left px-3 py-2 text-zinc-700 dark:text-zinc-200 hover:bg-zinc-50 dark:hover:bg-zinc-700/60 flex items-center gap-2 cursor-pointer"
                    >
                      <span>{tx("✏️ 编辑")}</span>
                    </button>
                  )}
                  <button
                    type="button"
                    onClick={() => {
                      setSharingAccountId(account.id);
                      setShowAccountMenu(false);
                    }}
                    className="w-full text-left px-3 py-2 text-zinc-700 dark:text-zinc-200 hover:bg-zinc-50 dark:hover:bg-zinc-700/60 flex items-center gap-2 cursor-pointer"
                  >
                    <span>{tx("🔗 共享")}</span>
                  </button>
                  {account.can_manage_shares === true && (
                    <button
                      type="button"
                      onClick={() => {
                        setTransferringAccount(account);
                        setShowAccountMenu(false);
                      }}
                      className="w-full text-left px-3 py-2 text-zinc-700 dark:text-zinc-200 hover:bg-zinc-50 dark:hover:bg-zinc-700/60 flex items-center gap-2 cursor-pointer"
                    >
                      <span>{tx("🔄 转移所有权")}</span>
                    </button>
                  )}
                  {account.can_edit === true && (
                    <button
                      type="button"
                      onClick={() => {
                        setImportingAccount(account);
                        setShowAccountMenu(false);
                      }}
                      className="w-full text-left px-3 py-2 text-zinc-700 dark:text-zinc-200 hover:bg-zinc-50 dark:hover:bg-zinc-700/60 flex items-center gap-2 cursor-pointer"
                    >
                      <span>{tx("📥 导入交易记录")}</span>
                    </button>
                  )}
                  {account.can_manage === true && <div className="my-1 border-t border-zinc-100 dark:border-zinc-700/60" />}
                  {account.can_manage === true && (
                    <button
                      type="button"
                      data-testid="delete-account-btn"
                      onClick={() => {
                        setDeletingAccount(account);
                        setShowAccountMenu(false);
                      }}
                      className="w-full text-left px-3 py-2 text-red-600 dark:text-red-400 hover:bg-red-50 dark:hover:bg-red-950/30 flex items-center gap-2 cursor-pointer"
                    >
                      <span>{tx("🗑️ 删除账户")}</span>
                    </button>
                  )}
                </div>
              </>
            )}
          </div>
        </div>
      </div>

      {/* ── 3. Balance Trend Overview Card (Exact 13.png with interactive scrub) ── */}
      {(() => {
        const activePoint = hoverIndex !== null && chartData ? chartData.coords[hoverIndex] : null;
        const displayBalance = balanceNumber;
        const displayChangeAmount = metrics?.change_amount || 0;
        const displayChangePct = changePct;
        const isDisplayPositive = parseFloat(displayChangeAmount) >= 0;

        return (
          <div className="rounded-2xl border border-zinc-200/90 dark:border-zinc-800 bg-white dark:bg-zinc-900 p-6 shadow-xs relative">
            <div className="flex items-start justify-between">
              <div>
                <div className="flex items-center gap-2">
                  <p className="text-xs font-semibold text-zinc-500 flex items-center gap-1.5">
                    {isLiability
                      ? (displayBalance < 0 ? tx("溢缴款 (还款盈余)") : tx("债务余额"))
                      : tx("当前余额")}
                    {isLiability && displayBalance < 0 && (
                      <span className="px-1.5 py-0.5 rounded text-[11px] font-medium bg-emerald-50 dark:bg-emerald-950/60 text-emerald-600 dark:text-emerald-400 border border-emerald-200 dark:border-emerald-800">{tx("无需还款 · 充当可用额度")}</span>
                    )}
                  </p>
                  {activePoint && (
                    <button
                      type="button"
                      data-testid="reset-scrub-btn"
                      onClick={() => setHoverIndex(null)}
                      className="text-[11px] text-blue-600 dark:text-blue-400 bg-blue-50 dark:bg-blue-950/60 hover:bg-blue-100 dark:hover:bg-blue-900/60 px-1.5 py-0.5 rounded-md font-medium transition cursor-pointer"
                    >{tx("清除历史标记")}</button>
                  )}
                </div>

                <div
                  data-testid="account-display-balance"
                  className={`text-2xl sm:text-3xl font-bold font-mono tracking-tight mt-1 ${
                    isLiability && displayBalance < 0
                      ? 'text-emerald-600 dark:text-emerald-400'
                      : 'text-zinc-900 dark:text-zinc-100'
                  }`}
                >
                  {privacyMode
                    ? '••••••'
                    : `${displayBalance < 0 ? '-' : ''}${nativeSymbol}${Math.abs(displayBalance).toLocaleString(currentLocale(), { minimumFractionDigits: 2 })}`}
                </div>

                {/* Change pill & comparison text */}
                <div className="flex items-center gap-2 mt-2 text-xs">
                  <span
                    className={`font-mono font-medium ${
                      isDisplayPositive
                        ? 'text-emerald-600 dark:text-emerald-400'
                        : 'text-rose-600 dark:text-rose-400'
                    }`}
                  >
                    {privacyMode ? '••••••' : `${displayChangeAmount < 0 ? '−' : '+'}${chartMoney(Math.abs(displayChangeAmount), nativeSymbol, false, currentLocale())}`}{' '}
                    ({displayChangeAmount < 0 ? '↓' : '↑'} {Math.abs(displayChangePct)}%)
                  </span>
                  <span className="text-zinc-400">
                    {activePoint ? tx("较期初变动") : tx(metrics?.compare_label || "与月初相比")}
                  </span>
                </div>
              </div>

              {/* Time range selector: MTD ⌄ (Exact 13.png) */}
              <div className="relative">
                <button
                  type="button"
                  onClick={() => setPeriodDropdownOpen(!periodDropdownOpen)}
                  className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-semibold rounded-lg border border-zinc-200 dark:border-zinc-700 bg-white dark:bg-zinc-800 text-zinc-800 dark:text-zinc-200 hover:bg-zinc-50 dark:hover:bg-zinc-700/60 shadow-2xs"
                >
                  <span>{period}</span>
                  <ChevronDown className="w-3.5 h-3.5 text-zinc-400" />
                </button>

                {periodDropdownOpen && (
                  <div className="absolute right-0 top-full mt-1.5 w-28 rounded-xl bg-white dark:bg-zinc-800 border border-zinc-200 dark:border-zinc-700 shadow-xl py-1 z-30 text-xs">
                    {["MTD", "1M", "3M", "6M", "YTD", "ALL"].map((p) => (
                      <button
                        key={p}
                        type="button"
                        onClick={() => {
                          setPeriod(p);
                          setPeriodDropdownOpen(false);
                          setHoverIndex(null);
                        }}
                        className={`w-full text-left px-3 py-1.5 cursor-pointer ${
                          period === p
                            ? 'bg-zinc-100 dark:bg-zinc-700 font-semibold text-zinc-900 dark:text-white'
                            : 'text-zinc-600 dark:text-zinc-300 hover:bg-zinc-50 dark:hover:bg-zinc-700/40'
                        }`}
                      >
                        {p}
                      </button>
                    ))}
                  </div>
                )}
              </div>
            </div>

            {/* ── 交互式平滑折线图容器 (支持鼠标移动与触摸左右滑动 scrub) ── */}
            <div
              ref={chartSvgRef}
              data-testid="account-balance-chart-container"
              onPointerDown={handlePointerDown}
              onPointerMove={handlePointerMove}
              onPointerUp={handlePointerUp}
              onPointerLeave={handlePointerLeave}
              className="mt-8 relative h-48 w-full select-none touch-none cursor-crosshair group"
            >
              {/* 跟随游标指示线的悬浮气泡 (Floating Tooltip) */}
              {activePoint && (
                <div
                  data-testid="chart-scrub-tooltip"
                  className="absolute -top-3 pointer-events-none transform -translate-x-1/2 bg-zinc-900/95 dark:bg-zinc-100/95 text-white dark:text-zinc-900 px-3 py-1.5 rounded-xl shadow-xl text-xs font-mono flex flex-col items-center gap-0.5 border border-zinc-700/50 dark:border-zinc-200/50 z-20 whitespace-nowrap transition-all duration-75"
                  style={{
                    left: `${(activePoint.x / chartData.width) * 100}%`,
                  }}
                >
                  <span className="text-[11px] text-zinc-400 dark:text-zinc-600 font-medium">
                    {dateLabel(activePoint.label || activePoint.date)}
                  </span>
                  <span className="font-bold text-sm tracking-tight text-emerald-400 dark:text-emerald-600">
                    {chartMoney(activePoint.balance, nativeSymbol, privacyMode, currentLocale())}
                  </span>
                  <div className="w-2 h-2 bg-zinc-900 dark:bg-zinc-100 rotate-45 -mb-2 mt-0.5" />
                </div>
              )}

              <svg
                viewBox={`0 0 ${chartData.width} ${chartData.height}`}
                preserveAspectRatio="none"
                className="w-full h-full overflow-visible"
              >
                <defs>
                  <linearGradient id="balanceChartGradient" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor="#10b981" stopOpacity="0.25" />
                    <stop offset="100%" stopColor="#10b981" stopOpacity="0.0" />
                  </linearGradient>
                </defs>

                {/* 渐变填充背景面积 */}
                {chartData.areaPath && (
                  <path d={chartData.areaPath} fill="url(#balanceChartGradient)" />
                )}

                {/* 主折线 */}
                <path
                  d={chartData.linePath || 'M 24 90 L 776 90'}
                  fill="none"
                  stroke="#10b981"
                  strokeWidth="2.5"
                  vectorEffect="non-scaling-stroke"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                />

                {/* 活跃指示线与点 (左右滑动时显示) */}
                {activePoint && (
                  <g className="transition-all duration-75">
                    {/* 竖向参考游标线 */}
                    <line
                      x1={activePoint.x}
                      y1={8}
                      x2={activePoint.x}
                      y2={chartData.height - 8}
                      stroke="#3b82f6"
                      strokeWidth="1.5"
                      strokeDasharray="4 4"
                    />

                    {/* 外圈光晕圆圈 */}
                    <circle
                      cx={activePoint.x}
                      cy={activePoint.y}
                      r="8"
                      fill="#3b82f6"
                      fillOpacity="0.25"
                      className="animate-pulse"
                    />

                    {/* 内圈实体高亮点 */}
                    <circle
                      cx={activePoint.x}
                      cy={activePoint.y}
                      r="4.5"
                      fill="#2563eb"
                      stroke="#ffffff"
                      strokeWidth="2"
                    />
                  </g>
                )}
              </svg>

              {/* Date Axis & 滑动提示 (底部轴线) */}
              <div className="flex items-center justify-between text-[11px] font-mono text-zinc-400 mt-2 px-1">
                <span>{dateLabel(chart?.start_date || tx("Sep 01, 2026"))}</span>
                <div className="text-zinc-400 dark:text-zinc-500 font-sans text-[11px] flex items-center gap-1">
                  {activePoint ? (
                    <span className="text-blue-600 dark:text-blue-400 font-medium font-mono">
                      {activePoint.date} {tx("· 历史采样点")}</span>
                  ) : (
                    <span>{tx("↔️ 左右滑动查看历史走势")}</span>
                  )}
                </div>
                <span>{dateLabel(chart?.end_date || tx("Sep 27, 2026"))}</span>
              </div>
            </div>
          </div>
        );
      })()}

      {/* ── 4. Activity & Plans Tabs ── */}
      <div className="flex flex-wrap items-center gap-1.5 p-1 bg-zinc-100/80 dark:bg-zinc-800/80 rounded-xl w-fit max-w-full">
        <button
          type="button"
          onClick={() => setActiveTab('activity')}
          className={`px-4 py-1.5 text-xs font-semibold rounded-lg transition-all ${
            activeTab === 'activity'
              ? 'bg-white dark:bg-zinc-700 text-zinc-900 dark:text-white shadow-xs'
              : 'text-zinc-500 hover:text-zinc-900 dark:hover:text-zinc-200'
          }`}
        >{tx("活动")}</button>
        <button
          type="button"
          data-testid="account-plan-tab"
          onClick={() => setActiveTab('plans')}
          className={`px-4 py-1.5 text-xs font-semibold rounded-lg transition-all ${
            activeTab === 'plans'
              ? 'bg-white dark:bg-zinc-700 text-zinc-900 dark:text-white shadow-xs'
              : 'text-zinc-500 hover:text-zinc-900 dark:hover:text-zinc-200'
          }`}
        >{tx("计划")}</button>
      </div>

      {/* ── 5. Activity Container (Exact 13.png) ── */}
      {activeTab === 'plans' ? (
        <ScheduledPlans account={account} onSelectTransaction={setSelectedTxnId} onChanged={() => loadAccountData(true)} />
      ) : (
        <div className="space-y-4">
          <div className="rounded-2xl border border-zinc-200/90 dark:border-zinc-800 bg-white dark:bg-zinc-900 shadow-xs overflow-hidden">
            {/* Activity Card Header: 标题 + [ + 新建 ] 按钮 */}
            <div className="p-4 flex items-center justify-between border-b border-zinc-100 dark:border-zinc-800/60">
              <h2 className="text-sm font-bold text-zinc-900 dark:text-zinc-100">{tx("活动")}</h2>

              {/* + 新建 下拉按钮 (Exact 13.png 红框位置) */}
              <div className="relative">
                {account.can_edit === true && (
                  <button
                    type="button"
                    data-testid="account-create-menu-btn"
                    onClick={() => setShowCreateMenu(!showCreateMenu)}
                    className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-zinc-100 dark:bg-zinc-800 hover:bg-zinc-200 dark:hover:bg-zinc-700 text-zinc-900 dark:text-zinc-100 text-xs font-semibold transition-all cursor-pointer border border-zinc-200/80 dark:border-zinc-700"
                  >
                    <Plus className="w-3.5 h-3.5" />
                    <span>{tx("新建")}</span>
                  </button>
                )}

                {account.can_edit === true && showCreateMenu && (
                  <>
                    <div className="fixed inset-0 z-20" onClick={() => setShowCreateMenu(false)} />
                    <div className="absolute right-0 top-full mt-1.5 w-36 rounded-xl bg-white dark:bg-zinc-800 border border-zinc-200 dark:border-zinc-700 shadow-xl py-1 z-30 text-xs animate-in fade-in zoom-in-95 duration-100">
                      <button
                        type="button"
                        data-testid="account-create-new-balance-btn"
                        onClick={() => {
                          setShowCreateMenu(false);
                          if (account && account.can_edit === false) {
                            showToast(tx("您对此账户仅有只读权限，无法调整余额"), 'error');
                            return;
                          }
                          setShowNewBalanceModal(true);
                        }}
                        className="w-full text-left px-3 py-2 text-zinc-700 dark:text-zinc-200 hover:bg-zinc-50 dark:hover:bg-zinc-700/60 flex items-center gap-2 cursor-pointer"
                      >
                        <span>{tx("新余额")}</span>
                      </button>
                      <button
                        type="button"
                        onClick={() => {
                          setShowCreateMenu(false);
                          if (account && account.can_edit === false) {
                            showToast(tx("您对此账户仅有只读权限，无法录入新交易"), 'error');
                            return;
                          }
                          setDefaultTxnType('expense');
                          setShowAddTxnModal(true);
                        }}
                        className="w-full text-left px-3 py-2 text-zinc-700 dark:text-zinc-200 hover:bg-zinc-50 dark:hover:bg-zinc-700/60 flex items-center gap-2 cursor-pointer"
                      >
                        <span>{tx("新交易记录")}</span>
                      </button>
                      <button
                        type="button"
                        onClick={() => {
                          setShowCreateMenu(false);
                          if (account && account.can_edit === false) {
                            showToast(tx("您对此账户仅有只读权限，无法录入转账"), 'error');
                            return;
                          }
                          setDefaultTxnType('transfer');
                          setShowAddTxnModal(true);
                        }}
                        className="w-full text-left px-3 py-2 text-zinc-700 dark:text-zinc-200 hover:bg-zinc-50 dark:hover:bg-zinc-700/60 flex items-center gap-2 cursor-pointer"
                      >
                        <span>{tx("新转账")}</span>
                      </button>
                    </div>
                  </>
                )}
              </div>
            </div>

            {/* Search and Filters Bar (Exact 13.png) */}
            <div className="p-3 bg-zinc-50/50 dark:bg-zinc-800/20 border-b border-zinc-100 dark:border-zinc-800/60 flex items-center gap-2">
              <div className="relative flex-1">
                <Search className="w-3.5 h-3.5 text-zinc-400 absolute left-3 top-1/2 -translate-y-1/2" />
                <input
                  type="text"
                  placeholder={tx("按名称搜索记录")}
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                  className="w-full pl-8 pr-3 py-1.5 text-xs rounded-lg border border-zinc-200 dark:border-zinc-700 bg-white dark:bg-zinc-900 text-zinc-900 dark:text-white placeholder:text-zinc-400 focus:outline-hidden focus:ring-1 focus:ring-zinc-800"
                />
              </div>

              <Link
                to={`/transactions?account_id=${id}`}
                className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-lg border border-zinc-200 dark:border-zinc-700 bg-white dark:bg-zinc-900 hover:bg-zinc-50 dark:hover:bg-zinc-800 text-zinc-700 dark:text-zinc-300 transition-colors shadow-2xs"
              >
                <SlidersHorizontal className="w-3.5 h-3.5 text-zinc-500" />
                <span>{tx("筛选")}</span>
              </Link>
            </div>

            {/* Transactions Grouped List (Exact 13.png) */}
            <div className="divide-y divide-zinc-100 dark:divide-zinc-800/60">
              {groupedTransactions.length === 0 ? (
                <div className="py-12 text-center text-xs text-zinc-400">{tx("暂无匹配的活动流水记录")}</div>
              ) : (
                groupedTransactions.map((group) => (
                  <div key={group.date} className="p-4 hover:bg-zinc-50/50 dark:hover:bg-zinc-800/20 transition-colors">
                    {/* Date group bar */}
                    <div className="flex items-center justify-between text-xs pb-2 border-b border-zinc-50 dark:border-zinc-800/30">
                      <span className="font-semibold text-zinc-700 dark:text-zinc-300">
                        {group.date} · {group.items.length} {tx("笔")}</span>
                      <span className="font-mono font-bold text-zinc-900 dark:text-zinc-100">
                        {privacyMode ? '••••••' : formatCurrencyTotals(group.currencyTotals)}
                      </span>
                    </div>

                    {/* Group Items */}
                    <div className="pt-2 divide-y divide-zinc-50 dark:divide-zinc-800/40">
                      {group.items.map((txn) => {
                        const badge = getTransactionInitialBadge(txn.narration);
                        const isRefund = txn.transaction_type === 'refund';
                        const isTransfer = txn.transaction_type === 'transfer';

                        return (
                          <div
                            key={txn.id}
                            data-testid="account-transaction-row"
                            onClick={() => setSelectedTxnId(txn.id)}
                            className="flex flex-col py-2 px-2 hover:bg-zinc-100/70 dark:hover:bg-zinc-800/60 rounded-xl cursor-pointer transition-colors group"
                          >
                            <div className="flex items-center justify-between w-full">
                              {/* Left: Platform / Transaction Initial Logo + Name & Subtitle */}
                              <div className="flex items-center gap-3 flex-1 min-w-0 pr-3">
                                {/* Transaction Initial Logo Circle/Square */}
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
                                      <span className="inline-flex items-center gap-0.5 px-1.5 py-0.5 rounded text-[11px] font-semibold bg-emerald-50 dark:bg-emerald-950/40 text-emerald-700 dark:text-emerald-300 border border-emerald-200 dark:border-emerald-800 whitespace-nowrap shrink-0">
                                        <RotateCcw className="w-2.5 h-2.5" />
                                        <span>{tx("退款")}</span>
                                      </span>
                                    )}
                                    {isTransfer && (
                                      <span className="inline-flex items-center gap-0.5 px-1.5 py-0.5 rounded text-[11px] font-semibold bg-blue-50 dark:bg-blue-950/40 text-blue-700 dark:text-blue-300 border border-blue-200 dark:border-blue-800 whitespace-nowrap shrink-0">
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
                                    {txn.transaction_type === 'adjustment' && (
                                      <span className="inline-flex items-center gap-0.5 px-1.5 py-0.5 rounded text-[11px] font-semibold bg-purple-50 dark:bg-purple-950/40 text-purple-700 dark:text-purple-300 border border-purple-200 dark:border-purple-800 whitespace-nowrap shrink-0">
                                        <SlidersHorizontal className="w-2.5 h-2.5" />
                                        <span>{tx("余额对账")}</span>
                                      </span>
                                    )}
                                  </div>
                                  <div className="text-[11px] text-zinc-400 dark:text-zinc-500 mt-0.5 min-w-0 flex items-center gap-1.5 flex-wrap">
                                    {isTransfer ? (
                                      <span className="font-semibold text-blue-600 dark:text-blue-400 flex items-center flex-wrap gap-x-1 gap-y-0.5 leading-tight">
                                        {txn.transfer_peer_account ? (() => {
                                          const peerIsMe = txn.transfer_peer_is_owner !== undefined
                                            ? txn.transfer_peer_is_owner
                                            : (!txn.transfer_peer_owner_name ||
                                               txn.transfer_peer_owner_name === '我的' ||
                                               txn.transfer_peer_owner_name === '本人' ||
                                               txn.transfer_peer_owner_name === user?.username ||
                                               txn.transfer_peer_owner_name === user?.displayName);
                                          const peerOwner = !peerIsMe ? txn.transfer_peer_owner_name : null;
                                          const renderPeerNode = () => {
                                            if (!txn.transfer_peer_account || txn.transfer_peer_account === '外部账户') return <span>{tx("外部账户")}</span>;
                                            if (peerOwner) {
                                              return (
                                                <span className="inline-flex items-center gap-1 text-purple-600 dark:text-purple-400 font-medium">
                                                  <span className="font-semibold">{peerOwner}</span>
                                                  <span className="font-normal text-zinc-400 dark:text-zinc-500">· {txn.transfer_peer_account}</span>
                                                </span>
                                              );
                                            }
                                            return <span>{txn.transfer_peer_account}</span>;
                                          };

                                          return txn.transfer_is_outflow ? (
                                            <>
                                              <span className="text-zinc-500 dark:text-zinc-400">{account?.name || tx("当前账户")}</span>
                                              <span className="text-blue-500 font-bold">➔</span>
                                              {renderPeerNode()}
                                            </>
                                          ) : (
                                            <>
                                              {renderPeerNode()}
                                              <span className="text-blue-500 font-bold">➔</span>
                                              <span className="text-zinc-500 dark:text-zinc-400">{account?.name || tx("当前账户")}</span>
                                            </>
                                          );
                                        })() : (
                                          (txn.narration || '').includes("转入") || (txn.narration || '').includes("收到") ? (
                                            <>
                                              <span className="text-zinc-400">{tx("外部账户")}</span>
                                              <span className="text-blue-500 font-bold">➔</span>
                                              <span>{account?.name || tx("当前账户")}</span>
                                            </>
                                          ) : (
                                            <>
                                              <span>{account?.name || tx("当前账户")}</span>
                                              <span className="text-blue-500 font-bold">➔</span>
                                              <span className="text-zinc-400">{tx("外部账户")}</span>
                                            </>
                                          )
                                        )}
                                      </span>
                                    ) : (
                                      <>
                                        {txn.account_id && txn.account_id !== account?.id ? (
                                          <span className="inline-flex items-center gap-1 min-w-0" title={tx("附属卡消费 · {p0}", {p0: (txn.account_name || tx("附属卡"))})}>
                                            <span className="px-1 py-0.5 rounded text-[10px] font-semibold bg-amber-50 dark:bg-amber-950/60 text-amber-700 dark:text-amber-400 border border-amber-200 dark:border-amber-800 shrink-0">{tx("副卡")}</span>
                                            <span className="truncate font-normal max-w-[120px] sm:max-w-none text-zinc-600 dark:text-zinc-400">
                                              {txn.account_name || tx("附属卡")}
                                            </span>
                                          </span>
                                        ) : (
                                          <span className="truncate font-normal max-w-[120px] sm:max-w-none" title={account?.name || tx("当前账户")}>
                                            {account?.name || tx("当前账户")}
                                          </span>
                                        )}
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

                              {/* Center: Category Pill (matching TransactionsPage) */}
                              <div className="hidden sm:flex items-center w-36 shrink-0 text-left">
                                <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-[11px] font-semibold bg-zinc-100 dark:bg-zinc-800 text-zinc-700 dark:text-zinc-300 border border-zinc-200/60 dark:border-zinc-700/60">
                                  <span>{txn.category_icon || '📦'}</span>
                                  <span className="truncate max-w-[90px]">{categoryLabel(txn.category_name) || tx("日常消费")}</span>
                                </span>
                              </div>

                              {/* Right: Amount & Time (Fixed w-32 for alignment) */}
                              <div className="w-auto sm:w-32 text-right shrink-0 flex flex-col items-end gap-0.5">
                                <span className={`font-mono font-bold text-xs ${
                                  isRefund || txn.transaction_type === 'income'
                                    ? 'text-emerald-600 dark:text-emerald-400'
                                    : isTransfer
                                    ? 'text-zinc-600 dark:text-zinc-300'
                                    : txn.transaction_type === 'adjustment'
                                    ? ((txn.narration || '').includes('(-') || txn.notes?.includes('减少') ? 'text-zinc-900 dark:text-zinc-100' : 'text-emerald-600 dark:text-emerald-400')
                                    : 'text-zinc-900 dark:text-white'
                                }`}>
                                  <TransactionAmount transaction={txn} privacy={privacyMode} />
                                </span>
                                <BookingMoneyInfo transaction={txn} privacy={privacyMode} />
                                {txn.occurred_at && (
                                  <span className="font-mono text-[11px] text-zinc-400 dark:text-zinc-500 tabular-nums leading-tight">
                                    {formatDateTime(txn.occurred_at).split(' ')[1]}
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
                                    <ReimbursementBadge txn={txn} onStatusUpdated={() => loadAccountData()} />
                                  </div>
                                )}

                                {/* Right: 靠右对齐，放置于时间正下方 */}
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
                ))
              )}
            </div>
          </div>
        </div>
      )}

      {/* ── 6. Modals ── */}
      {/* 确认新余额模态框 (Exact 14.png) */}
      <NewBalanceModal
        isOpen={showNewBalanceModal}
        onClose={() => setShowNewBalanceModal(false)}
        account={account}
        onSuccess={loadAccountData}
      />

      {/* 新建交易模态框 */}
      <AddTransactionModal
        open={showAddTxnModal}
        onClose={() => setShowAddTxnModal(false)}
        defaultAccountId={account?.id}
        defaultType={defaultTxnType}
        onSuccess={loadAccountData}
      />

      {/* 账户操作：编辑 / 共享 / 转移 / 删除 / 导入 */}
      <EditAccountModal
        isOpen={!!editingAccount}
        onClose={() => setEditingAccount(null)}
        account={editingAccount}
        onSuccess={loadAccountData}
      />

      <AccountSharingModal
        accountId={sharingAccountId}
        isOpen={!!sharingAccountId}
        onClose={() => setSharingAccountId(null)}
        onSuccess={loadAccountData}
      />

      <TransferOwnershipModal
        isOpen={!!transferringAccount}
        onClose={() => setTransferringAccount(null)}
        account={transferringAccount}
        onSuccess={loadAccountData}
      />

      <DeleteAccountModal
        isOpen={!!deletingAccount}
        onClose={() => setDeletingAccount(null)}
        account={deletingAccount}
        onSuccess={() => {
          navigate('/');
        }}
      />

      <ImportTransactionsModal
        isOpen={!!importingAccount}
        onClose={() => setImportingAccount(null)}
        account={importingAccount}
        onSuccess={loadAccountData}
      />

      {selectedTxnId && (
        <TransactionDrawer
          transactionId={selectedTxnId}
          onClose={() => setSelectedTxnId(null)}
          onTransactionUpdated={loadAccountData}
        />
      )}
    </div>
  );
}
