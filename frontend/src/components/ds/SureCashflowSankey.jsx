import { chartMoney } from '../../utils/chartMoney';
import { categoryLabel, tx, useLocale, currentLocale } from "../../localization.js";
import React, { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useCurrency } from '../../CurrencyContext';

function wrapMobileLabel(text, width, fontSize) {
  const lines = [];
  let line = '', used = 0;
  for (const char of Array.from(text)) {
    const size = fontSize * (char.charCodeAt(0) > 255 ? 1.1 : 0.7);
    if (line && used + size > width) { lines.push(line.trim()); line = ''; used = 0; }
    line += char; used += size;
  }
  if (line) lines.push(line.trim());
  return lines;
}

export default function SureCashflowSankey({
  data,
  currencySymbol: reportSymbol,
  height = 350,
  userFilter = '',
  startDate = '',
  endDate = '',
}) {
  useLocale();
  const { symbol, privacyMode } = useCurrency() || {};
  const currencySymbol = reportSymbol ?? symbol ?? '';
  const formatAmount = value => chartMoney(value, currencySymbol, privacyMode, currentLocale());
  const navigate = useNavigate();
  const [hoveredLink, setHoveredLink] = useState(null);
  const chartRef = React.useRef(null);
  const [chartWidth, setChartWidth] = useState(300);
  const [viewportWidth, setViewportWidth] = useState(() =>
    typeof window === 'undefined' ? 1024 : window.innerWidth
  );
  const isMobile = viewportWidth < 640;
  const titleFontSize = viewportWidth >= 1536 ? 15 : viewportWidth >= 1280 ? 13 : 11;
  const amountFontSize = viewportWidth >= 1536 ? 14 : viewportWidth >= 1280 ? 12 : 11;
  const lineGap = viewportWidth >= 1536 ? 22 : viewportWidth >= 1280 ? 19 : isMobile ? 16 : 15;

  React.useEffect(() => {
    const handleResize = () => setViewportWidth(window.innerWidth);
    window.addEventListener('resize', handleResize);
    return () => window.removeEventListener('resize', handleResize);
  }, []);

  const incomes = Array.isArray(data?.income_sources) ? data.income_sources : [];
  const pool = data?.pool || { name: 'Cash Flow', amount: 0, color: '#10A861' };
  const expenses = Array.isArray(data?.expense_destinations) ? data.expense_destinations : [];
  const hasData = incomes.length > 0 || expenses.length > 0;
  React.useEffect(() => {
    if (!chartRef.current) return;
    const measure = () => { if (chartRef.current?.clientWidth) setChartWidth(chartRef.current.clientWidth); };
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(chartRef.current);
    return () => observer.disconnect();
  }, [hasData]);

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

  const handleExpenseClick = (categoryName) => {
    navigate(buildUrl({ category_name: categoryName, transaction_type: 'expense,refund', spending_net: 'true' }));
  };

  const handleIncomeClick = (categoryName) => {
    if (categoryName) {
      navigate(buildUrl({ transaction_type: 'income', category_name: categoryName }));
    } else {
      navigate(buildUrl({ transaction_type: 'income' }));
    }
  };

  const handlePoolClick = () => {
    navigate(buildUrl({ transaction_type: 'expense,refund', spending_net: 'true' }));
  };

  if (!incomes.length && !expenses.length) {
    return (
      <div className="w-full flex flex-col items-center justify-center py-12 px-4 rounded-xl bg-zinc-50/50 dark:bg-zinc-800/20 border border-dashed border-zinc-200 dark:border-zinc-800 text-center">
        <div className="w-10 h-10 rounded-full bg-zinc-100 dark:bg-zinc-800 flex items-center justify-center text-zinc-400 mb-2">
          💧
        </div>
        <p className="text-sm font-medium text-zinc-600 dark:text-zinc-300">{tx("暂无现金流收支数据")}</p>
        <p className="text-xs text-zinc-400 mt-0.5">{tx("当前筛选周期或家庭成员名下未产生收入或支出流动")}</p>
      </div>
    );
  }

  const numExp = expenses.length || 1;
  const numInc = incomes.length || 1;

  const leftX = isMobile ? 14 : 20;
  const leftNodeW = isMobile ? 12 : 14;
  const poolX = isMobile ? chartWidth / 2 - 6 : 460;
  const poolWidth = isMobile ? 12 : 14;
  const rightX = isMobile ? chartWidth - 26 : 865;
  const rightNodeW = isMobile ? 12 : 14;

  const topPad = isMobile ? 52 : 28;
  const bottomPad = isMobile ? 12 : 40;
  const mobileLabelWidth = Math.max(40, chartWidth * 0.42 - 28);
  const labelLines = (name, icon) => isMobile ? wrapMobileLabel(`${icon} ${categoryLabel(name)}`, mobileLabelWidth, titleFontSize) : [`${icon} ${categoryLabel(name)}`];

  // 自适应初始高度预估
  const baseEstimateHeight = Math.max(
    height || (isMobile ? 240 : 360),
    numExp * (isMobile ? 38 : 56) + topPad + bottomPad,
    numInc * (isMobile ? 44 : 60) + topPad + bottomPad
  );

  const availableRightH = baseEstimateHeight - topPad - bottomPad;

  // 计算每条支出流的等宽带宽 (flowH)，起点终点严格等厚，绝不变宽
  const totalExp = expenses.reduce((s, e) => s + e.amount, 0) || 1;
  const gapRight = Math.max(isMobile ? 8 : 12, Math.min(isMobile ? 14 : 24, (availableRightH * 0.35) / Math.max(1, numExp - 1)));
  const totalExpFlowH = Math.max(isMobile ? 40 : 60, availableRightH - (numExp - 1) * gapRight);

  const expItems = expenses.map((exp, idx) => {
    const fraction = exp.amount / totalExp;
    const flowH = Math.max(isMobile ? 8 : 10, fraction * totalExpFlowH);
    return {
      ...exp,
      id: exp.id || `exp_${idx}`,
      fraction,
      flowH,
      labelLines: labelLines(exp.name, exp.icon || '🍪'),
    };
  });

  // 中间 pool 柱高度与各支出流精确对齐
  const poolH = expItems.reduce((s, e) => s + e.flowH, 0);
  const minExpSlotH = isMobile ? 42 : 46; // 保底单项高度，确保标题+金额两行文字呼吸自然绝对不叠字

  // 先排布右侧支出流，以准确计算支出占用的总跨度并让中间柱垂直居中
  let currentTargetY = topPad;
  expItems.forEach((exp) => {
    exp.targetY = currentTargetY;
    exp.targetH = exp.flowH;
    exp.labelY = isMobile ? exp.targetY + Math.max(titleFontSize, (exp.flowH - (exp.labelLines.length + 1) * lineGap) / 2 + titleFontSize) : exp.targetY + exp.flowH / 2 - 2;
    currentTargetY += Math.max(exp.flowH + gapRight, minExpSlotH, isMobile ? (exp.labelLines.length + 1) * lineGap + 10 : 0);
  });
  const totalExpHeight = currentTargetY - topPad;

  // 中间 pool 柱垂直居中于支出群，移动端顶部留足 Cash Flow 居中标签高度 (>=32px)
  const minPoolY = isMobile ? topPad + 30 : topPad + 12;
  const poolY = Math.max(minPoolY, topPad + (totalExpHeight - poolH) / 2);

  let currentRightPoolY = poolY;
  expItems.forEach((exp) => {
    exp.poolStartY = currentRightPoolY;
    exp.poolH = exp.flowH;
    currentRightPoolY += exp.flowH;
  });

  // 收入流计算 (Left -> Pool): 保证两端等厚流入，绝不变宽
  const totalInc = incomes.reduce((s, i) => s + i.amount, 0) || 1;
  const totalIncFlowH = Math.min(poolH * 0.75, Math.max(36, poolH * (totalInc / (totalExp || 1))));
  const incGap = isMobile ? 12 : 20;
  const minIncSlotH = isMobile ? 42 : 46; // 收入项保底步长，杜绝多项小额收入重叠

  let currentLeftPoolY = poolY;
  // 移动端让收入流贴近顶部 topPad + 4 开始布局，避免顶部出现大块空白
  let currentSourceY = isMobile ? topPad + 4 : Math.max(topPad, poolY - 10);

  const incItems = incomes.map((inc, idx) => {
    const lines = labelLines(inc.name, inc.icon || '💰');
    const fraction = inc.amount / totalInc;
    const flowH = Math.max(isMobile ? 12 : 14, fraction * totalIncFlowH);
    const poolStartY = currentLeftPoolY;
    currentLeftPoolY += flowH;

    const sourceY = currentSourceY;
    currentSourceY += Math.max(flowH + incGap, minIncSlotH, isMobile ? (lines.length + 1) * lineGap + 10 : 0);

    return {
      ...inc,
      id: inc.id || `inc_${idx}`,
      flowH,
      poolStartY,
      poolH: flowH,
      sourceY,
      sourceH: flowH, // 左端与流入端严格等厚！
      labelLines: lines,
    };
  });

  // ── 安全保障：动态检测右侧文字与节点实际占用的最大 Y 坐标，确保绝对不发生截断 ──
  const maxExpContentY = expItems.reduce((max, exp) => {
    const textBottom = exp.labelY + lineGap * exp.labelLines.length + amountFontSize;
    const blockBottom = exp.targetY + exp.targetH;
    return Math.max(max, textBottom, blockBottom);
  }, 0);

  const maxIncContentY = incItems.reduce((max, inc) => {
    const textBottom = inc.sourceY + (isMobile ? 15 : 13) + lineGap * inc.labelLines.length + amountFontSize;
    const blockBottom = inc.sourceY + inc.sourceH;
    return Math.max(max, textBottom, blockBottom);
  }, 0);

  const maxPoolContentY = Math.max(poolY + poolH, poolY + (isMobile ? -3 : 40 + lineGap) + amountFontSize);

  const requiredBottomY = Math.max(maxExpContentY, maxIncContentY, maxPoolContentY) + (isMobile ? 6 : 24);
  const svgWidth = isMobile ? chartWidth : 900;
  const svgHeight = Math.ceil(requiredBottomY);

  return (
    <div ref={chartRef} data-testid="cashflow-sankey" className="w-full max-w-4xl mx-auto relative select-none overflow-visible pb-0">
      <svg
        viewBox={`0 0 ${svgWidth} ${svgHeight}`}
        className="w-full h-auto overflow-visible"
        style={{
          minHeight: `${svgHeight}px`,
        }}
      >
        <defs>
          {/* Gradients for income flows (Sure soft translucent style) */}
          {incItems.map((inc, i) => (
            <linearGradient key={`sankey-grad-inc-${i}`} id={`sankey-grad-inc-${i}`} x1="0%" y1="0%" x2="100%" y2="0%">
              <stop offset="0%" stopColor={inc.color || '#10b981'} stopOpacity={0.25} />
              <stop offset="100%" stopColor="#10A861" stopOpacity={0.20} />
            </linearGradient>
          ))}
          {/* Gradients for expense flows (Sure soft translucent style) */}
          {expItems.map((exp, i) => (
            <linearGradient key={`sankey-grad-exp-${i}`} id={`sankey-grad-exp-${i}`} x1="0%" y1="0%" x2="100%" y2="0%">
              <stop offset="0%" stopColor="#10A861" stopOpacity="0.16" />
              <stop offset="100%" stopColor={exp.color || '#ef4444'} stopOpacity="0.22" />
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

          const pathD = `M ${x0} ${y0_top} C ${cx} ${y0_top}, ${cx} ${y1_top}, ${x1} ${y1_top} L ${x1} ${y1_bot} C ${cx} ${y1_bot}, ${cx} ${y0_bot}, ${x0} ${y0_bot} Z`;

          const isHovered = hoveredLink === `inc-${i}`;

          return (
            <g
              key={`flow-inc-${i}`}
              role="button"
              tabIndex={0}
              className="cursor-pointer group"
              onClick={() => handleIncomeClick(inc.name)}
              onMouseEnter={() => setHoveredLink(`inc-${i}`)}
              onMouseLeave={() => setHoveredLink(null)}
            >
              <title>{tx("{p0}: {p1}{p2} (点击查看【{p3}】收入明细)", {p0: (categoryLabel(inc.name)), p1: '', p2: formatAmount(inc.amount), p3: (categoryLabel(inc.name))})}</title>
              <path
                d={pathD}
                fill={`url(#sankey-grad-inc-${i})`}
                className="transition-opacity duration-200"
                opacity={isHovered ? 0.85 : 0.55}
                pointerEvents="all"
              />

              {/* Left rounded vertical block (Exact 10.jpg) */}
              <rect
                x={leftX}
                y={y0_top}
                width={leftNodeW}
                height={inc.sourceH}
                rx={isMobile ? 5 : 6}
                fill={inc.color || '#10b981'}
                className="transition-all hover:opacity-90"
              />

              {/* Income Label (Next to block) */}
              <text
                x={leftX + leftNodeW + 6}
                y={y0_top + (isMobile ? 15 : 13)}
                data-testid="sankey-node-label"
                style={{ fontSize: titleFontSize }}
                className={`font-bold transition-colors select-none ${
                  isHovered
                    ? 'fill-emerald-600 dark:fill-emerald-400'
                    : 'fill-zinc-900 dark:fill-zinc-100'
                }`}
              >
                {inc.labelLines.map((line, index) => <tspan key={index} x={leftX + leftNodeW + 6} dy={index === 0 ? 0 : lineGap}>{line}</tspan>)}
              </text>
              <text
                x={leftX + leftNodeW + 6}
                y={y0_top + (isMobile ? 15 : 13) + lineGap * inc.labelLines.length}
                data-testid="sankey-node-amount"
                style={{ fontSize: amountFontSize }}
                className="font-mono font-medium fill-zinc-500 dark:fill-zinc-400 select-none"
              >
                {formatAmount(inc.amount)}
              </text>
            </g>
          );
        })}

        {/* ── 2. Expense Flows (Center Pool -> Right Individual Nodes) ── */}
        {expItems.map((exp, i) => {
          const x0 = poolX + poolWidth;
          const y0_top = exp.poolStartY;
          const y0_bot = exp.poolStartY + exp.poolH;
          const x1 = rightX;
          const y1_top = exp.targetY;
          const y1_bot = exp.targetY + exp.targetH;
          const dx = x1 - x0;
          const cx1 = x0 + dx * 0.48;
          const cx2 = x1 - dx * 0.48;

          const pathD = `M ${x0} ${y0_top} C ${cx1} ${y0_top}, ${cx2} ${y1_top}, ${x1} ${y1_top} L ${x1} ${y1_bot} C ${cx2} ${y1_bot}, ${cx1} ${y0_bot}, ${x0} ${y0_bot} Z`;

          const isHovered = hoveredLink === `exp-${i}`;

          return (
            <g
              key={`flow-exp-${i}`}
              className="cursor-pointer group"
              onMouseEnter={() => setHoveredLink(`exp-${i}`)}
              onMouseLeave={() => setHoveredLink(null)}
              onClick={() => handleExpenseClick(exp.name)}
            >
              <path
                d={pathD}
                fill={`url(#sankey-grad-exp-${i})`}
                className="transition-opacity duration-150"
                opacity={isHovered ? 0.85 : 0.50}
                pointerEvents="all"
              >
                <title>{tx("{p0}: {p1}{p2} (点击查看消费明细)", {p0: (categoryLabel(exp.name)), p1: '', p2: formatAmount(exp.amount)})}</title>
              </path>

              {/* Destination label right-aligned before the colored block */}
              <text
                x={rightX - (isMobile ? 8 : 10)}
                y={exp.labelY}
                textAnchor="end"
                data-testid="sankey-node-label"
                style={{ fontSize: titleFontSize }}
                className={`font-bold transition-colors select-none ${
                  isHovered
                    ? 'fill-blue-600 dark:fill-blue-400'
                    : 'fill-zinc-900 dark:fill-zinc-100'
                }`}
              >
                {exp.labelLines.map((line, index) => <tspan key={index} x={rightX - (isMobile ? 8 : 10)} dy={index === 0 ? 0 : lineGap}>{line}</tspan>)}
              </text>
              <text
                x={rightX - (isMobile ? 8 : 10)}
                y={exp.labelY + lineGap * exp.labelLines.length}
                textAnchor="end"
                data-testid="sankey-node-amount"
                style={{ fontSize: amountFontSize }}
                className="font-mono font-medium fill-zinc-500 dark:fill-zinc-400 select-none"
              >
                {formatAmount(exp.amount)}
              </text>

              {/* Right individual rounded vertical block */}
              <rect
                x={rightX}
                y={y1_top}
                width={rightNodeW}
                height={exp.targetH}
                rx={isMobile ? 4 : 5}
                fill={exp.color || '#ef4444'}
                className="transition-opacity hover:opacity-85"
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
            <title>{tx("现金流中枢: 点击查看全部支出流水")}</title>
          </rect>
          {/* Label: 移动端居中置于柱体正上方，桌面端置于柱体右侧 */}
          <text
            x={isMobile ? poolX + poolWidth / 2 : poolX + 18}
            y={isMobile ? 15 : poolY + 40}
            textAnchor={isMobile ? 'middle' : 'start'}
            data-testid="sankey-node-label"
            style={{ fontSize: titleFontSize }}
            className="font-bold fill-zinc-900 dark:fill-zinc-100 select-none"
          >{tx("Cash Flow")}</text>
          <text
            x={isMobile ? poolX + poolWidth / 2 : poolX + 18}
            y={isMobile ? 31 : poolY + 40 + lineGap}
            textAnchor={isMobile ? 'middle' : 'start'}
            data-testid="sankey-node-amount"
            style={{ fontSize: amountFontSize }}
            className="font-mono font-medium fill-zinc-500 dark:fill-zinc-400 select-none"
          >
            {formatAmount(pool.amount)}
          </text>
        </g>
      </svg>
    </div>
  );
}
