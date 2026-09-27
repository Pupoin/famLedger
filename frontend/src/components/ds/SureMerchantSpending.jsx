import React from 'react';
import { Link } from 'react-router-dom';
import { ListOrdered } from 'lucide-react';

export default function SureMerchantSpending({
  data,
  currencySymbol = '¥',
}) {
  const defaultTreemap = [
    { name: 'GOOGLE*CHATGPT TOKYO JP', amount: 1037.25, placement: '1 / 1 / 5 / 4', bg: 'bg-red-100/70 dark:bg-red-950/30', border: 'border-red-200 dark:border-red-900/50' },
    { name: '财付通-微信支付-微信转账快捷', amount: 466.00, placement: '1 / 4 / 4 / 6', bg: 'bg-orange-100/70 dark:bg-orange-950/30', border: 'border-orange-200 dark:border-orange-900/50' },
    { name: '支付宝-上海拉扎斯信息科技有限公司快捷', amount: 173.80, placement: '1 / 6 / 4 / 7', bg: 'bg-emerald-100/70 dark:bg-emerald-950/30', border: 'border-emerald-200 dark:border-emerald-900/50' },
    { name: '支付宝-老北京地摊烧烤东北小馆快捷', amount: 168.00, placement: '4 / 4 / 7 / 5', bg: 'bg-red-50/70 dark:bg-red-950/20', border: 'border-red-200 dark:border-red-900/40' },
    { name: '财付通-微信支付-京东商城平台商户快捷', amount: 161.86, placement: '4 / 5 / 7 / 7', bg: 'bg-orange-50/70 dark:bg-orange-950/20', border: 'border-orange-200 dark:border-orange-900/40' },
    { name: '抖音支付-环胜电子商务（上海）有限公司快捷', amount: 94.70, placement: '5 / 1 / 7 / 2', bg: 'bg-emerald-50/70 dark:bg-emerald-950/20', border: 'border-emerald-200 dark:border-emerald-900/40' },
    { name: '银联扣款', amount: 90.86, placement: '5 / 2 / 7 / 3', bg: 'bg-zinc-50 dark:bg-zinc-800/60', border: 'border-zinc-200 dark:border-zinc-700' },
    { name: '其他', amount: 1278.99, placement: '5 / 3 / 7 / 4', bg: 'bg-zinc-50 dark:bg-zinc-800/60', border: 'border-zinc-200 dark:border-zinc-700' },
  ];

  const defaultRanking = [
    { rank: 1, name: 'GOOGLE*CHATGPT TOKYO JP', count: 3, average: 345.75, amount: 1037.25 },
    { rank: 2, name: '财付通-微信支付-微信转账快捷', count: 4, average: 116.50, amount: 466.00 },
    { rank: 3, name: '支付宝-上海拉扎斯信息科技有限公司快捷', count: 1, average: 168.00, amount: 173.80 },
    { rank: 4, name: '支付宝-老北京地摊烧烤东北小馆快捷', count: 1, average: 168.00, amount: 168.00 },
    { rank: 5, name: '财付通-微信支付-京东商城平台商户快捷', count: 7, average: 23.12, amount: 161.86 },
    { rank: 6, name: '抖音支付-环胜电子商务（上海）有限公司快捷', count: 3, average: 31.57, amount: 94.70 },
    { rank: 7, name: '银联扣款', count: 4, average: 22.72, amount: 90.86 },
    { rank: 8, name: '抖音支付-北京京东润源邻居酒家快捷', count: 1, average: 89.00, amount: 89.00 },
    { rank: 9, name: '北京自来水-一网通', count: 1, average: 84.00, amount: 84.00 },
    { rank: 10, name: '支付宝-好蔬果生鲜超市快捷', count: 2, average: 40.17, amount: 80.33 },
  ];

  const treemap = data?.treemap?.length ? data.treemap : defaultTreemap;
  const ranking = data?.ranking?.length ? data.ranking : defaultRanking;

  return (
    <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
      {/* ── Left Column: 6x6 CSS Grid Treemap ── */}
      <div className="lg:col-span-7 flex flex-col justify-between">
        <div
          className="h-80 sm:h-96 grid grid-cols-6 grid-rows-6 gap-1.5 p-1 rounded-2xl border border-zinc-200/90 dark:border-zinc-800 bg-zinc-50/50 dark:bg-zinc-900/50 overflow-hidden"
          aria-label="商户支出分布图"
        >
          {treemap.map((item, idx) => (
            <Link
              key={idx}
              to={`/transactions?search=${encodeURIComponent(item.name)}`}
              style={{ gridArea: item.placement }}
              className={`rounded-xl border ${item.border} ${item.bg} p-2.5 sm:p-3 flex flex-col justify-between hover:scale-[0.99] transition-transform duration-150 overflow-hidden shadow-2xs group`}
              title={`${item.name} · ${currencySymbol}${item.amount.toLocaleString('zh-CN', { minimumFractionDigits: 2 })}`}
            >
              <p className="text-xs sm:text-sm font-semibold text-zinc-900 dark:text-zinc-100 line-clamp-2 leading-tight">
                {item.name}
              </p>
              <p className="text-xs sm:text-sm font-bold font-mono text-zinc-600 dark:text-zinc-300 mt-1 truncate">
                {currencySymbol}{item.amount.toLocaleString('zh-CN', { minimumFractionDigits: 2 })}
              </p>
            </Link>
          ))}
        </div>
        <p className="mt-2 text-xs text-zinc-400">
          方块面积表示所选时段内该商户的总支出。
        </p>
      </div>

      {/* ── Right Column: Top 10 Ranking List ── */}
      <div className="lg:col-span-5 rounded-2xl border border-zinc-200/80 dark:border-zinc-800 bg-zinc-50/60 dark:bg-zinc-800/40 p-4 flex flex-col">
        <div className="flex items-center gap-2 mb-3">
          <ListOrdered className="w-4 h-4 text-zinc-500" />
          <h3 className="text-sm font-bold text-zinc-900 dark:text-zinc-100">
            商户排行
          </h3>
        </div>

        <div className="space-y-1.5 overflow-y-auto max-h-[340px] pr-1">
          {ranking.map((item, idx) => (
            <Link
              key={idx}
              to={`/transactions?search=${encodeURIComponent(item.name)}`}
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
                  {item.count} 笔交易 · 平均 {currencySymbol}{item.average.toFixed(2)}
                </p>
              </div>

              {/* Amount */}
              <span className="text-xs sm:text-sm font-bold font-mono text-zinc-900 dark:text-zinc-100 shrink-0 text-right">
                {currencySymbol}{item.amount.toLocaleString('zh-CN', { minimumFractionDigits: 2 })}
              </span>
            </Link>
          ))}
        </div>
      </div>
    </div>
  );
}
