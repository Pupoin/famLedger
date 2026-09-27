import React, { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { ChevronRight } from 'lucide-react';

export default function SureOutflowsDonut({
  data,
  currencySymbol = '¥',
}) {
  const navigate = useNavigate();
  const [groupBy, setGroupBy] = useState('category'); // 'category' | 'account'
  const [activeCategory, setActiveCategory] = useState(null);

  const defaultCategories = [
    {"id": "cat_other", "name": "其他", "amount": 1628.10, "percentage": 42.5, "color": "#f97316", "icon": "🍪"},
    {"id": "cat_dining", "name": "餐饮美食", "amount": 688.55, "percentage": 18.0, "color": "#8b5cf6", "icon": "🍴"},
    {"id": "cat_transfer", "name": "个人/转账", "amount": 547.30, "percentage": 14.3, "color": "#0ea5e9", "icon": "👤"},
    {"id": "cat_shopping", "name": "购物消费", "amount": 496.62, "percentage": 12.9, "color": "#eab308", "icon": "🛍️"},
    {"id": "cat_groceries", "name": "超市便利", "amount": 296.02, "percentage": 7.7, "color": "#10b981", "icon": "🛒"},
    {"id": "cat_utilities", "name": "生活缴费", "amount": 113.93, "percentage": 3.0, "color": "#ef4444", "icon": "⚡"},
    {"id": "cat_transport", "name": "交通出行", "amount": 64.66, "percentage": 1.7, "color": "#06b6d4", "icon": "🚗"},
  ];

  const total = data?.total ?? 2947.65;
  const categories = data?.categories?.length ? data.categories : defaultCategories;
  const adjustments = data?.adjustments || [
    { name: '待匹配退款调整', amount: -887.54, hint: '以下账户本期退款超过支出，已从总支出中扣除' }
  ];

  // SVG Donut calculation
  const radius = 100;
  const strokeWidth = 14;
  const center = 120;
  const circumference = 2 * Math.PI * radius;

  let accumulatedPercent = 0;
  const segments = categories.map((cat) => {
    const strokeDasharray = `${(cat.percentage / 100) * circumference} ${circumference}`;
    const strokeDashoffset = -((accumulatedPercent / 100) * circumference);
    accumulatedPercent += cat.percentage;
    return {
      ...cat,
      strokeDasharray,
      strokeDashoffset,
    };
  });

  const handleCategoryClick = (catName) => {
    navigate(`/transactions?category_name=${encodeURIComponent(catName)}`);
  };

  const handleAdjustmentClick = () => {
    navigate('/transactions?transaction_type=refund');
  };

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
          >
            按分类
          </button>
          <button
            onClick={() => setGroupBy('account')}
            className={`px-3 py-1 rounded-md transition-all ${
              groupBy === 'account'
                ? 'bg-white dark:bg-zinc-700 text-zinc-900 dark:text-white font-semibold shadow-2xs'
                : 'text-zinc-500 hover:text-zinc-900 dark:hover:text-zinc-200'
            }`}
          >
            按账户
          </button>
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
                  onClick={() => handleCategoryClick(seg.name)}
                >
                  <title>{`${seg.name}: ${currencySymbol}${seg.amount} (${seg.percentage}%) - 点击查看对应明细`}</title>
                </circle>
              );
            })}
          </svg>

          {/* Center Text */}
          <div className="absolute inset-0 flex flex-col items-center justify-center pointer-events-none">
            {activeCategory ? (
              (() => {
                const cur = categories.find((c) => c.id === activeCategory);
                return (
                  <>
                    <span className="text-xs text-zinc-500 font-medium">{cur.name}</span>
                    <span className="text-xl sm:text-2xl font-bold font-mono tracking-tight text-zinc-900 dark:text-zinc-100 mt-0.5">
                      {currencySymbol}{cur.amount.toLocaleString('zh-CN', { minimumFractionDigits: 2 })}
                    </span>
                    <span className="text-xs text-zinc-400 font-mono mt-0.5">{cur.percentage}%</span>
                    <span className="text-[10px] text-zinc-400 mt-1">点击查看流水</span>
                  </>
                );
              })()
            ) : (
              <>
                <span className="text-xs text-zinc-500 font-medium">总支出</span>
                <span className="text-2xl sm:text-3xl font-bold font-mono tracking-tight text-zinc-900 dark:text-zinc-100 mt-1">
                  {currencySymbol}{total.toLocaleString('zh-CN', { minimumFractionDigits: 2 })}
                </span>
              </>
            )}
          </div>
        </div>

        {/* Right: Category Breakdown Table */}
        <div className="lg:col-span-8 bg-zinc-50/70 dark:bg-zinc-800/40 rounded-2xl p-2.5 border border-zinc-100 dark:border-zinc-800/80 space-y-1">
          {/* Header */}
          <div className="px-4 py-2 flex items-center justify-between text-xs font-semibold text-zinc-400 uppercase tracking-wider">
            <span>分类 · {categories.length}</span>
            <div className="flex items-center gap-10">
              <span>金额</span>
              <span className="w-12 text-right">占比</span>
            </div>
          </div>

          {/* List */}
          <div className="bg-white dark:bg-zinc-900 rounded-xl divide-y divide-zinc-100 dark:divide-zinc-800/70 shadow-2xs border border-zinc-100 dark:border-zinc-800/60">
            {categories.map((cat) => {
              const isHovered = activeCategory === cat.id;
              return (
                <div
                  key={cat.id}
                  onMouseEnter={() => setActiveCategory(cat.id)}
                  onMouseLeave={() => setActiveCategory(null)}
                  onClick={() => handleCategoryClick(cat.name)}
                  className={`flex items-center justify-between px-4 py-3 cursor-pointer transition-colors group ${
                    isHovered ? 'bg-zinc-50/90 dark:bg-zinc-800/60' : 'hover:bg-zinc-50/60 dark:hover:bg-zinc-800/40'
                  }`}
                  title={`点击查看 ${cat.name} 的交易明细`}
                >
                  <div className="flex items-center gap-3">
                    <span
                      className="w-7 h-7 rounded-full flex items-center justify-center text-sm shrink-0 transition-transform group-hover:scale-110"
                      style={{ backgroundColor: `${cat.color}15`, color: cat.color }}
                    >
                      {cat.icon}
                    </span>
                    <div className="flex items-center gap-1.5">
                      <span className="text-xs sm:text-sm font-semibold text-zinc-900 dark:text-zinc-100 group-hover:text-blue-600 dark:group-hover:text-blue-400 transition-colors">
                        {cat.name}
                      </span>
                      <ChevronRight className="w-3.5 h-3.5 text-zinc-300 opacity-0 group-hover:opacity-100 transition-opacity" />
                    </div>
                  </div>

                  <div className="flex items-center gap-10 text-right">
                    <span className="text-xs sm:text-sm font-bold font-mono text-zinc-900 dark:text-zinc-100">
                      {currencySymbol}{cat.amount.toLocaleString('zh-CN', { minimumFractionDigits: 2 })}
                    </span>
                    <span className="text-xs sm:text-sm text-zinc-500 font-mono w-12 text-right">
                      {cat.percentage}%
                    </span>
                  </div>
                </div>
              );
            })}
          </div>

          {/* Adjustments (Refund offset) */}
          {adjustments.length > 0 && (
            <div className="pt-2 px-2 text-xs text-zinc-500 space-y-1.5">
              <p className="text-[11px] text-zinc-400">以下账户本期退款超过支出，已从总支出中扣除</p>
              {adjustments.map((adj, idx) => (
                <div
                  key={idx}
                  onClick={handleAdjustmentClick}
                  className="flex items-center justify-between py-1.5 px-2 rounded-lg hover:bg-zinc-100 dark:hover:bg-zinc-800/60 cursor-pointer transition-colors text-xs group"
                  title="点击查看所有退款流水"
                >
                  <div className="flex items-center gap-1.5">
                    <span className="text-zinc-600 dark:text-zinc-400 group-hover:text-emerald-600 dark:group-hover:text-emerald-400 font-medium">
                      {adj.name}
                    </span>
                    <ChevronRight className="w-3.5 h-3.5 text-zinc-300 opacity-0 group-hover:opacity-100 transition-opacity" />
                  </div>
                  <span className="font-mono font-medium text-emerald-600 dark:text-emerald-400">
                    {currencySymbol}{adj.amount.toLocaleString('zh-CN', { minimumFractionDigits: 2 })}
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
