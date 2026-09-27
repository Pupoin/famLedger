import React, { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Calendar, ArrowRight, X, CreditCard, ChevronRight } from 'lucide-react';
import { fetchWithAuth } from '../../api/fetchWithAuth';

export default function SureSpendingCalendar({
  data,
  currencySymbol = '¥',
}) {
  const navigate = useNavigate();
  const [activeCell, setActiveCell] = useState(null);
  const [selectedDay, setSelectedDay] = useState(null);
  const [dayTransactions, setDayTransactions] = useState([]);
  const [loadingDayTxns, setLoadingDayTxns] = useState(false);
  const [modalOpen, setModalOpen] = useState(false);

  const startDateStr = data?.start_date || '2025年12月01日';
  const endDateStr = data?.end_date || '2026年09月27日';
  const weeks = data?.weeks || [];

  const dayNames = ['周一', '周二', '周三', '周四', '周五', '周六', '周日'];

  // Color mappings
  const getCellColor = (day) => {
    if (day.outside) {
      return 'bg-zinc-100/40 dark:bg-zinc-800/20 border-zinc-200/40 dark:border-zinc-800/40';
    }
    if (day.level === 0 || day.amount === 0) {
      return 'bg-zinc-50 dark:bg-zinc-800/50 border-zinc-200/80 dark:border-zinc-700/60';
    }
    if (day.is_refund || day.amount < 0) {
      return 'bg-emerald-400 dark:bg-emerald-500 border-emerald-500 text-white';
    }
    // Red levels
    switch (day.level) {
      case 1:
        return 'bg-red-200/90 dark:bg-red-900/60 border-red-300 dark:border-red-800';
      case 2:
        return 'bg-red-300 dark:bg-red-700/70 border-red-400 dark:border-red-600';
      case 3:
        return 'bg-red-400 dark:bg-red-600 border-red-500';
      case 4:
      default:
        return 'bg-red-500 dark:bg-red-500 border-red-600';
    }
  };

  const getMonthLabel = (weekIndex) => {
    if (!weeks[weekIndex] || !weeks[weekIndex][0]) return '';
    const dateStr = weeks[weekIndex][0].date;
    const month = parseInt(dateStr.slice(5, 7), 10);
    // Only show if first week or first week of month
    if (weekIndex === 0) return `${month}月`;
    const prevDateStr = weeks[weekIndex - 1][0].date;
    const prevMonth = parseInt(prevDateStr.slice(5, 7), 10);
    if (month !== prevMonth) return `${month}月`;
    return '';
  };

  const handleCellClick = async (day) => {
    if (day.outside) return;
    setSelectedDay(day);
    setModalOpen(true);
    setLoadingDayTxns(true);

    try {
      const res = await fetchWithAuth(`/api/v1/transactions?start_date=${day.date}&end_date=${day.date}&limit=50`);
      if (res.ok) {
        const json = await res.json();
        setDayTransactions(json.items || []);
      }
    } catch (err) {
      console.error('Failed to load day transactions', err);
    } finally {
      setLoadingDayTxns(false);
    }
  };

  return (
    <div className="space-y-3 w-full max-w-full overflow-hidden">
      {/* ── Header details ── */}
      <div className="flex flex-col gap-0.5">
        <p className="text-xs text-zinc-500">
          所选范围较短时自动向前补充历史消费并铺满可用宽度
        </p>
        <p className="text-xs font-mono text-zinc-400">
          {startDateStr} – {endDateStr}
        </p>
      </div>

      {/* ── Heatmap Grid Container (Self-contained scroll, won't break page width) ── */}
      <div className="w-full max-w-full overflow-x-auto pb-2 scrollbar-thin">
        <div className="inline-flex gap-2 min-w-max">
          {/* Weekday Labels (Left column) */}
          <div className="grid grid-rows-7 gap-1 pt-6 w-9 shrink-0 text-xs text-zinc-400 font-medium select-none">
            {dayNames.map((name, i) => (
              <span key={i} className="flex h-7 items-center justify-start">
                {name}
              </span>
            ))}
          </div>

          {/* Weeks Columns */}
          <div className="flex gap-1">
            {weeks.map((week, wIdx) => {
              const monthLabel = getMonthLabel(wIdx);
              return (
                <div key={wIdx} className="space-y-1 w-7 shrink-0">
                  {/* Month header */}
                  <p className="h-5 text-xs text-zinc-400 font-medium truncate overflow-visible whitespace-nowrap">
                    {monthLabel}
                  </p>

                  {/* 7 Days in Week */}
                  <div className="grid grid-rows-7 gap-1">
                    {week.map((day, dIdx) => {
                      const colorClasses = getCellColor(day);
                      const isHovered = activeCell?.date === day.date;
                      const isSelected = selectedDay?.date === day.date;
                      return (
                        <button
                          key={dIdx}
                          type="button"
                          disabled={day.outside}
                          onMouseEnter={() => !day.outside && setActiveCell(day)}
                          onMouseLeave={() => setActiveCell(null)}
                          onClick={() => handleCellClick(day)}
                          className={`w-7 h-7 rounded-md border transition-all duration-150 relative cursor-pointer ${colorClasses} ${
                            isSelected
                              ? 'ring-2 ring-zinc-900 dark:ring-white scale-110 z-20 shadow-md'
                              : isHovered
                              ? 'scale-110 z-10 shadow-sm ring-1 ring-zinc-700'
                              : ''
                          }`}
                          title={`${day.date} · ${currencySymbol}${Math.abs(day.amount).toFixed(2)} (点击查看明细)`}
                        />
                      );
                    })}
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      </div>

      {/* ── Bottom status bar ── */}
      <div className="rounded-xl bg-zinc-50 dark:bg-zinc-800/50 border border-zinc-100 dark:border-zinc-800 px-3.5 py-2.5 text-xs text-zinc-500 flex items-center justify-between min-h-[38px] flex-wrap gap-2">
        {activeCell ? (
          <div className="flex items-center gap-2">
            <span className="font-medium text-zinc-900 dark:text-zinc-100">{activeCell.date}</span>
            <span>·</span>
            <span className={`font-mono font-bold ${activeCell.amount < 0 ? 'text-emerald-600' : 'text-zinc-900 dark:text-zinc-100'}`}>
              {activeCell.amount < 0 ? '退款 ' : '支出 '}{currencySymbol}{Math.abs(activeCell.amount).toFixed(2)}
            </span>
            <span className="text-zinc-400 text-[11px]">(点击格子查看当天明细)</span>
          </div>
        ) : (
          <span>电脑端悬浮查看金额、点击进入明细；触屏端短按查看金额、长按进入明细。</span>
        )}

        {selectedDay && (
          <button
            onClick={() => navigate(`/transactions?start_date=${selectedDay.date}&end_date=${selectedDay.date}`)}
            className="inline-flex items-center gap-1 font-medium text-blue-600 dark:text-blue-400 hover:underline text-xs"
          >
            <span>进入 {selectedDay.date} 交易流水</span>
            <ChevronRight className="w-3.5 h-3.5" />
          </button>
        )}
      </div>

      {/* ── Day Transactions Modal / Popover ── */}
      {modalOpen && selectedDay && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/40 backdrop-blur-xs animate-in fade-in duration-150">
          <div className="relative w-full max-w-lg bg-white dark:bg-zinc-900 rounded-2xl shadow-2xl border border-zinc-200 dark:border-zinc-800 p-5 space-y-4 max-h-[85vh] flex flex-col">
            {/* Header */}
            <div className="flex items-center justify-between pb-3 border-b border-zinc-100 dark:border-zinc-800">
              <div className="flex items-center gap-2.5">
                <div className="p-2 rounded-xl bg-zinc-100 dark:bg-zinc-800 text-zinc-700 dark:text-zinc-300">
                  <Calendar className="w-4 h-4" />
                </div>
                <div>
                  <h3 className="text-base font-bold text-zinc-900 dark:text-zinc-100">
                    {selectedDay.date} 消费明细
                  </h3>
                  <p className="text-xs text-zinc-400 mt-0.5">
                    当日净额: <span className="font-mono font-bold text-zinc-900 dark:text-zinc-100">{currencySymbol}{Math.abs(selectedDay.amount).toFixed(2)}</span>
                  </p>
                </div>
              </div>

              <button
                onClick={() => setModalOpen(false)}
                className="p-1 rounded-lg text-zinc-400 hover:text-zinc-700 dark:hover:text-zinc-200 hover:bg-zinc-100 dark:hover:bg-zinc-800 transition-colors"
              >
                <X className="w-5 h-5" />
              </button>
            </div>

            {/* Transactions List */}
            <div className="flex-1 overflow-y-auto space-y-2 custom-scrollbar">
              {loadingDayTxns ? (
                <div className="py-12 text-center text-xs text-zinc-400 flex items-center justify-center gap-2">
                  <div className="w-4 h-4 border-2 border-zinc-900 border-t-transparent rounded-full animate-spin dark:border-white" />
                  <span>正在查询当日账单...</span>
                </div>
              ) : dayTransactions.length === 0 ? (
                <div className="py-10 text-center space-y-2">
                  <CreditCard className="w-8 h-8 text-zinc-300 mx-auto" />
                  <p className="text-sm font-semibold text-zinc-700 dark:text-zinc-300">
                    当日暂无直接匹配的独立交易记录
                  </p>
                  <p className="text-xs text-zinc-400 max-w-xs mx-auto">
                    热力值由历史均值加权补充。您可以前往交易明细页面查询相近周期的全部账单。
                  </p>
                </div>
              ) : (
                <div className="divide-y divide-zinc-100 dark:divide-zinc-800 border border-zinc-200 dark:border-zinc-800 rounded-xl overflow-hidden bg-white dark:bg-zinc-900">
                  {dayTransactions.map((txn) => {
                    const isExpense = txn.transaction_type === 'expense';
                    return (
                      <div key={txn.id} className="p-3 flex items-center justify-between gap-3 hover:bg-zinc-50 dark:hover:bg-zinc-800/40">
                        <div className="min-w-0">
                          <p className="text-xs sm:text-sm font-semibold text-zinc-900 dark:text-zinc-100 truncate">
                            {txn.merchant_name || txn.name}
                          </p>
                          <p className="text-[11px] text-zinc-400 font-mono mt-0.5">
                            {txn.transacted_at} · {txn.transaction_type}
                          </p>
                        </div>
                        <span className={`text-xs sm:text-sm font-bold font-mono shrink-0 ${isExpense ? 'text-zinc-900 dark:text-zinc-100' : 'text-emerald-600'}`}>
                          {isExpense ? '-' : '+'}{currencySymbol}{parseFloat(txn.amount).toFixed(2)}
                        </span>
                      </div>
                    );
                  })}
                </div>
              )}
            </div>

            {/* Footer Action */}
            <div className="pt-2 border-t border-zinc-100 dark:border-zinc-800 flex items-center justify-between">
              <span className="text-xs text-zinc-400 font-mono">
                {dayTransactions.length} 笔入账明细
              </span>

              <button
                onClick={() => {
                  setModalOpen(false);
                  navigate(`/transactions?start_date=${selectedDay.date}&end_date=${selectedDay.date}`);
                }}
                className="inline-flex items-center gap-1 px-3 py-1.5 text-xs font-semibold rounded-lg bg-zinc-900 hover:bg-zinc-800 dark:bg-white dark:text-zinc-900 text-white shadow-xs transition-colors"
              >
                <span>跳转至完整流水</span>
                <ArrowRight className="w-3.5 h-3.5" />
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
