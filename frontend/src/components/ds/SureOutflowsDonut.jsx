import { chartMoney } from '../../utils/chartMoney';
import { categoryLabel, tx, useLocale, currentLocale } from "../../localization.js";
import React, { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { ChevronRight } from 'lucide-react';
import { useCurrency } from '../../CurrencyContext';

export default function SureOutflowsDonut({
  data,
  currencySymbol: reportSymbol,
  userFilter = '',
  startDate = '',
  endDate = '',
}) {
  useLocale();
  const { symbol, privacyMode } = useCurrency() || {};
  const currencySymbol = reportSymbol ?? symbol ?? '';
  const formatAmount = value => chartMoney(value, currencySymbol, privacyMode, currentLocale());
  const navigate = useNavigate();
  const [groupBy, setGroupBy] = useState('category'); // 'category' | 'account'
  const [activeCategory, setActiveCategory] = useState(null);

  const total = Number(data?.total) || 0;
  const categories = Array.isArray(data?.categories) ? data.categories : [];
  const accounts = Array.isArray(data?.by_account) ? data.by_account : [];
  const adjustments = Array.isArray(data?.adjustments) ? data.adjustments : [];

  const activeItems = groupBy === 'account' ? accounts : categories;

  const buildUrl = (extraParams = {}) => {
    const params = new URLSearchParams();
    Object.entries(extraParams).forEach(([k, v]) => {
      if (v !== undefined && v !== null && v !== '') {
        params.set(k, v);
      }
    });
    if (userFilter && userFilter !== '全部' && userFilter !== 'all') {
      params.set('user', userFilter);
    }
    if (startDate) {
      params.set('start_date', startDate);
    }
    if (endDate) {
      params.set('end_date', endDate);
    }
    const q = params.toString();
    return `/transactions${q ? `?${q}` : ''}`;
  };

  const handleItemClick = (item) => {
    if (item.amount < 0) {
      navigate(buildUrl({ transaction_type: 'refund' }));
      return;
    }
    if (groupBy === 'account' && item.account_id) {
      navigate(buildUrl({ account_id: item.account_id, transaction_type: 'expense' }));
    } else {
      navigate(buildUrl({ category_name: item.name, transaction_type: 'expense' }));
    }
  };

  const handleAdjustmentClick = () => {
    navigate(buildUrl({ transaction_type: 'refund' }));
  };

  // SVG Donut calculation
  const radius = 100;
  const strokeWidth = 14;
  const center = 120;
  const circumference = 2 * Math.PI * radius;

  let accumulatedPercent = 0;
  const segments = activeItems.filter((item) => item.amount > 0).map((item) => {
    const strokeDasharray = `${(item.percentage / 100) * circumference} ${circumference}`;
    const strokeDashoffset = -((accumulatedPercent / 100) * circumference);
    accumulatedPercent += item.percentage;
    return {
      ...item,
      strokeDasharray,
      strokeDashoffset,
    };
  });

  return (
    <div className="space-y-4">
      {/* ── Segmented Switch: 按分类 | 按账户 ── */}
      <div className="flex justify-end">
        <div className="inline-flex p-0.5 bg-zinc-100 dark:bg-zinc-800 rounded-lg text-xs font-medium">
          <button
            onClick={() => setGroupBy('category')}
            className={`px-3 py-1 rounded-md transition-all ${
              groupBy === 'category'
                ? 'bg-white dark:bg-zinc-700 text-zinc-900 dark:text-white font-semibold shadow-2xs'
                : 'text-zinc-500 hover:text-zinc-900 dark:hover:text-zinc-200'
            }`}
          >{tx("按分类")}</button>
          <button
            onClick={() => setGroupBy('account')}
            className={`px-3 py-1 rounded-md transition-all ${
              groupBy === 'account'
                ? 'bg-white dark:bg-zinc-700 text-zinc-900 dark:text-white font-semibold shadow-2xs'
                : 'text-zinc-500 hover:text-zinc-900 dark:hover:text-zinc-200'
            }`}
          >{tx("按账户")}</button>
        </div>
      </div>

      {/* ── Body Grid: Left Donut + Right Table ── */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-8 items-center">
        {/* Left: Donut Chart */}
        <div className="lg:col-span-4 flex flex-col items-center justify-center relative min-h-[260px]">
          <svg width={center * 2} height={center * 2} className="rotate-[-90deg] overflow-visible">
            {/* Background ring */}
            <circle
              cx={center}
              cy={center}
              r={radius}
              fill="transparent"
              stroke="currentColor"
              strokeWidth={strokeWidth}
              className="text-zinc-100 dark:text-zinc-800/80"
            />
            {/* Data slices */}
            {segments.map((seg) => {
              const isHovered = activeCategory === seg.id;
              return (
                <circle
                  key={seg.id}
                  cx={center}
                  cy={center}
                  r={radius}
                  fill="transparent"
                  stroke={seg.color}
                  strokeWidth={isHovered ? strokeWidth + 4 : strokeWidth}
                  strokeDasharray={seg.strokeDasharray}
                  strokeDashoffset={seg.strokeDashoffset}
                  strokeLinecap="round"
                  className="transition-all duration-200 cursor-pointer"
                  onMouseEnter={() => setActiveCategory(seg.id)}
                  onMouseLeave={() => setActiveCategory(null)}
                  onClick={() => handleItemClick(seg)}
                >
                  <title>{tx("{p0}: {p1}{p2} ({p3}%) - 点击查看对应明细", {p0: (groupBy === 'category' ? categoryLabel(seg.name) : seg.name), p1: '', p2: formatAmount(seg.amount), p3: (seg.percentage)})}</title>
                </circle>
              );
            })}
          </svg>

          {/* Center Text */}
          <div className="absolute inset-0 flex flex-col items-center justify-center pointer-events-none">
            {activeCategory ? (
              (() => {
                const cur = activeItems.find((c) => c.id === activeCategory);
                if (!cur) return null;
                return (
                  <>
                    <span className="text-xs text-zinc-500 font-medium">{groupBy === 'category' ? categoryLabel(cur.name) : cur.name}</span>
                    <span className="text-xl sm:text-2xl font-bold font-mono tracking-tight text-zinc-900 dark:text-zinc-100 mt-0.5">
                      {formatAmount(cur.amount)}
                    </span>
                    <span className="text-xs text-zinc-400 font-mono mt-0.5">{cur.percentage}%</span>
                    <span className="text-[11px] text-zinc-400 mt-1">{tx("点击查看流水")}</span>
                  </>
                );
              })()
            ) : (
              <>
                <span className="text-xs text-zinc-500 font-medium">{tx("总支出")}</span>
                <span className="text-2xl sm:text-3xl font-bold font-mono tracking-tight text-zinc-900 dark:text-zinc-100 mt-1">
                  {formatAmount(total)}
                </span>
              </>
            )}
          </div>
        </div>

        {/* Right: Breakdown Table */}
        <div className="lg:col-span-8 bg-zinc-50/70 dark:bg-zinc-800/40 rounded-2xl p-2.5 border border-zinc-100 dark:border-zinc-800/80 space-y-1">
          {/* Header */}
          <div className="px-3 sm:px-4 py-2 flex items-center justify-between text-xs font-semibold text-zinc-400 uppercase tracking-wider">
            <span className="flex-1 min-w-0 pr-2 sm:pr-4">{groupBy === 'account' ? tx("账户") : tx("分类")} · {activeItems.length}</span>
            <div className="flex items-center gap-2 sm:gap-6 text-right shrink-0">
              <span className="min-w-[80px] sm:w-28 text-right">{tx("金额")}</span>
              <span className="w-11 sm:w-14 text-right">{tx("占比")}</span>
            </div>
          </div>

          <p className="px-3 text-xs text-zinc-500">{tx("金额为扣除退款后的净额；占比按正数分类合计计算，负数表示退款冲抵。")}</p>
          {/* List */}
          <div className="bg-white dark:bg-zinc-900 rounded-xl divide-y divide-zinc-100 dark:divide-zinc-800/70 shadow-2xs border border-zinc-100 dark:border-zinc-800/60">
            {activeItems.length === 0 ? (
              <div className="py-8 px-4 text-center text-xs text-zinc-400">{tx("本期暂无支出数据")}</div>
            ) : (
              activeItems.map((item) => {
              const isHovered = activeCategory === item.id;
              return (
                <div
                  key={item.id}
                  onMouseEnter={() => setActiveCategory(item.id)}
                  onMouseLeave={() => setActiveCategory(null)}
                  onClick={() => handleItemClick(item)}
                  className={`flex items-center justify-between px-3 sm:px-4 py-2.5 sm:py-3 cursor-pointer transition-colors group ${
                    isHovered ? 'bg-zinc-50/90 dark:bg-zinc-800/60' : 'hover:bg-zinc-50/60 dark:hover:bg-zinc-800/40'
                  }`}
                  title={tx("点击查看 {p0} 的交易明细", {p0: (item.name)})}
                >
                  <div className="flex items-center gap-2.5 sm:gap-3 flex-1 min-w-0 pr-2 sm:pr-4">
                    <span
                      className="w-7 h-7 rounded-full flex items-center justify-center text-sm shrink-0 transition-transform group-hover:scale-110"
                      style={{ backgroundColor: `${item.color}15`, color: item.color }}
                    >
                      {item.icon}
                    </span>
                    <div className="flex items-center gap-1.5 truncate min-w-0">
                      <span className="text-xs sm:text-sm font-semibold text-zinc-900 dark:text-zinc-100 group-hover:text-blue-600 dark:group-hover:text-blue-400 transition-colors truncate">
                        {groupBy === 'category' ? categoryLabel(item.name) : item.name}
                      </span>
                      <ChevronRight className="w-3.5 h-3.5 text-zinc-300 opacity-0 group-hover:opacity-100 transition-opacity shrink-0 hidden sm:inline-block" />
                    </div>
                  </div>

                  <div className="flex items-center gap-2 sm:gap-6 text-right shrink-0">
                    <span className="min-w-[80px] sm:w-28 text-right font-mono font-bold text-xs sm:text-sm text-zinc-900 dark:text-zinc-100">
                      {formatAmount(item.amount)}
                    </span>
                    <span className="w-11 sm:w-14 text-right font-mono text-xs sm:text-sm text-zinc-500">
                      {item.amount < 0 ? '—' : `${item.percentage}%`}
                    </span>
                  </div>
                </div>
              );
            }))}
          </div>

          {/* Adjustments (Refund offset) */}
          {adjustments.length > 0 && (
            <div className="pt-2 px-2 text-xs text-zinc-500 space-y-1.5">
              <p className="text-[11px] text-zinc-400">{tx("以下账户本期退款超过支出，已从总支出中扣除")}</p>
              {adjustments.map((adj, idx) => (
                <div
                  key={idx}
                  onClick={handleAdjustmentClick}
                  className="flex items-center justify-between py-1.5 px-2 rounded-lg hover:bg-zinc-100 dark:hover:bg-zinc-800/60 cursor-pointer transition-colors text-xs group"
                  title={tx("点击查看所有退款流水")}
                >
                  <div className="flex items-center gap-1.5">
                    <span className="text-zinc-600 dark:text-zinc-400 group-hover:text-emerald-600 dark:group-hover:text-emerald-400 font-medium">
                      {tx(adj.name)}
                    </span>
                    <ChevronRight className="w-3.5 h-3.5 text-zinc-300 opacity-0 group-hover:opacity-100 transition-opacity" />
                  </div>
                  <span className="font-mono font-medium text-emerald-600 dark:text-emerald-400">
                    {formatAmount(adj.amount)}
                  </span>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
