import { chartMoney } from '../../utils/chartMoney';
import { tx, useLocale, currentLocale } from "../../localization.js";
import React, { useEffect, useRef, useState, useMemo } from 'react';
import { Link } from 'react-router-dom';
import { ListOrdered } from 'lucide-react';
import { useCurrency } from '../../CurrencyContext';
import { usePageViewState } from '../../PageViewContext';
import { layoutMerchantTreemap } from '../../utils/merchantTreemap';

// Keep complete class names in frontend source so Tailwind includes every tile color.
const MERCHANT_TILE_STYLES = [
  'bg-rose-100 border-rose-200 dark:bg-rose-900/50 dark:border-rose-700/70',
  'bg-orange-100 border-orange-200 dark:bg-orange-900/50 dark:border-orange-700/70',
  'bg-emerald-100 border-emerald-200 dark:bg-emerald-900/50 dark:border-emerald-700/70',
  'bg-sky-100 border-sky-200 dark:bg-sky-900/50 dark:border-sky-700/70',
  'bg-violet-100 border-violet-200 dark:bg-violet-900/50 dark:border-violet-700/70',
  'bg-amber-100 border-amber-200 dark:bg-amber-900/50 dark:border-amber-700/70',
  'bg-teal-100 border-teal-200 dark:bg-teal-900/50 dark:border-teal-700/70',
];
const OTHER_TILE_STYLE = 'bg-zinc-200 border-zinc-300 dark:bg-zinc-800 dark:border-zinc-600';

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
  const chartRef = useRef(null);
  const [chartSize, setChartSize] = useState({ width: 500, height: 500 });
  const hasTiles = treemap.length > 0;
  useEffect(() => {
    const element = chartRef.current;
    const measure = () => {
      if (element?.clientWidth > 0 && element.clientHeight > 0) {
        const width = element.clientWidth, height = element.clientHeight;
        setChartSize(previous => previous.width === width && previous.height === height ? previous : { width, height });
      }
    };
    measure();
    const observer = typeof ResizeObserver === 'undefined' ? null : new ResizeObserver(measure);
    if (element) observer?.observe(element);
    window.addEventListener('resize', measure);
    return () => {
      observer?.disconnect();
      window.removeEventListener('resize', measure);
    };
  }, [hasTiles]);
  const tiles = useMemo(() => layoutMerchantTreemap(treemap, chartSize.width, chartSize.height), [treemap, chartSize]);
  const rankingRef = useRef(null);
  const [rankingScroll, setRankingScroll] = usePageViewState(`merchants.scrollTop.${startDate}:${endDate}`, 0);
  useEffect(() => {
    if (rankingRef.current) rankingRef.current.scrollTop = rankingScroll;
  }, [data, rankingScroll]);

  const buildSearchUrl = (merchantName, isOther = false) => {
    const params = new URLSearchParams();
    if (isOther) {
      params.set('merchant_group', 'other');
      params.set('transaction_type', 'expense');
    } else if (merchantName) params.set('search', merchantName);
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
      {/* Amount controls area; row breaks favour horizontal rectangles for names. */}
      <div className="lg:col-span-7 flex flex-col">
        <div
          className="w-full max-w-[520px] p-1.5 rounded-2xl border border-zinc-300 dark:border-zinc-700 bg-zinc-100 dark:bg-zinc-950 overflow-hidden"
          aria-label={tx("商户支出分布图")}
        >
          <div ref={chartRef} data-testid="merchant-treemap" className="relative aspect-square w-full rounded-xl overflow-hidden">
          {tiles.map(({ item, index, x, y, width, height }) => (
            <Link
              key={index}
              data-testid="merchant-treemap-tile"
              to={buildSearchUrl(item.name, item.is_other)}
              style={{ left: `${x / chartSize.width * 100}%`, top: `${y / chartSize.height * 100}%`,
                       width: `${width / chartSize.width * 100}%`, height: `${height / chartSize.height * 100}%` }}
              className={`absolute min-w-0 rounded-md ${width >= 2 && height >= 2 ? 'border' : ''} ${item.is_other ? OTHER_TILE_STYLE : MERCHANT_TILE_STYLES[index % MERCHANT_TILE_STYLES.length]} ${width >= 48 && height >= 26 ? (height < 40 ? 'p-1' : 'p-2') : 'p-0'} flex flex-col justify-between hover:brightness-105 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-blue-500 transition-[filter] duration-150 overflow-hidden group`}
              title={`${item.is_other ? tx(item.name) : item.name} · ${formatAmount(item.amount)}`}
              aria-label={`${item.is_other ? tx(item.name) : item.name} · ${formatAmount(item.amount)}`}
            >
              {width >= 48 && height >= 26 && <p className={`text-[11px] sm:text-xs font-semibold text-zinc-900 dark:text-zinc-100 ${height >= 70 ? 'line-clamp-2' : 'line-clamp-1'} [overflow-wrap:anywhere] leading-snug`}>
                {item.is_other ? tx(item.name) : item.name}
              </p>}
              {width >= 80 && height >= 54 && <p className="text-[11px] sm:text-xs font-bold font-mono text-zinc-700 dark:text-zinc-200 mt-1 truncate">
                {formatAmount(item.amount)}
              </p>}
            </Link>
          ))}
          </div>
        </div>
        <p className="mt-2 text-xs text-zinc-400">{tx("色块面积按商户支出金额占比显示（未扣退款）。")}</p>
      </div>

      {/* ── Right Column: Top 10 Ranking List ── */}
      <div className="lg:col-span-5 rounded-2xl border border-zinc-200/80 dark:border-zinc-800 bg-zinc-50/60 dark:bg-zinc-800/40 p-4 flex flex-col">
        <div className="flex items-center gap-2 mb-3">
          <ListOrdered className="w-4 h-4 text-zinc-500" />
          <h3 className="text-sm font-bold text-zinc-900 dark:text-zinc-100">{tx("商户排行")}</h3>
        </div>

        <div ref={rankingRef} onScroll={(event) => setRankingScroll(event.currentTarget.scrollTop)} className="space-y-1.5 overflow-y-auto max-h-[340px] pr-1">
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
