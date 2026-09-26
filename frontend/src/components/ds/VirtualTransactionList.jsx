import React, { useRef } from 'react';
import { useVirtualizer } from '@tanstack/react-virtual';
import {
  ArrowLeftRight,
  RotateCcw,
  Scissors,
  Tag,
  Calendar,
  CreditCard,
  Building,
} from 'lucide-react';
import { Pill } from './DesignSystem';
import { useCurrency } from '../../CurrencyContext';

export function VirtualTransactionList({
  items = [],
  onSelectTransaction,
  selectedId,
  isLoadingMore = false,
  onLoadMore,
  hasMore = false,
}) {
  const { privacyMode } = useCurrency();
  const parentRef = useRef(null);

  const rowVirtualizer = useVirtualizer({
    count: hasMore ? items.length + 1 : items.length,
    getScrollElement: () => parentRef.current,
    estimateSize: () => 76,
    overscan: 5,
  });

  const virtualItems = rowVirtualizer.getVirtualItems();

  return (
    <div
      ref={parentRef}
      className="h-[calc(100vh-270px)] min-h-[480px] lg:h-[700px] overflow-y-auto custom-scrollbar border border-outline/15 rounded-2xl bg-surface-container-low shadow-xs"
    >
      <div
        className="w-full relative"
        style={{
          height: `${rowVirtualizer.getTotalSize()}px`,
        }}
      >
        {virtualItems.map((virtualRow) => {
          const isLoaderRow = virtualRow.index >= items.length;
          const txn = items[virtualRow.index];

          if (isLoaderRow) {
            return (
              <div
                key="loader"
                className="absolute top-0 left-0 w-full flex items-center justify-center p-4"
                style={{
                  transform: `translateY(${virtualRow.start}px)`,
                }}
              >
                {isLoadingMore ? (
                  <span className="w-5 h-5 border-2 border-primary border-t-transparent rounded-full animate-spin" />
                ) : (
                  <button
                    onClick={onLoadMore}
                    className="text-xs text-primary hover:underline font-medium"
                  >
                    加载更多...
                  </button>
                )}
              </div>
            );
          }

          const isNegative = Number(txn.amount) < 0;
          const isSelected = selectedId === txn.id;

          return (
            <div
              key={txn.id}
              onClick={() => onSelectTransaction?.(txn)}
              className={`absolute top-0 left-0 w-full px-4 py-3 cursor-pointer transition-colors border-b border-outline/10 flex items-center justify-between gap-4 ${
                isSelected
                  ? 'bg-primary/10'
                  : 'hover:bg-surface-container/60 bg-surface-container-lowest'
              }`}
              style={{
                height: `${virtualRow.size}px`,
                transform: `translateY(${virtualRow.start}px)`,
              }}
            >
              {/* Left Column: Icon & Basic Info */}
              <div className="flex items-center gap-3 min-w-0">
                <div
                  className={`w-9 h-9 sm:w-10 sm:h-10 rounded-xl flex items-center justify-center shrink-0 ${
                    txn.transaction_type === 'transfer'
                      ? 'bg-blue-500/10 text-blue-600'
                      : txn.transaction_type === 'refund'
                      ? 'bg-amber-500/10 text-amber-600'
                      : isNegative
                      ? 'bg-surface-container text-on-surface'
                      : 'bg-emerald-500/10 text-emerald-600'
                  }`}
                >
                  {txn.transaction_type === 'transfer' ? (
                    <ArrowLeftRight className="w-4 h-4 sm:w-5 sm:h-5" />
                  ) : txn.transaction_type === 'refund' ? (
                    <RotateCcw className="w-4 h-4 sm:w-5 sm:h-5" />
                  ) : txn.is_split ? (
                    <Scissors className="w-4 h-4 sm:w-5 sm:h-5" />
                  ) : (
                    <CreditCard className="w-4 h-4 sm:w-5 sm:h-5" />
                  )}
                </div>

                <div className="min-w-0">
                  <div className="flex items-center gap-1.5 sm:gap-2">
                    <span className="font-semibold text-xs sm:text-sm text-on-surface truncate">
                      {txn.name || txn.merchant_name || '未命名消费'}
                    </span>
                    {txn.account_mask && (
                      <span className="inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-mono bg-surface-container text-on-surface-variant font-medium shrink-0 border border-outline/10">
                        *{txn.account_mask}
                      </span>
                    )}
                    {txn.transaction_type === 'transfer' && (
                      <Pill label="内部转账" variant="info" />
                    )}
                    {txn.transaction_type === 'refund' && (
                      <Pill label="退款冲抵" variant="warning" />
                    )}
                    {txn.is_split && (
                      <Pill label="已拆分" variant="purple" />
                    )}
                  </div>

                  <div className="flex items-center gap-2 sm:gap-3 text-[11px] sm:text-xs text-on-surface-variant mt-0.5 font-mono overflow-hidden">
                    <span className="flex items-center gap-1 whitespace-nowrap shrink-0">
                      <Calendar className="w-3 h-3" />
                      <span>{txn.transacted_at}</span>
                    </span>
                    {txn.merchant_name && txn.merchant_name !== txn.name && (
                      <span className="truncate max-w-[100px] sm:max-w-[140px] shrink-0 text-on-surface-variant/80">
                        {txn.merchant_name}
                      </span>
                    )}
                    {txn.notes && (
                      <span className="truncate max-w-[120px] sm:max-w-[160px] text-outline">
                        {txn.notes}
                      </span>
                    )}
                  </div>
                </div>
              </div>

              {/* Right Column: Amount */}
              <div className="text-right shrink-0">
                <span
                  className={`text-sm sm:text-base font-bold font-mono block ${
                    txn.transaction_type === 'transfer'
                      ? 'text-on-surface-variant'
                      : (txn.transaction_type === 'refund' || isNegative)
                      ? 'text-emerald-600 dark:text-emerald-400'
                      : 'text-on-surface'
                  }`}
                >
                  {privacyMode
                    ? '••••••'
                    : `${txn.transaction_type === 'transfer' ? '' : (txn.transaction_type === 'refund' || isNegative) ? '+' : '-'}¥${Math.abs(Number(txn.amount)).toFixed(2)}`}
                </span>
                <span className="text-[10px] text-on-surface-variant uppercase tracking-wider font-semibold">
                  {txn.currency}
                </span>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
