import React from 'react';
import { ResponsiveContainer, LineChart, Line, XAxis, YAxis, Tooltip } from 'recharts';
import { tx, useLocale } from '../../localization';
import { formatCurrency } from '../../utils/currency';
import { useTheme } from '../../ThemeContext';
import { useCurrency } from '../../CurrencyContext';

function NetWorthChart({ data, currencySymbol }) {
  useLocale();
  const { theme } = useTheme();
  const { privacyMode } = useCurrency();
  const fmt = value => privacyMode ? '••••' : formatCurrency(value, currencySymbol);
  return (
    <ResponsiveContainer width="100%" height="100%">
      <LineChart data={data} margin={{ top: 10, right: 10, left: 10, bottom: 0 }}>
        <XAxis dataKey="date" stroke="#888888" fontSize={11} tickLine={false} axisLine={false} />
        <YAxis hide domain={['dataMin - 1000', 'dataMax + 1000']} />
        <Tooltip formatter={value => [fmt(value), tx('账户净资产')]}
          contentStyle={{ backgroundColor: theme === 'dark' ? '#18181b' : '#ffffff',
            border: '1px solid #27272a', borderRadius: '8px', fontSize: '11px' }} />
        <Line type="monotone" dataKey="value" isAnimationActive={false} stroke="#10b981"
          strokeWidth={2.5} dot={false} activeDot={{ r: 4, fill: '#10b981' }} />
      </LineChart>
    </ResponsiveContainer>
  );
}

export default React.memo(NetWorthChart);
