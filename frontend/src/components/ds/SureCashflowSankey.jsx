import React, { useState } from 'react';
import { useNavigate } from 'react-router-dom';

export default function SureCashflowSankey({
  data,
  currencySymbol = '¥',
  height = 350,
}) {
  const navigate = useNavigate();
  const [hoveredLink, setHoveredLink] = useState(null);
  const [isMobile, setIsMobile] = useState(() => {
    if (typeof window !== 'undefined') {
      return window.innerWidth < 640;
    }
    return false;
  });

  React.useEffect(() => {
    const handleResize = () => {
      setIsMobile(window.innerWidth < 640);
    };
    window.addEventListener('resize', handleResize);
    return () => window.removeEventListener('resize', handleResize);
  }, []);

  const defaultIncomes = [
    { id: 'inc_salary', name: '工资收入', amount: 540.03, icon: '💰', color: '#eab308' }
  ];
  const defaultPool = { name: 'Cash Flow', amount: 2814.60, color: '#10A861' };
  const defaultExpenses = [
    { id: 'exp_other', name: '其他', amount: 1383.90, icon: '🍪', color: '#ef4444' },
    { id: 'exp_utilities', name: '生活缴费', amount: 126.55, icon: '⚡', color: '#f97316' },
    { id: 'exp_transfer', name: '个人/转账', amount: 473.78, icon: '👤', color: '#f59e0b' },
    { id: 'exp_groceries', name: '超市便利', amount: 294.52, icon: '🛒', color: '#10b981' },
    { id: 'exp_transport', name: '交通出行', amount: 62.11, icon: '🚗', color: '#06b6d4' },
    { id: 'exp_shopping', name: '购物消费', amount: 302.59, icon: '🛍️', color: '#8b5cf6' },
  ];

  const incomes = data?.income_sources?.length ? data.income_sources : defaultIncomes;
  const pool = data?.pool || defaultPool;
  const expenses = data?.expense_destinations?.length ? data.expense_destinations : defaultExpenses;

  // Svg geometry matching 10.jpg for mobile and 1.png for desktop
  const svgWidth = isMobile ? 380 : 900;
  const svgHeight = isMobile ? 440 : height;

  const leftX = isMobile ? 14 : 20;
  const leftNodeW = isMobile ? 12 : 14;
  const poolX = isMobile ? 180 : 460;
  const poolWidth = isMobile ? 12 : 14;
  const rightX = isMobile ? 354 : 865;
  const rightNodeW = isMobile ? 12 : 14;

  // Calculate layout heights
  const poolH = isMobile ? 300 : Math.max(180, Math.min(270, svgHeight - 60));
  const poolY = isMobile ? 65 : (svgHeight - poolH) / 2 + 10;

  // Expense destinations distribution
  const totalExp = expenses.reduce((s, e) => s + e.amount, 0) || 1;

  let currentRightPoolY = poolY;
  const expItems = expenses.map((exp, idx) => {
    const fraction = exp.amount / totalExp;
    const h = Math.max(8, fraction * poolH);
    const poolStartY = currentRightPoolY;
    currentRightPoolY += h;

    // Distribute right destination nodes
    const totalSlots = expenses.length || 1;
    const slotH = (svgHeight - (isMobile ? 50 : 60)) / totalSlots;
    const targetY = (isMobile ? 20 : 24) + idx * slotH;
    const targetH = isMobile
      ? Math.max(16, Math.min(60, fraction * 150))
      : Math.max(12, Math.min(56, fraction * 140));

    return {
      ...exp,
      id: exp.id || `exp_${idx}`,
      poolStartY,
      poolH: h,
      targetY,
      targetH,
    };
  });

  // Income sources distribution (flow to top half of pool like 10.jpg)
  const totalInc = incomes.reduce((s, i) => s + i.amount, 0) || 1;
  let currentLeftPoolY = poolY;
  const incItems = incomes.map((inc, idx) => {
    const fraction = inc.amount / totalInc;
    const h = Math.max(18, fraction * (poolH * 0.45));
    const poolStartY = currentLeftPoolY;
    currentLeftPoolY += h;
    const sourceY = isMobile ? 80 + idx * 56 : poolY + idx * 52;
    const sourceH = isMobile ? 38 : Math.max(24, Math.min(48, fraction * 48));

    return {
      ...inc,
      id: inc.id || `inc_${idx}`,
      poolStartY,
      poolH: h,
      sourceY,
      sourceH,
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
        style={{
          maxHeight: isMobile ? undefined : height,
          minHeight: isMobile ? '380px' : undefined,
        }}
      >
        <defs>
          {/* Gradients for income flows */}
          {incItems.map((inc, i) => (
            <linearGradient key={`sankey-grad-inc-${i}`} id={`sankey-grad-inc-${i}`} x1="0%" y1="0%" x2="100%" y2="0%">
              <stop offset="0%" stopColor="#eab308" stopOpacity="0.4" />
              <stop offset="100%" stopColor="#10A861" stopOpacity="0.55" />
            </linearGradient>
          ))}
          {/* Gradients for expense flows (Exact smooth flows in 10.jpg) */}
          {expItems.map((exp, i) => (
            <linearGradient key={`sankey-grad-exp-${i}`} id={`sankey-grad-exp-${i}`} x1="0%" y1="0%" x2="100%" y2="0%">
              <stop offset="0%" stopColor="#10A861" stopOpacity="0.3" />
              <stop offset="100%" stopColor={exp.color || '#ef4444'} stopOpacity="0.45" />
            </linearGradient>
          ))}
        </defs>

        {/* ── 1. Income Flows (Left Node -> Center Pool) ── */}
        {incItems.map((inc, i) => {
          const x0 = leftX + leftNodeW;
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

              {/* Left rounded vertical block (Exact 10.jpg) */}
              <rect
                x={leftX}
                y={y0_top}
                width={leftNodeW}
                height={inc.sourceH}
                rx={isMobile ? 5 : 6}
                fill="#eab308"
                className="transition-all"
              />

              {/* Income Label (Next to block) */}
              <text
                x={leftX + leftNodeW + 6}
                y={y0_top + (isMobile ? 15 : 13)}
                className="text-[12px] sm:text-[13px] font-semibold fill-zinc-800 dark:fill-zinc-200"
              >
                {inc.icon || '💰'} {inc.name}
              </text>
              <text
                x={leftX + leftNodeW + 6}
                y={y0_top + (isMobile ? 30 : 28)}
                className="text-[10.5px] sm:text-[11px] font-mono font-medium fill-zinc-400"
              >
                {currencySymbol}{inc.amount.toLocaleString('zh-CN', { minimumFractionDigits: 2 })}
              </text>
            </g>
          );
        })}

        {/* ── 2. Expense Flows (Center Pool -> Right Individual Nodes, Exact 10.jpg) ── */}
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

          const isHovered = hoveredLink === `exp-${i}`;

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
                <title>{`${exp.name}: ${currencySymbol}${exp.amount.toFixed(2)} (点击查看消费明细)`}</title>
              </path>

              {/* Destination label right-aligned before the colored block */}
              <text
                x={rightX - (isMobile ? 8 : 10)}
                y={y1_top + (exp.targetH > 24 ? 12 : 6)}
                textAnchor="end"
                className={`text-[12px] sm:text-[13px] font-semibold transition-colors ${
                  isHovered
                    ? 'fill-blue-600 dark:fill-blue-400 font-bold'
                    : 'fill-zinc-800 dark:fill-zinc-200'
                }`}
              >
                {exp.icon || '🍪'} {exp.name}
              </text>
              <text
                x={rightX - (isMobile ? 8 : 10)}
                y={y1_top + (exp.targetH > 24 ? 27 : 20)}
                textAnchor="end"
                className="text-[10.5px] sm:text-[11px] font-mono font-medium fill-zinc-400"
              >
                {currencySymbol}{exp.amount.toLocaleString('zh-CN', { minimumFractionDigits: 2 })}
              </text>

              {/* Right individual rounded vertical block (Exact 10.jpg) */}
              <rect
                x={rightX}
                y={y1_top}
                width={rightNodeW}
                height={exp.targetH}
                rx={isMobile ? 4 : 5}
                fill={exp.color || '#ef4444'}
                className="transition-transform group-hover:scale-105"
              />
            </g>
          );
        })}

        {/* ── 3. Central Cash Flow Pillar (Matching 10.jpg) ── */}
        <g className="cursor-pointer" onClick={handlePoolClick}>
          <rect
            x={poolX}
            y={poolY}
            width={poolWidth}
            height={poolH}
            rx={5}
            fill="#10A861"
            className="transition-transform hover:opacity-90"
          >
            <title>现金流中枢: 点击查看全部支出流水</title>
          </rect>
          {/* Label next to pillar (In 10.jpg mobile, Cash Flow is to the LEFT of the pillar at the bottom half!) */}
          <text
            x={isMobile ? poolX - 8 : poolX + 18}
            y={isMobile ? poolY + poolH * 0.58 : poolY + 40}
            textAnchor={isMobile ? 'end' : 'start'}
            className="text-[12px] sm:text-[13px] font-bold fill-zinc-900 dark:fill-zinc-100 select-none"
          >
            Cash Flow
          </text>
          <text
            x={isMobile ? poolX - 8 : poolX + 18}
            y={isMobile ? poolY + poolH * 0.58 + 16 : poolY + 56}
            textAnchor={isMobile ? 'end' : 'start'}
            className="text-[11px] sm:text-[12px] font-mono font-semibold fill-zinc-600 dark:fill-zinc-200 select-none"
          >
            {currencySymbol}{pool.amount.toLocaleString('zh-CN', { minimumFractionDigits: 2 })}
          </text>
        </g>
      </svg>
    </div>
  );
}
