import { tx, useLocale } from "../localization.js";
import React, { useState, useEffect, useRef } from 'react';
import {
  ChevronDown,
  Check,
  Wallet,
  HandCoins,
  TrendingUp,
  Bitcoin,
  Building2,
  Car,
  Gem,
  CreditCard,
  Landmark,
  BadgePercent,
} from 'lucide-react';

/**
 * 预定义的账户类型完整配置表（区分资产类与负债类）
 */
export const ACCOUNT_TYPE_OPTIONS = [
  // ── 资产类 ──
  {
    value: 'cash',
    group: 'asset',
    groupLabel: '资产类账户',
    label: '现金 (活期 / 借记卡 / 储蓄)',
    shortLabel: '现金',
    Icon: Wallet,
    color: 'text-emerald-600 dark:text-emerald-400 bg-emerald-50 dark:bg-emerald-950/60 border-emerald-200/60',
  },
  {
    value: 'iou',
    group: 'asset',
    groupLabel: '资产类账户',
    label: '借据 (借出款 / 应收款项)',
    shortLabel: '借据',
    Icon: HandCoins,
    color: 'text-amber-600 dark:text-amber-400 bg-amber-50 dark:bg-amber-950/60 border-amber-200/60',
  },
  {
    value: 'investment',
    group: 'asset',
    groupLabel: '资产类账户',
    label: '投资 (股票 / 基金 / 证券理财)',
    shortLabel: '投资',
    Icon: TrendingUp,
    color: 'text-blue-600 dark:text-blue-400 bg-blue-50 dark:bg-blue-950/60 border-blue-200/60',
  },
  {
    value: 'crypto',
    group: 'asset',
    groupLabel: '资产类账户',
    label: '加密资产 (数字货币 / Web3)',
    shortLabel: '加密资产',
    Icon: Bitcoin,
    color: 'text-orange-600 dark:text-orange-400 bg-orange-50 dark:bg-orange-950/60 border-orange-200/60',
  },
  {
    value: 'real_estate',
    group: 'asset',
    groupLabel: '资产类账户',
    label: '房产 (住宅 / 商业不动产)',
    shortLabel: '房产',
    Icon: Building2,
    color: 'text-indigo-600 dark:text-indigo-400 bg-indigo-50 dark:bg-indigo-950/60 border-indigo-200/60',
  },
  {
    value: 'vehicle',
    group: 'asset',
    groupLabel: '资产类账户',
    label: '车辆 (汽车 / 机动车)',
    shortLabel: '车辆',
    Icon: Car,
    color: 'text-cyan-600 dark:text-cyan-400 bg-cyan-50 dark:bg-cyan-950/60 border-cyan-200/60',
  },
  {
    value: 'other_asset',
    group: 'asset',
    groupLabel: '资产类账户',
    label: '其他资产 (贵金属 / 收藏品等)',
    shortLabel: '其他资产',
    Icon: Gem,
    color: 'text-teal-600 dark:text-teal-400 bg-teal-50 dark:bg-teal-950/60 border-teal-200/60',
  },

  // ── 负债类 ──
  {
    value: 'credit_card',
    group: 'liability',
    groupLabel: '负债类账户',
    label: '信用卡 (信用卡 / 花呗 / 白条)',
    shortLabel: '信用卡',
    Icon: CreditCard,
    color: 'text-purple-600 dark:text-purple-400 bg-purple-50 dark:bg-purple-950/60 border-purple-200/60',
  },
  {
    value: 'loan',
    group: 'liability',
    groupLabel: '负债类账户',
    label: '贷款 (房贷 / 车贷 / 信用贷)',
    shortLabel: '贷款',
    Icon: Landmark,
    color: 'text-rose-600 dark:text-rose-400 bg-rose-50 dark:bg-rose-950/60 border-rose-200/60',
  },
  {
    value: 'other_liability',
    group: 'liability',
    groupLabel: '负债类账户',
    label: '其他负债 (借款 / 欠款等)',
    shortLabel: '其他负债',
    Icon: BadgePercent,
    color: 'text-stone-600 dark:text-stone-400 bg-stone-100 dark:bg-stone-800 border-stone-200',
  },
];

/**
 * 针对手机端与桌面端统一设计的账户类型高质感自定义下拉组件
 *
 * 优势：
 * 1. 彻底规避手机浏览器唤起巨大系统原生轮盘滚轮
 * 2. 统一 text-xs (12px) 精致字阶与内嵌专属彩色图标
 * 3. 结构化区分「资产类账户 (7)」与「负债类账户 (3)」分组
 * 4. 内置隐藏原生 <select> 保持对表单序列化与自动化测试完全兼容
 */
export default function AccountTypeSelectDropdown({
  name = 'account_type',
  value = 'cash',
  onChange,
  testId = 'account-type-select',
  className = '',
  useShortLabel = false,
}) {
  useLocale();
  const [isOpen, setIsOpen] = useState(false);
  const dropdownRef = useRef(null);

  const selectedOption =
    ACCOUNT_TYPE_OPTIONS.find((opt) => opt.value === value) || ACCOUNT_TYPE_OPTIONS[0];

  const assetOptions = ACCOUNT_TYPE_OPTIONS.filter((opt) => opt.group === 'asset');
  const liabilityOptions = ACCOUNT_TYPE_OPTIONS.filter((opt) => opt.group === 'liability');

  useEffect(() => {
    const handleOutsideClick = (e) => {
      if (dropdownRef.current && !dropdownRef.current.contains(e.target)) {
        setIsOpen(false);
      }
    };
    if (isOpen) {
      document.addEventListener('mousedown', handleOutsideClick);
    }
    return () => document.removeEventListener('mousedown', handleOutsideClick);
  }, [isOpen]);

  const handleSelect = (val) => {
    if (onChange) {
      onChange({ target: { name, value: val } });
    }
    setIsOpen(false);
  };

  const renderOptionItem = (opt) => {
    const isSelected = opt.value === value;
    const Icon = opt.Icon;
    return (
      <div
        key={opt.value}
        data-testid={`account-type-option-${opt.value}`}
        onClick={() => handleSelect(opt.value)}
        className={`flex items-center justify-between px-2.5 py-1.5 text-xs rounded-lg mx-1 cursor-pointer transition-colors ${
          isSelected
            ? 'bg-zinc-100 dark:bg-zinc-800 font-semibold'
            : 'hover:bg-zinc-50 dark:hover:bg-zinc-800/60'
        }`}
      >
        <div className="flex items-center gap-2 min-w-0 pr-2">
          <div
            className={`w-6 h-6 rounded-lg border flex items-center justify-center shrink-0 shadow-2xs ${opt.color}`}
          >
            <Icon className="w-3.5 h-3.5" />
          </div>
          <span className="truncate text-zinc-900 dark:text-zinc-100">{tx(opt.label)}</span>
        </div>
        {isSelected && (
          <Check className="w-3.5 h-3.5 text-zinc-900 dark:text-zinc-100 shrink-0 ml-1" />
        )}
      </div>
    );
  };

  const SelectedIcon = selectedOption.Icon;

  return (
    <div className={`relative w-full ${className}`} ref={dropdownRef}>
      {/* 隐藏原生 select 保持兼容 */}
      <select
        name={name}
        value={value}
        onChange={onChange}
        className="sr-only"
        tabIndex={-1}
        aria-hidden="true"
      >
        <optgroup label={tx("资产类账户")}>
          {assetOptions.map((opt) => (
            <option key={opt.value} value={opt.value}>
              {tx(opt.label)}
            </option>
          ))}
        </optgroup>
        <optgroup label={tx("负债类账户")}>
          {liabilityOptions.map((opt) => (
            <option key={opt.value} value={opt.value}>
              {tx(opt.label)}
            </option>
          ))}
        </optgroup>
      </select>

      {/* 触发器按钮 */}
      <button
        type="button"
        data-testid={testId}
        onClick={() => setIsOpen((prev) => !prev)}
        className={`w-full px-3 py-2 rounded-xl border text-xs transition text-left flex items-center justify-between cursor-pointer ${
          isOpen
            ? 'border-zinc-900 dark:border-white ring-2 ring-zinc-900/10 dark:ring-white/20 bg-white dark:bg-zinc-800'
            : 'border-zinc-200 dark:border-zinc-700 bg-white dark:bg-zinc-800 hover:border-zinc-300 dark:hover:border-zinc-600'
        }`}
      >
        <div className="flex items-center gap-2 min-w-0 pr-2">
          <div
            className={`w-5 h-5 rounded-md border flex items-center justify-center shrink-0 shadow-2xs ${selectedOption.color}`}
          >
            <SelectedIcon className="w-3 h-3" />
          </div>
          <span className="truncate text-zinc-900 dark:text-zinc-100 font-medium">
            {tx(useShortLabel ? selectedOption.shortLabel : selectedOption.label)}
          </span>
        </div>
        <ChevronDown
          className={`w-3.5 h-3.5 text-zinc-400 transition-transform duration-200 shrink-0 ${
            isOpen ? 'rotate-180' : ''
          }`}
        />
      </button>

      {/* 展开浮层菜单 */}
      {isOpen && (
        <div className="absolute left-0 right-0 top-full mt-1.5 z-50 bg-white dark:bg-zinc-900 border border-zinc-200 dark:border-zinc-700 rounded-xl shadow-xl max-h-60 overflow-y-auto py-1 animate-in fade-in-50 zoom-in-95 duration-100">
          {/* 资产类账户分组 */}
          <div>
            <div className="px-3 py-1.5 text-[10.5px] font-semibold text-zinc-400 dark:text-zinc-500 uppercase tracking-wider bg-zinc-50/60 dark:bg-zinc-800/40">{tx("资产类账户 (")} {assetOptions.length})
            </div>
            {assetOptions.map(renderOptionItem)}
          </div>

          {/* 负债类账户分组 */}
          <div className="border-t border-zinc-100 dark:border-zinc-800 mt-1 pt-1">
            <div className="px-3 py-1.5 text-[10.5px] font-semibold text-zinc-400 dark:text-zinc-500 uppercase tracking-wider bg-zinc-50/60 dark:bg-zinc-800/40">{tx("负债类账户 (")} {liabilityOptions.length})
            </div>
            {liabilityOptions.map(renderOptionItem)}
          </div>
        </div>
      )}
    </div>
  );
}
