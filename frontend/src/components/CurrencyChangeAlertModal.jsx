import { tx, useLocale } from "../localization.js";
import React from 'react';
import { ArrowRight, Coins, ShieldCheck, Check } from 'lucide-react';

const CURRENCY_LABELS = {
  CNY: '人民币 (CNY)',
  USD: '美元 (USD)',
  EUR: '欧元 (EUR)',
  GBP: '英镑 (GBP)',
  CAD: '加元 (CAD)',
  AUD: '澳元 (AUD)',
  JPY: '日元 (JPY)',
  HKD: '港币 (HKD)',
  SGD: '新加坡元 (SGD)',
  CHF: '瑞士法郎 (CHF)',
  INR: '印度卢比 (INR)',
};

export default function CurrencyChangeAlertModal({
  isOpen,
  onClose,
  data = {},
}) {
  useLocale();
  if (!isOpen) return null;

  const {
    familyName = '家庭组',
    previous_currency = 'CNY',
    new_currency = 'CNY',
  } = data;

  const prevLabel = CURRENCY_LABELS[previous_currency] || previous_currency;
  const newLabel = CURRENCY_LABELS[new_currency] || new_currency;

  return (
    <div
      data-testid="currency-change-alert-modal"
      className="fixed inset-0 z-50 overflow-y-auto flex items-center justify-center p-4 bg-black/65 backdrop-blur-xs animate-in fade-in duration-200"
    >
      <div
        className="relative bg-white dark:bg-zinc-900 rounded-3xl shadow-2xl w-full max-w-md border border-zinc-200/90 dark:border-zinc-800 p-6 space-y-5 animate-in zoom-in-95 duration-200"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Top Header */}
        <div className="flex items-center gap-3.5">
          <div className="w-12 h-12 rounded-2xl bg-gradient-to-tr from-amber-500 to-orange-500 text-white flex items-center justify-center shrink-0 shadow-lg shadow-amber-500/25">
            <Coins className="w-6 h-6" />
          </div>
          <div>
            <h3 className="text-base font-bold text-zinc-900 dark:text-zinc-100">{tx("结算币种已同步更新")}</h3>
            <p className="text-xs text-zinc-500 dark:text-zinc-400 mt-0.5">{tx("已加入家庭组「")} {familyName}」
            </p>
          </div>
        </div>

        {/* Currency Transition Comparison Card */}
        <div className="p-4 rounded-2xl bg-gradient-to-br from-amber-50/70 via-orange-50/40 to-amber-50/30 dark:from-amber-950/20 dark:via-orange-950/15 dark:to-amber-950/10 border border-amber-200/80 dark:border-amber-900/40 space-y-3">
          <p className="text-xs text-zinc-700 dark:text-zinc-300 leading-relaxed">{tx("为保证家庭组内所有成员收支口径与账本汇总一致，您的个人默认结算币种已自动对齐更换：")}</p>

          <div className="grid grid-cols-[1fr_auto_1fr] items-center gap-2 pt-1 pb-1">
            {/* Old Currency */}
            <div className="p-2.5 rounded-xl bg-white dark:bg-zinc-800 border border-zinc-200 dark:border-zinc-700 text-center shadow-2xs">
              <span className="text-[10px] text-zinc-400 dark:text-zinc-400 block mb-0.5">{tx("原默认币种")}</span>
              <span className="text-sm font-bold text-zinc-600 dark:text-zinc-300 block line-through decoration-zinc-400">
                {previous_currency}
              </span>
              <span className="text-[10px] text-zinc-400 truncate block mt-0.5">
                {tx(prevLabel)}
              </span>
            </div>

            {/* Transition Arrow */}
            <div className="flex items-center justify-center text-amber-600 dark:text-amber-400 px-1">
              <div className="w-7 h-7 rounded-full bg-amber-100 dark:bg-amber-950/60 flex items-center justify-center shadow-2xs">
                <ArrowRight className="w-4 h-4" />
              </div>
            </div>

            {/* New Currency */}
            <div className="p-2.5 rounded-xl bg-amber-100/70 dark:bg-amber-900/40 border border-amber-300/80 dark:border-amber-800 text-center shadow-2xs">
              <span className="text-[10px] text-amber-700 dark:text-amber-300 font-medium block mb-0.5">{tx("新家庭基准币种")}</span>
              <span className="text-sm font-bold text-amber-950 dark:text-amber-100 block">
                {new_currency}
              </span>
              <span className="text-[10px] text-amber-800/80 dark:text-amber-300/80 truncate block mt-0.5">
                {tx(newLabel)}
              </span>
            </div>
          </div>
        </div>

        {/* Security / Notice Details */}
        <div className="space-y-2 text-xs text-zinc-600 dark:text-zinc-400 bg-zinc-50 dark:bg-zinc-850/60 p-3.5 rounded-2xl border border-zinc-200/80 dark:border-zinc-800">
          <div className="flex items-start gap-2">
            <ShieldCheck className="w-4 h-4 text-emerald-600 dark:text-emerald-400 shrink-0 mt-0.5" />
            <span className="leading-relaxed">
              <strong className="text-zinc-800 dark:text-zinc-200">{tx("资产不受影响：")}</strong> {tx("您名下已建立的外币账户及其所有流水金额均完整保留，原样记录。")}</span>
          </div>
          <div className="flex items-start gap-2 pt-1 border-t border-zinc-200/60 dark:border-zinc-800/60">
            <Coins className="w-4 h-4 text-blue-600 dark:text-blue-400 shrink-0 mt-0.5" />
            <span className="leading-relaxed">
              <strong className="text-zinc-800 dark:text-zinc-200">{tx("汇总口径对齐：")}</strong> {tx("仪表盘概览、财务分析报表与图表将统一以")} <strong className="text-zinc-900 dark:text-zinc-100">{new_currency}</strong> {tx("进行汇总呈现。")}</span>
          </div>
        </div>

        {/* Confirm Action Button */}
        <button
          type="button"
          onClick={onClose}
          className="w-full py-3 px-4 rounded-xl bg-gradient-to-r from-amber-600 to-orange-600 hover:from-amber-700 hover:to-orange-700 text-white text-sm font-bold shadow-lg shadow-amber-600/25 flex items-center justify-center gap-2 transition-all active:scale-[0.99]"
        >
          <Check className="w-4 h-4" />
          <span>{tx("我知道了")}</span>
        </button>
      </div>
    </div>
  );
}
