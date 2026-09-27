import React, { useState } from 'react';

export default function SureCashflowSankey({
  data,
  currencySymbol = '¥',
  height = 360,
}) {
  const [hoveredNode, setHoveredNode] = useState(null);
  const [hoveredLink, setHoveredLink] = useState(null);

  const defaultIncomes = [
    { id: 'inc_salary', name: '工资收入', amount: 548.03, icon: '💰', color: '#f59e0b' }
  ];
  const defaultPool = { name: 'Cash Flow', amount: 2814.60, color: '#10A861' };
  const defaultExpenses = [
    { id: 'exp_other', name: '其他', amount: 1383.90, icon: '🍪', color: '#f97316' },
    { id: 'exp_utilities', name: '生活缴费', amount: 126.55, icon: '⚡', color: '#ef4444' },
    { id: 'exp_transfer', name: '个人/转账', amount: 473.78, icon: '👤', color: '#0ea5e9' },
    { id: 'exp_groceries', name: '超市便利', amount: 294.52, icon: '🛒', color: '#10b981' },
    { id: 'exp_transport', name: '交通出行', amount: 62.11, icon: '🚗', color: '#06b6d4' },
    { id: 'exp_shopping', name: '购物消费', amount: 302.59, icon: '🛍️', color: '#eab308' },
  ];

  const incomes = data?.income_sources?.length ? data.income_sources : defaultIncomes;
  const pool = data?.pool || defaultPool;
  const expenses = data?.expense_destinations?.length ? data.expense_destinations : defaultExpenses;

  // Viewbox coordinates
  const svgWidth = 960;
  const svgHeight = height;

  // Layout positions
  // Left: Incomes (X = 40 to 60)
  // Center: Cash Flow Pool (X = 480 to 488)
  // Right: Expenses (X = 920 to 928)
  const leftX = 140;
  const poolX = 490;
  const rightX = 860;
  const poolWidth = 8;
  const rightBarWidth = 8;

  // Calculate layout heights
  const poolH = Math.max(140, Math.min(240, svgHeight - 80));
  const poolY = (svgHeight - poolH) / 2;

  // Total sums
  const totalExp = expenses.reduce((s, e) => s + e.amount, 0);

  // Distribute right items along poolH
  let currentRightPoolY = poolY;
  const expItems = expenses.map((exp, idx) => {
    const fraction = exp.amount / totalExp;
    const h = Math.max(8, fraction * poolH);
    const poolStartY = currentRightPoolY;
    currentRightPoolY += h;

    // Distribute evenly on the right side
    const spacing = (svgHeight - 60) / (expenses.length || 1);
    const targetY = 30 + idx * spacing;
    const targetH = Math.max(6, (h / poolH) * 40);

    return {
      ...exp,
      poolStartY,
      poolH: h,
      targetY,
      targetH,
    };
  });

  // Distribute left items
  const totalInc = incomes.reduce((s, i) => s + i.amount, 0);
  let currentLeftPoolY = poolY + 20;
  const incItems = incomes.map((inc) => {
    const fraction = totalInc > 0 ? inc.amount / totalInc : 1;
    const h = Math.max(14, fraction * 40);
    const poolStartY = currentLeftPoolY;
    currentLeftPoolY += h;
    const sourceY = poolY + 30;

    return {
      ...inc,
      poolStartY,
      poolH: h,
      sourceY,
      sourceH: 14,
    };
  });

  return (
    <div className="w-full relative select-none overflow-hidden">
      <svg
        viewBox={`0 0 ${svgWidth} ${svgHeight}`}
        className="w-full h-auto overflow-visible"
        style={{ maxHeight: height }}
      >
        <defs>
          {/* Gradients for income flow */}
          {incItems.map((inc, i) => (
            <linearGradient key={`grad-inc-${i}`} id={`grad-inc-${i}`} x1="0%" y1="0%" x2="100%" y2="0%">
              <stop offset="0%" stopColor="#f59e0b" stopOpacity="0.4" />
              <stop offset="100%" stopColor="#10A861" stopOpacity="0.5" />
            </linearGradient>
          ))}
          {/* Gradients for expense flows */}
          {expItems.map((exp, i) => (
            <linearGradient key={`grad-exp-${i}`} id={`grad-exp-${i}`} x1="0%" y1="0%" x2="100%" y2="0%">
              <stop offset="0%" stopColor="#10A861" stopOpacity="0.2" />
              <stop offset="100%" stopColor={exp.color} stopOpacity="0.35" />
            </linearGradient>
          ))}
        </defs>

        {/* ── 1. Income Flows (Left -> Center Pool) ── */}
        {incItems.map((inc, i) => {
          const x0 = leftX;
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

          return (
            <g key={`flow-inc-${i}`}>
              <path
                d={pathD}
                fill={`url(#grad-inc-${i})`}
                className="transition-opacity duration-200"
                opacity={hoveredLink === `inc-${i}` ? 0.9 : 0.65}
                onMouseEnter={() => setHoveredLink(`inc-${i}`)}
                onMouseLeave={() => setHoveredLink(null)}
              />
              {/* Income source node and label */}
              <rect
                x={x0 - 4}
                y={y0_top}
                width={4}
                height={inc.sourceH}
                rx={2}
                fill="#f59e0b"
              />
              <text
                x={x0 - 10}
                y={y0_top - 2}
                textAnchor="end"
                className="text-[12px] font-medium fill-zinc-700 dark:fill-zinc-300"
              >
                {inc.icon} {inc.name}
              </text>
              <text
                x={x0 - 10}
                y={y0_top + 12}
                textAnchor="end"
                className="text-[11px] font-mono fill-zinc-400"
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
            <g key={`flow-exp-${i}`}>
              <path
                d={pathD}
                fill={`url(#grad-exp-${i})`}
                className="transition-all duration-200 cursor-pointer"
                opacity={isHovered ? 0.95 : 0.55}
                onMouseEnter={() => setHoveredLink(`exp-${i}`)}
                onMouseLeave={() => setHoveredLink(null)}
              />

              {/* Destination label */}
              <text
                x={x1 - 12}
                y={y1_top - 4}
                textAnchor="end"
                className="text-[12px] font-medium fill-zinc-700 dark:fill-zinc-300"
              >
                {exp.icon} {exp.name}
              </text>
              <text
                x={x1 - 12}
                y={y1_top + 9}
                textAnchor="end"
                className="text-[11px] font-mono fill-zinc-400"
              >
                {currencySymbol}{exp.amount.toLocaleString('zh-CN', { minimumFractionDigits: 2 })}
              </text>
            </g>
          );
        })}

        {/* ── 3. Central Cash Flow Pillar ── */}
        <g>
          <rect
            x={poolX}
            y={poolY}
            width={poolWidth}
            height={poolH}
            rx={4}
            fill="#10A861"
            className="transition-transform"
          />
          <text
            x={poolX + 16}
            y={poolY + 24}
            className="text-[12px] font-bold fill-zinc-900 dark:fill-zinc-100"
          >
            Cash Flow
          </text>
          <text
            x={poolX + 16}
            y={poolY + 38}
            className="text-[11px] font-mono font-medium fill-zinc-500 dark:fill-zinc-400"
          >
            {currencySymbol}{pool.amount.toLocaleString('zh-CN', { minimumFractionDigits: 2 })}
          </text>
        </g>

        {/* ── 4. Right Vertical End Pillar (Red/Destructive) ── */}
        <rect
          x={rightX}
          y={20}
          width={rightBarWidth}
          height={svgHeight - 40}
          rx={4}
          fill="#ef4444"
          opacity={0.8}
        />
      </svg>
    </div>
  );
}
