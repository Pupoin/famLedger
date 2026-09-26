import React, { useMemo } from 'react';
import {
  ResponsiveContainer,
  AreaChart,
  Area,
  XAxis,
  YAxis,
  Tooltip,
  BarChart,
  Bar,
  PieChart,
  Pie,
  Cell,
} from 'recharts';

// ── Sure Design System Chart Colors ─────────────────────────
export const SURE_COLORS = [
  '#10B981', // Emerald
  '#3B82F6', // Blue
  '#F59E0B', // Amber
  '#EC4899', // Pink
  '#8B5CF6', // Purple
  '#06B6D4', // Cyan
  '#F97316', // Orange
  '#64748B', // Slate
];

// ── 1. Sure Spending Trend Area Chart (平滑收支趋势图) ───────
export function SureAreaChart({ data, currencySymbol = '¥', height = 280 }) {
  if (!data || data.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center h-64 text-on-surface-variant text-sm">
        暂无趋势走势数据
      </div>
    );
  }

  return (
    <div style={{ width: '100%', height }}>
      <ResponsiveContainer width="100%" height="100%">
        <AreaChart data={data} margin={{ top: 12, right: 12, left: -20, bottom: 0 }}>
          <defs>
            <linearGradient id="sureTrendGradient" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="#10B981" stopOpacity={0.25} />
              <stop offset="95%" stopColor="#10B981" stopOpacity={0.0} />
            </linearGradient>
          </defs>
          <XAxis
            dataKey="label"
            stroke="#94A3B8"
            fontSize={11}
            tickLine={false}
            axisLine={{ stroke: '#E2E8F0', strokeOpacity: 0.2 }}
            dy={8}
          />
          <YAxis
            stroke="#94A3B8"
            fontSize={11}
            tickLine={false}
            axisLine={false}
            tickFormatter={(val) => `${currencySymbol}${val >= 1000 ? (val / 1000).toFixed(1) + 'k' : val}`}
          />
          <Tooltip
            content={({ active, payload, label }) => {
              if (active && payload && payload.length) {
                const val = payload[0].value;
                return (
                  <div className="bg-surface-container-lowest/95 backdrop-blur-md px-3.5 py-2.5 rounded-xl shadow-lg border border-outline/10 text-xs font-sans">
                    <p className="text-on-surface-variant mb-1 font-medium">{label}</p>
                    <p className="text-sm font-bold text-on-surface font-mono">
                      {currencySymbol}{Number(val).toFixed(2)}
                    </p>
                  </div>
                );
              }
              return null;
            }}
          />
          <Area
            type="monotone"
            dataKey="amount"
            stroke="#10B981"
            strokeWidth={2.5}
            fillOpacity={1}
            fill="url(#sureTrendGradient)"
            dot={{ r: 3, fill: '#10B981', strokeWidth: 2, stroke: '#FFFFFF' }}
            activeDot={{ r: 6, fill: '#10B981', strokeWidth: 2, stroke: '#FFFFFF' }}
          />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
}

// ── 2. Sure Category Donut Chart (中心大字环形分类图) ────────
export function SureDonutChart({ data, totalAmount = 0, currencySymbol = '¥', height = 300 }) {
  const chartData = useMemo(() => {
    return (data || []).filter((d) => Number(d.amount) > 0);
  }, [data]);

  const total = useMemo(() => {
    if (totalAmount) return Number(totalAmount);
    return chartData.reduce((sum, item) => sum + Number(item.amount), 0);
  }, [chartData, totalAmount]);

  if (chartData.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center h-64 text-on-surface-variant text-sm">
        暂无分类统计数据
      </div>
    );
  }

  return (
    <div className="flex flex-col md:flex-row items-center gap-6">
      {/* Donut Container with Centered Total */}
      <div className="relative shrink-0" style={{ width: 220, height: 220 }}>
        <ResponsiveContainer width="100%" height="100%">
          <PieChart>
            <Pie
              data={chartData}
              innerRadius={72}
              outerRadius={98}
              paddingAngle={3}
              dataKey="amount"
              cornerRadius={4}
            >
              {chartData.map((entry, index) => (
                <Cell
                  key={`cell-${index}`}
                  fill={SURE_COLORS[index % SURE_COLORS.length]}
                  stroke="none"
                />
              ))}
            </Pie>
            <Tooltip
              content={({ active, payload }) => {
                if (active && payload && payload.length) {
                  const item = payload[0].payload;
                  const pct = total > 0 ? ((item.amount / total) * 100).toFixed(1) : 0;
                  return (
                    <div className="bg-surface-container-lowest/95 backdrop-blur-md px-3 py-2 rounded-xl shadow-lg border border-outline/10 text-xs">
                      <p className="font-semibold text-on-surface">{item.category}</p>
                      <p className="font-mono text-primary font-bold mt-0.5">
                        {currencySymbol}{Number(item.amount).toFixed(2)} ({pct}%)
                      </p>
                    </div>
                  );
                }
                return null;
              }}
            />
          </PieChart>
        </ResponsiveContainer>

        {/* Centered Total Overlay */}
        <div className="absolute inset-0 flex flex-col items-center justify-center pointer-events-none select-none text-center">
          <span className="text-[11px] font-semibold text-on-surface-variant uppercase tracking-wider">
            当期总计
          </span>
          <span className="text-lg font-bold text-on-surface font-mono tracking-tight">
            {currencySymbol}{total.toFixed(2)}
          </span>
        </div>
      </div>

      {/* Category Pills & Legend List */}
      <div className="flex-1 w-full grid grid-cols-1 sm:grid-cols-2 gap-2.5">
        {chartData.map((item, idx) => {
          const color = SURE_COLORS[idx % SURE_COLORS.length];
          const pct = total > 0 ? ((Number(item.amount) / total) * 100).toFixed(1) : 0;
          return (
            <div
              key={item.category}
              className="flex items-center justify-between p-2.5 rounded-xl bg-surface-container-low/60 hover:bg-surface-container border border-outline/5 transition-colors"
            >
              <div className="flex items-center gap-2.5 min-w-0">
                <span
                  className="w-2.5 h-2.5 rounded-full shrink-0"
                  style={{ backgroundColor: color }}
                />
                <span className="text-xs font-semibold text-on-surface truncate">
                  {item.category}
                </span>
              </div>

              <div className="flex items-center gap-2 shrink-0">
                <span className="text-xs font-mono font-bold text-on-surface">
                  {currencySymbol}{Number(item.amount).toFixed(2)}
                </span>
                <span className="text-[10px] font-mono px-1.5 py-0.5 rounded-md bg-surface-container font-semibold text-on-surface-variant">
                  {pct}%
                </span>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ── 3. Sure Money Flow Bar Chart (收支双柱对比图) ───────────
export function SureMoneyFlowChart({ data, currencySymbol = '¥', height = 280 }) {
  if (!data || data.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center h-64 text-on-surface-variant text-sm">
        暂无月度对比数据
      </div>
    );
  }

  return (
    <div style={{ width: '100%', height }}>
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={data} margin={{ top: 12, right: 12, left: -20, bottom: 0 }} barGap={6}>
          <XAxis
            dataKey="month"
            stroke="#94A3B8"
            fontSize={11}
            tickLine={false}
            axisLine={{ stroke: '#E2E8F0', strokeOpacity: 0.2 }}
            dy={8}
          />
          <YAxis
            stroke="#94A3B8"
            fontSize={11}
            tickLine={false}
            axisLine={false}
            tickFormatter={(val) => `${currencySymbol}${val >= 1000 ? (val / 1000).toFixed(1) + 'k' : val}`}
          />
          <Tooltip
            content={({ active, payload, label }) => {
              if (active && payload && payload.length) {
                return (
                  <div className="bg-surface-container-lowest/95 backdrop-blur-md px-3.5 py-2.5 rounded-xl shadow-lg border border-outline/10 text-xs">
                    <p className="text-on-surface-variant mb-1 font-semibold">{label}</p>
                    {payload.map((entry) => (
                      <div key={entry.name} className="flex items-center justify-between gap-4 font-mono">
                        <span className="text-on-surface-variant">{entry.name}:</span>
                        <span className="font-bold text-on-surface">
                          {currencySymbol}{Number(entry.value).toFixed(2)}
                        </span>
                      </div>
                    ))}
                  </div>
                );
              }
              return null;
            }}
          />
          <Bar
            dataKey="expense"
            name="支出"
            fill="#EF4444"
            radius={[4, 4, 0, 0]}
            maxBarSize={32}
          />
          <Bar
            dataKey="income"
            name="收入/退款"
            fill="#10B981"
            radius={[4, 4, 0, 0]}
            maxBarSize={32}
          />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}
