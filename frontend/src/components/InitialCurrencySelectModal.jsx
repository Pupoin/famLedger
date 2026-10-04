import { tx, useLocale } from "../localization.js";
import React, { useState } from 'react';
import { Coins, CheckCircle2, ArrowRight, Sparkles } from 'lucide-react';

const SUPPORTED_CURRENCIES = [
  { code: 'CNY', symbol: '¥', name: '人民币', enName: 'Chinese Yuan', popular: true },
  { code: 'USD', symbol: '$', name: '美元', enName: 'US Dollar', popular: true },
  { code: 'CAD', symbol: 'C$', name: '加元', enName: 'Canadian Dollar', popular: true },
  { code: 'EUR', symbol: '€', name: '欧元', enName: 'Euro' },
  { code: 'GBP', symbol: '£', name: '英镑', enName: 'British Pound' },
  { code: 'HKD', symbol: 'HK$', name: '港币', enName: 'Hong Kong Dollar' },
  { code: 'JPY', symbol: '¥', name: '日元', enName: 'Japanese Yen' },
  { code: 'AUD', symbol: 'A$', name: '澳元', enName: 'Australian Dollar' },
  { code: 'SGD', symbol: 'S$', name: '新加坡元', enName: 'Singapore Dollar' },
  { code: 'CHF', symbol: 'CHF', name: '瑞士法郎', enName: 'Swiss Franc' },
];

export default function InitialCurrencySelectModal({
  isOpen,
  onSelectCurrency,
}) {
  useLocale();
  const [selected, setSelected] = useState('CNY');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState('');

  if (!isOpen) return null;

  const handleConfirm = async () => {
    if (!selected || submitting) return;
    try {
      setError('');
      setSubmitting(true);
      await onSelectCurrency(selected);
    } catch (err) {
      setError(tx(err.message || '保存币种失败，请重试'));
    } finally {
      setSubmitting(false);
    }
  };

  const selectedItem = SUPPORTED_CURRENCIES.find((c) => c.code === selected) || SUPPORTED_CURRENCIES[0];

  return (
    <div
      data-testid="initial-currency-select-modal"
      className="fixed inset-0 z-[9999] overflow-y-auto flex items-center justify-center p-4 bg-black/75 backdrop-blur-xs animate-in fade-in duration-200"
    >
      <div
        className="relative bg-white dark:bg-zinc-900 rounded-3xl shadow-2xl w-full max-w-lg border border-zinc-200/90 dark:border-zinc-800 p-6 sm:p-7 space-y-5 animate-in zoom-in-95 duration-200"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header Banner */}
        <div className="flex items-start gap-4">
          <div className="w-12 h-12 rounded-2xl bg-gradient-to-tr from-indigo-600 via-blue-600 to-indigo-700 text-white flex items-center justify-center shrink-0 shadow-lg shadow-indigo-500/25">
            <Coins className="w-6 h-6" />
          </div>
          <div>
            <div className="flex items-center gap-2">
              <h2 className="text-lg font-bold text-zinc-900 dark:text-zinc-100">{tx("欢迎开启您的财富记账")}</h2>
              <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[11px] font-semibold bg-indigo-100 dark:bg-indigo-950 text-indigo-700 dark:text-indigo-300">
                <Sparkles className="w-3 h-3" /> {tx("首次设置")}</span>
            </div>
            <p className="text-xs text-zinc-500 dark:text-zinc-400 mt-1">{tx("请选择您的交易与记账结算币种，该币种将作为您的默认基准货币。")}</p>
          </div>
        </div>

        {/* Currency Options Grid */}
        <div className="space-y-2">
          <div className="flex items-center justify-between text-xs font-semibold text-zinc-700 dark:text-zinc-300 px-0.5">
            <span>{tx("支持的主要结算币种")}</span>
            <span className="text-[11px] text-zinc-400 font-normal">{tx("支持多资产独立记账")}</span>
          </div>

          <div className="grid grid-cols-2 sm:grid-cols-2 gap-2.5 max-h-[290px] overflow-y-auto pr-1 py-1">
            {SUPPORTED_CURRENCIES.map((item) => {
              const isChosen = selected === item.code;
              return (
                <button
                  key={item.code}
                  type="button"
                  onClick={() => setSelected(item.code)}
                  className={`relative p-3 rounded-2xl text-left transition-all flex items-center justify-between cursor-pointer border ${
                    isChosen
                      ? 'border-indigo-600 bg-indigo-50/70 dark:bg-indigo-950/40 shadow-xs ring-2 ring-indigo-500/20'
                      : 'border-zinc-200/90 dark:border-zinc-800 bg-white dark:bg-zinc-850 hover:border-zinc-300 dark:hover:border-zinc-700'
                  }`}
                >
                  <div className="space-y-0.5 min-w-0 pr-2">
                    <div className="flex items-center gap-1.5">
                      <span className="text-base font-extrabold text-zinc-900 dark:text-zinc-100">
                        {item.symbol}
                      </span>
                      <span className="text-xs font-bold text-zinc-700 dark:text-zinc-300">
                        {item.code}
                      </span>
                      {item.popular && (
                        <span className="px-1.5 py-0.2 rounded text-[10px] font-medium bg-zinc-100 dark:bg-zinc-800 text-zinc-500 dark:text-zinc-400">{tx("常用")}</span>
                      )}
                    </div>
                    <div className="text-[11px] text-zinc-500 dark:text-zinc-400 truncate">
                      {tx(item.name)}
                    </div>
                  </div>

                  <div className="shrink-0">
                    {isChosen ? (
                      <CheckCircle2 className="w-5 h-5 text-indigo-600 dark:text-indigo-400 fill-indigo-100 dark:fill-indigo-950" />
                    ) : (
                      <div className="w-4 h-4 rounded-full border border-zinc-300 dark:border-zinc-700" />
                    )}
                  </div>
                </button>
              );
            })}
          </div>
        </div>

        {/* Informative Tip */}
        <div className="p-3 rounded-2xl bg-zinc-50 dark:bg-zinc-850/60 border border-zinc-200/70 dark:border-zinc-800 text-xs text-zinc-500 dark:text-zinc-400 leading-relaxed space-y-1">
          <p>{tx("• 选定后，您的总资产概览、收支统计与图表将统一按")} <strong className="text-zinc-800 dark:text-zinc-200">{tx(selectedItem.name)} ({selectedItem.code})</strong> {tx("折算汇总。")}</p>
          <p>{tx("• 您依然可以创建其他外币账户（如 USD、EUR 信用卡等），后续可在「设置 ➔ 系统偏好」随时调整。")}</p>
        </div>

        {error && <p role="alert" className="text-sm text-red-600">{tx(error)}</p>}
        {/* Confirm Action Button */}
        <button
          type="button"
          disabled={submitting}
          onClick={handleConfirm}
          className="w-full py-3.5 px-4 rounded-xl bg-gradient-to-r from-indigo-600 to-blue-600 hover:from-indigo-700 hover:to-blue-700 text-white text-sm font-bold shadow-lg shadow-indigo-600/25 flex items-center justify-center gap-2 transition-all active:scale-[0.99] disabled:opacity-50 cursor-pointer"
        >
          <span>{submitting ? tx("正在配置...") : tx("确认使用 {p0} 并开始记账", {p0: tx(selectedItem.name)})}</span>
          <ArrowRight className="w-4 h-4" />
        </button>
      </div>
    </div>
  );
}
