import React, { useState } from 'react';
import { useNavigate } from 'react-router-dom';

export default function SureCashflowSankey({
  data,
  currencySymbol = '¥',
  height = 340,
}) {
  const navigate = useNavigate();
  const [hoveredNode, setHoveredNode] = useState(null);
  const [hoveredLink, setHoveredLink] = useState(null);

  const defaultIncomes = [
    { id: 'inc_salary', name: '工资收入', amount: 548.03, icon: '💰', color: '#eab308' }
  ];
  const defaultPool = { name: 'Cash Flow', amount: 2947.65, color: '#10A861' };
  const defaultExpenses = [
    { id: 'exp_other', name: '其他', amount: 1628.10, icon: '🍪', color: '#f97316' },
    { id: 'exp_dining', name: '餐饮美食', amount: 688.55, icon: '🍴', color: '#8b5cf6' },
    { id: 'exp_transfer', name: '个人/转账', amount: 547.30, icon: '👤', color: '#0ea5e9' },
    { id: 'exp_shopping', name: '购物消费', amount: 496.62, icon: '🛍️', color: '#eab308' },
    { id: 'exp_groceries', name: '超市便利', amount: 296.02, icon: '🛒', color: '#10b981' },
    { id: 'exp_utilities', name: '生活缴费', amount: 113.93, icon: '⚡', color: '#ef4444' },
    { id: 'exp_transport', name: '交通出行', amount: 64.66, icon: '🚗', color: '#06b6d4' },
  ];

  const incomes = data?.income_sources?.length ? data.income_sources : defaultIncomes;
  const pool = data?.pool || defaultPool;
  const expenses = data?.expense_destinations?.length ? data.expense_destinations : defaultExpenses;

  // Svg geometry exactly matching 1.png
  const svgWidth = 960;
  const svgHeight = height;

  // 1.png coordinates: Left income starts near edge, Center pool is around 60%, Right terminates near edge
  const leftX = 24;
  const poolX = 575; // Approx 60% like 1.png
  const poolWidth = 8;
  const rightX = 932;
  const rightBarWidth = 6;

  // Pool Height
  const poolH = Math.max(160, Math.min(260, svgHeight - 60));
  const poolY = (svgHeight - poolH) / 2 + 10;

  // Expense destinations distribution
  const totalExp = expenses.reduce((s, e) => s + e.amount, 0) || 1;

  let currentRightPoolY = poolY;
  const expItems = expenses.map((exp, idx) => {
    const fraction = exp.amount / totalExp;
    const h = Math.max(6, fraction * poolH);
    const poolStartY = currentRightPoolY;
    currentRightPoolY += h;

    // Distribute evenly on the right side
    const totalSlots = expenses.length || 1;
    const slotHeight = (svgHeight - 70) / totalSlots;
    const targetY = 32 + idx * slotHeight;
    const targetH = Math.max(5, (h / poolH) * 36);

    return {
      ...exp,
      id: exp.id || `exp_${idx}`,
      poolStartY,
      poolH: h,
      targetY,
      targetH,
    };
  });

  // Income sources distribution
  const totalInc = incomes.reduce((s, i) => s + i.amount, 0) || 1;
  let currentLeftPoolY = poolY + 15;
  const incItems = incomes.map((inc, idx) => {
    const fraction = inc.amount / totalInc;
    const h = Math.max(16, fraction * 55);
    const poolStartY = currentLeftPoolY;
    currentLeftPoolY += h;
    const sourceY = poolY + 25 + idx * 45;

    return {
      ...inc,
      id: inc.id || `inc_${idx}`,
      poolStartY,
      poolH: h,
      sourceY,
      sourceH: 22,
    };
  });

  const handleExpenseClick = (categoryName) => {
    navigate(`/transactions?category_name=${encodeURIComponent(categoryName)}`);
  };

  const handleIncomeClick = () => {
    navigate('/transactions?transaction_type=income');
  };

  const handlePoolClick = () => {
    navigate('/transactions?transaction_type=expense');
  };

  return (
    <div className="w-full relative select-none overflow-hidden">
      <svg
        viewBox={`0 0 ${svgWidth} ${svgHeight}`}
        className="w-full h-auto overflow-visible"
        style={{ maxHeight: height }}
      >
        <defs>
          {/* Gradients for incomes */}
          {incItems.map((inc, i) => (
            <linearGradient key={`grad-inc-${i}`} id={`sankey-grad-inc-${i}`} x1="0%" y1="0%" x2="100%" y2="0%">
              <stop offset="0%" stopColor="#eab308" stopOpacity="0.45" />
              <stop offset="100%" stopColor="#10A861" stopOpacity="0.65" />
            </linearGradient>
          ))}
          {/* Gradients for expenses */}
          {expItems.map((exp, i) => (
            <linearGradient key={`grad-exp-${i}`} id={`sankey-grad-exp-${i}`} x1="0%" y1="0%" x2="100%" y2="0%">
              <stop offset="0%" stopColor="#10A861" stopOpacity="0.25" />
              <stop offset="100%" stopColor={exp.color || '#f97316'} stopOpacity="0.45" />
            </linearGradient>
          ))}
        </defs>

        {/* ── 1. Income Flows (Left Edge -> Center Pool) ── */}
        {incItems.map((inc, i) => {
          const x0 = leftX + 4;
          const y0_top = inc.sourceY;
          const y0_bot = inc.sourceY + inc.sourceH;
          const x1 = poolX;
          const y1_top = inc.poolStartY;
          const y1_bot = inc.poolStartY + inc.poolH;
          const cx = (x0 + x1) / 2;

          const pathD = `
            M ${x0} ${y0_top}
            C ${cx} ${y0_top}, ${cx} ${y1_top}, ${x1} ${y1_top}
            L ${x1} ${y1_bot}
            C ${cx} ${y1_bot}, ${cx} ${y0_bot}, ${x0} ${y0_bot}
            Z
          `;

          const isHovered = hoveredLink === `inc-${i}`;

          return (
            <g key={`flow-inc-${i}`} className="cursor-pointer" onClick={handleIncomeClick}>
              <path
                d={pathD}
                fill={`url(#sankey-grad-inc-${i})`}
                className="transition-opacity duration-200"
                opacity={isHovered ? 0.95 : 0.65}
                onMouseEnter={() => setHoveredLink(`inc-${i}`)}
                onMouseLeave={() => setHoveredLink(null)}
              >
                <title>{`${inc.name}: ${currencySymbol}${inc.amount.toFixed(2)} (点击查看收入流水)`}</title>
              </path>

              {/* Left income vertical bar */}
              <rect
                x={leftX}
                y={y0_top}
                width={4}
                height={inc.sourceH}
                rx={1.5}
                fill="#eab308"
                className="transition-all"
              />

              {/* Left label: Icon + Name on top, Amount below (Matching 1.png) */}
              <text
                x={leftX + 10}
                y={y0_top + 10}
                className="text-[12px] font-medium fill-zinc-800 dark:fill-zinc-200 transition-colors"
              >
                {inc.icon || '💰'} {inc.name}
              </text>
              <text
                x={leftX + 10}
                y={y0_top + 22}
                className="text-[10px] font-mono fill-zinc-400"
              >
                {currencySymbol}{inc.amount.toLocaleString('zh-CN', { minimumFractionDigits: 2 })}
              </text>
            </g>
          );
        })}

        {/* ── 2. Expense Flows (Center Pool -> Right Destinations) ── */}
        {expItems.map((exp, i) => {
          const x0 = poolX + poolWidth;
          const y0_top = exp.poolStartY;
          const y0_bot = exp.poolStartY + exp.poolH;
          const x1 = rightX;
          const y1_top = exp.targetY;
          const y1_bot = exp.targetY + exp.targetH;
          const cx = (x0 + x1) / 2;

          const pathD = `
            M ${x0} ${y0_top}
            C ${cx} ${y0_top}, ${cx} ${y1_top}, ${x1} ${y1_top}
            L ${x1} ${y1_bot}
            C ${cx} ${y1_bot}, ${cx} ${y0_bot}, ${x0} ${y0_bot}
            Z
          `;

          const isHovered = hoveredLink === `exp-${i}` || hoveredNode === exp.id;

          return (
            <g
              key={`flow-exp-${i}`}
              className="cursor-pointer group"
              onClick={() => handleExpenseClick(exp.name)}
            >
              <path
                d={pathD}
                fill={`url(#sankey-grad-exp-${i})`}
                className="transition-all duration-200"
                opacity={isHovered ? 0.95 : 0.55}
                onMouseEnter={() => setHoveredLink(`exp-${i}`)}
                onMouseLeave={() => setHoveredLink(null)}
              >
                <title>{`${exp.name}: ${currencySymbol}${exp.amount.toFixed(2)} (点击穿透查看消费明细)`}</title>
              </path>

              {/* Destination label right-aligned before the red end pillar */}
              <text
                x={rightX - 10}
                y={y1_top + 2}
                textAnchor="end"
                className={`text-[12px] font-medium transition-colors ${
                  isHovered
                    ? 'fill-blue-600 dark:fill-blue-400 font-bold'
                    : 'fill-zinc-800 dark:fill-zinc-200'
                }`}
              >
                {exp.icon || '🍪'} {exp.name}
              </text>
              <text
                x={rightX - 10}
                y={y1_top + 14}
                textAnchor="end"
                className="text-[10px] font-mono fill-zinc-400"
              >
                {currencySymbol}{exp.amount.toLocaleString('zh-CN', { minimumFractionDigits: 2 })}
              </text>

              {/* Small color node right next to red bar */}
              <rect
                x={rightX - 3}
                y={y1_top - 2}
                width={3}
                height={Math.max(8, exp.targetH + 4)}
                rx={1}
                fill={exp.color || '#ef4444'}
              />
            </g>
          );
        })}

        {/* ── 3. Central Cash Flow Pillar (Matching 1.png at ~60%) ── */}
        <g className="cursor-pointer" onClick={handlePoolClick}>
          <rect
            x={poolX}
            y={poolY}
            width={poolWidth}
            height={poolH}
            rx={3}
            fill="#10A861"
            className="transition-transform hover:opacity-90"
          >
            <title>现金流中枢: 点击查看全部支出流水</title>
          </rect>
          {/* Label next to pillar */}
          <text
            x={poolX + 12}
            y={poolY + 22}
            className="text-[12px] font-bold fill-zinc-900 dark:fill-zinc-100 select-none"
          >
            Cash Flow
          </text>
          <text
            x={poolX + 12}
            y={poolY + 35}
            className="text-[11px] font-mono font-medium fill-zinc-500 dark:fill-zinc-400 select-none"
          >
            {currencySymbol}{pool.amount.toLocaleString('zh-CN', { minimumFractionDigits: 2 })}
          </text>
        </g>

        {/* ── 4. Right Vertical End Pillar (Red, Exact 1.png Style) ── */}
        <rect
          x={rightX}
          y={24}
          width={rightBarWidth}
          height={svgHeight - 48}
          rx={3}
          fill="#ef4444"
          opacity={0.85}
          className="select-none pointer-events-none"
        />
      </svg>
    </div>
  );
}
