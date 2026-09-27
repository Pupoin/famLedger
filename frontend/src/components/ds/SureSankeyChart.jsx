import React, { useMemo } from 'react';
import { ResponsiveContainer, Sankey, Tooltip } from 'recharts';
import { useTheme } from '../../ThemeContext';

export default function SureSankeyChart({
  data,
  accounts = [],
  monthlySummary = [],
  currencySymbol = '¥',
  height = 320,
}) {
  const { theme } = useTheme();
  const isDark = theme === 'dark';

  // Build Sankey Nodes & Links
  const sankeyData = useMemo(() => {
    // If external structured data is passed
    if (data && data.nodes && data.links && data.links.length > 0) {
      return data;
    }

    // Otherwise construct intelligent cashflow from accounts & categories
    // Left: Source Accounts (Cash & Cards)
    const validAccounts = (accounts || [])
      .filter((a) => (a.transaction_count || 0) > 0)
      .slice(0, 5);

    // Right: Destination Categories
    const validCategories = (monthlySummary || [])
      .filter((c) => c.category !== 'Payment' && c.category !== 'Reimbursement' && c.amount > 0)
      .sort((a, b) => b.amount - a.amount)
      .slice(0, 6);

    if (validAccounts.length === 0 || validCategories.length === 0) {
      return {
        nodes: [
          { name: '招商银行借记卡 *7931' },
          { name: '招商银行借记卡 *2238' },
          { name: '招商银行信用卡 *8866' },
          { name: '餐饮美食' },
          { name: '生活日用' },
          { name: '数码电器' },
          { name: '结余储蓄' },
        ],
        links: [
          { source: 0, target: 3, value: 540 },
          { source: 0, target: 4, value: 280 },
          { source: 1, target: 3, value: 310 },
          { source: 1, target: 5, value: 650 },
          { source: 2, target: 3, value: 180 },
          { source: 0, target: 6, value: 1200 },
        ],
      };
    }

    const nodes = [];
    const sourceCount = validAccounts.length;

    validAccounts.forEach((acc) => {
      nodes.push({ name: `${acc.institution_name} *${acc.mask}` });
    });

    validCategories.forEach((cat) => {
      nodes.push({ name: cat.category });
    });

    const links = [];
    const totalCatAmt = validCategories.reduce((s, c) => s + c.amount, 0);

    validAccounts.forEach((acc, aIdx) => {
      const accWeight = (acc.transaction_count || 1);
      validCategories.forEach((cat, cIdx) => {
        const val = parseFloat(((cat.amount * accWeight) / (sourceCount * 1.5)).toFixed(2));
        if (val > 0) {
          links.push({
            source: aIdx,
            target: sourceCount + cIdx,
            value: Math.max(val, 10),
          });
        }
      });
    });

    return { nodes, links };
  }, [data, accounts, monthlySummary]);

  // Color palette for nodes
  const nodeColors = [
    '#10b981', '#3b82f6', '#f59e0b', '#8b5cf6', '#ec4899', '#06b6d4',
    '#14b8a6', '#6366f1', '#f43f5e', '#84cc16'
  ];

  return (
    <div className="w-full flex flex-col justify-center" style={{ height }}>
      <ResponsiveContainer width="100%" height="100%">
        <Sankey
          data={sankeyData}
          nodePadding={24}
          nodeWidth={12}
          margin={{ left: 150, right: 140, top: 20, bottom: 20 }}
          link={{ stroke: isDark ? 'rgba(255, 255, 255, 0.12)' : 'rgba(0, 0, 0, 0.08)' }}
          node={({ x, y, width, height, index, payload }) => {
            const color = nodeColors[index % nodeColors.length];
            // Left column has sourceLinks, right column has targetLinks
            const isLeft = payload.sourceLinks && payload.sourceLinks.length > 0;
            return (
              <g>
                <rect
                  x={x}
                  y={y}
                  width={width}
                  height={height}
                  fill={color}
                  fillOpacity={0.85}
                  rx={3}
                />
                <text
                  x={isLeft ? x - 10 : x + width + 10}
                  y={y + height / 2}
                  textAnchor={isLeft ? 'end' : 'start'}
                  dominantBaseline="middle"
                  fill={isDark ? '#e4e4e7' : '#27272a'}
                  fontSize={12}
                  fontWeight={500}
                >
                  {payload.name}
                </text>
              </g>
            );
          }}
        >
          <Tooltip
            content={({ active, payload }) => {
              if (active && payload && payload.length) {
                const item = payload[0];
                return (
                  <div className="bg-white dark:bg-zinc-800 border border-zinc-200 dark:border-zinc-700 px-3 py-2 rounded-xl shadow-lg text-xs">
                    <span className="font-semibold text-zinc-900 dark:text-zinc-100 block">
                      {item.payload.source?.name} → {item.payload.target?.name}
                    </span>
                    <span className="font-mono text-emerald-600 dark:text-emerald-400 font-bold block mt-0.5">
                      {currencySymbol}{item.value?.toLocaleString()}
                    </span>
                  </div>
                );
              }
              return null;
            }}
          />
        </Sankey>
      </ResponsiveContainer>
    </div>
  );
}
