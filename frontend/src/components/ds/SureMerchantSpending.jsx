import { chartMoney } from '../../utils/chartMoney';
import { tx, useLocale, currentLocale } from "../../localization.js";
import React from 'react';
import { Link } from 'react-router-dom';
import { ListOrdered } from 'lucide-react';
import { useCurrency } from '../../CurrencyContext';

export default function SureMerchantSpending({
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
  const treemap = Array.isArray(data?.treemap) ? data.treemap : [];
  const ranking = Array.isArray(data?.ranking) ? data.ranking : [];

  const buildSearchUrl = (merchantName) => {
    const params = new URLSearchParams();
    if (merchantName) params.set('search', merchantName);
    if (userFilter && userFilter !== '全部' && userFilter !== 'all') {
      params.set('user', userFilter);
    }
    if (startDate) params.set('start_date', startDate);
    if (endDate) params.set('end_date', endDate);
    const q = params.toString();
    return `/transactions${q ? `?${q}` : ''}`;
  };

  if (treemap.length === 0 && ranking.length === 0) {
    return (
      <div className="w-full flex flex-col items-center justify-center py-12 px-4 rounded-xl bg-zinc-50/50 dark:bg-zinc-800/20 border border-dashed border-zinc-200 dark:border-zinc-800 text-center">
        <div className="w-10 h-10 rounded-full bg-zinc-100 dark:bg-zinc-800 flex items-center justify-center text-zinc-400 mb-2">
          🏬
        </div>
        <p className="text-sm font-medium text-zinc-600 dark:text-zinc-300">{tx("暂无商户支出数据")}</p>
        <p className="text-xs text-zinc-400 mt-0.5">{tx("当前筛选周期或家庭成员名下未产生商户消费记录")}</p>
      </div>
    );
  }

  return (
    <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
      {/* ── Left Column: 6x6 CSS Grid Treemap ── */}
      <div className="lg:col-span-7 flex flex-col justify-between">
        <div
          className="h-80 sm:h-96 grid grid-cols-6 grid-rows-6 gap-1.5 p-1 rounded-2xl border border-zinc-200/90 dark:border-zinc-800 bg-zinc-50/50 dark:bg-zinc-900/50 overflow-hidden"
          aria-label={tx("商户支出分布图")}
        >
          {treemap.map((item, idx) => (
            <Link
              key={idx}
              to={buildSearchUrl(item.name)}
              style={{ gridArea: item.placement }}
              className={`rounded-xl border ${item.border} ${item.bg} p-2.5 sm:p-3 flex flex-col justify-between hover:scale-[0.99] transition-transform duration-150 overflow-hidden shadow-2xs group`}
              title={`${item.is_other ? tx(item.name) : item.name} · ${formatAmount(item.amount)}`}
            >
              <p className="text-xs sm:text-sm font-semibold text-zinc-900 dark:text-zinc-100 line-clamp-2 leading-tight">
                {item.is_other ? tx(item.name) : item.name}
              </p>
              <p className="text-xs sm:text-sm font-bold font-mono text-zinc-600 dark:text-zinc-300 mt-1 truncate">
                {formatAmount(item.amount)}
              </p>
            </Link>
          ))}
        </div>
        <p className="mt-2 text-xs text-zinc-400">{tx("方块列示所选时段内各商户的消费支出（未扣退款），面积不表示金额比例。")}</p>
      </div>

      {/* ── Right Column: Top 10 Ranking List ── */}
      <div className="lg:col-span-5 rounded-2xl border border-zinc-200/80 dark:border-zinc-800 bg-zinc-50/60 dark:bg-zinc-800/40 p-4 flex flex-col">
        <div className="flex items-center gap-2 mb-3">
          <ListOrdered className="w-4 h-4 text-zinc-500" />
          <h3 className="text-sm font-bold text-zinc-900 dark:text-zinc-100">{tx("商户排行")}</h3>
        </div>

        <div className="space-y-1.5 overflow-y-auto max-h-[340px] pr-1">
          {ranking.map((item, idx) => (
            <Link
              key={idx}
              to={buildSearchUrl(item.name)}
              className="flex items-center gap-3 p-2 rounded-xl hover:bg-white dark:hover:bg-zinc-800 transition-colors group"
            >
              {/* Badge */}
              <span
                className={`w-6 h-6 shrink-0 rounded-full flex items-center justify-center text-xs font-bold ${
                  item.rank <= 3
                    ? 'bg-amber-100 dark:bg-amber-950/60 text-amber-700 dark:text-amber-400'
                    : 'bg-zinc-100 dark:bg-zinc-700 text-zinc-500 dark:text-zinc-300'
                }`}
              >
                {item.rank}
              </span>

              {/* Merchant Details */}
              <div className="min-w-0 flex-1">
                <p
                  className="text-xs sm:text-sm font-medium text-zinc-900 dark:text-zinc-100 truncate group-hover:text-blue-600 dark:group-hover:text-blue-400"
                  title={item.name}
                >
                  {item.name}
                </p>
                <p className="text-[11px] text-zinc-400 truncate mt-0.5">
                  {item.count} {tx("笔交易 · 平均")} {formatAmount(item.average)}
                </p>
              </div>

              {/* Amount */}
              <span className="text-xs sm:text-sm font-bold font-mono text-zinc-900 dark:text-zinc-100 shrink-0 text-right">
                {formatAmount(item.amount)}
              </span>
            </Link>
          ))}
        </div>
      </div>
    </div>
  );
}
