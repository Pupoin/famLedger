import React from 'react';
import { Wallet, CreditCard, HandCoins, TrendingUp, Bitcoin, Building2, Car, Gem, BadgePercent, Receipt } from 'lucide-react';

/**
 * 规范化账户类型 Key：
 * 'cash' | 'credit_card' | 'investment' | 'crypto' | 'real_estate' | 'vehicle' | 'iou' | 'other_asset' | 'loan' | 'other_liability'
 */
export function normalizeAccountTypeKey(acc) {
  if (!acc) return 'cash';
  const type = String(typeof acc === 'string' ? acc : acc.account_type || '').trim().toLowerCase();
  const name = String(typeof acc === 'object' ? acc.name || acc.account_name || '' : '').toLowerCase();
  const classification = String(typeof acc === 'object' ? acc.classification || '' : '').toLowerCase();

  // 1. 信用卡 (credit_card)
  if (
    ['信用卡', 'credit_card', 'credit', '贷记卡', '花呗', '白条'].includes(type) ||
    name.includes('信用卡') ||
    name.includes('花呗') ||
    name.includes('白条')
  ) {
    return 'credit_card';
  }

  // 2. 贷款 (loan)
  if (
    ['贷款', 'loan', 'mortgage', '抵押贷款', '借款', '微粒贷', '借呗'].includes(type) ||
    name.includes('贷款') ||
    name.includes('房贷') ||
    name.includes('车贷') ||
    name.includes('借呗') ||
    name.includes('微粒贷')
  ) {
    return 'loan';
  }

  // 3. 其他负债 (other_liability)
  if (
    ['其他负债', 'other_liability'].includes(type) ||
    (classification === 'liability' && !['credit_card', 'loan'].includes(type))
  ) {
    return 'other_liability';
  }

  // 4. 借据 (iou / receivable)
  if (
    ['借据', 'iou', 'receivable', 'loan_receivable', '借出款', '借出', '借条', '欠条'].includes(type) ||
    name.includes('借据') ||
    name.includes('借出款') ||
    name.includes('借条') ||
    name.includes('欠条') ||
    name.includes('借给')
  ) {
    return 'iou';
  }

  // 5. 加密资产 (crypto)
  if (
    ['加密资产', 'crypto', 'cryptocurrency', 'btc', 'eth', '数字货币', '加密'].includes(type) ||
    name.includes('加密') ||
    name.includes('数字货币') ||
    name.includes('btc') ||
    name.includes('eth')
  ) {
    return 'crypto';
  }

  // 6. 房产 (real_estate)
  if (
    ['房产', 'real_estate', 'property', 'house', '不动产', '房屋'].includes(type) ||
    name.includes('房产') ||
    name.includes('住宅') ||
    name.includes('公寓')
  ) {
    return 'real_estate';
  }

  // 7. 车辆 (vehicle)
  if (
    ['车辆', 'vehicle', 'car', '汽车', '机动车'].includes(type) ||
    name.includes('车辆') ||
    name.includes('汽车') ||
    name.includes('私家车')
  ) {
    return 'vehicle';
  }

  // 8. 投资 (investment)
  if (
    ['投资', 'investment', 'brokerage', 'mutual_fund', 'stock', '证券', '理财', '基金', '股票'].includes(type) ||
    name.includes('理财') ||
    name.includes('证券') ||
    name.includes('基金') ||
    name.includes('股票') ||
    name.includes('投资')
  ) {
    return 'investment';
  }

  // 9. 其他资产 (other_asset)
  if (['其他资产', 'other_asset'].includes(type) || name.includes('黄金') || name.includes('贵金属')) {
    return 'other_asset';
  }

  // 10. 现金 / 储蓄 / 活期 (cash / checking / savings)
  if (
    ['现金', 'cash', 'checking', 'savings', '活期', '借记卡', '储蓄', '储蓄卡'].includes(type) ||
    name.includes('借记卡') ||
    name.includes('活期') ||
    name.includes('储蓄') ||
    name.includes('现金')
  ) {
    return 'cash';
  }

  return classification === 'liability' ? 'other_liability' : 'cash';
}

/**
 * 映射每种账户类别的专属图标 (logo)、主题色、中文标签与样式
 */
export const ACCOUNT_TYPE_CONFIGS = {
  cash: {
    key: 'cash',
    label: '现金/储蓄卡',
    emoji: '🏦',
    icon: Wallet,
    color: 'text-emerald-500 dark:text-emerald-400',
    bgColor: 'bg-emerald-50 dark:bg-emerald-950/40',
    borderColor: 'border-emerald-200/60 dark:border-emerald-800/60',
    badgeClass: 'bg-emerald-50 dark:bg-emerald-950/40 text-emerald-700 dark:text-emerald-300 border-emerald-200/60 dark:border-emerald-800/60',
  },
  credit_card: {
    key: 'credit_card',
    label: '信用卡',
    emoji: '💳',
    icon: CreditCard,
    color: 'text-purple-500 dark:text-purple-400',
    bgColor: 'bg-purple-50 dark:bg-purple-950/40',
    borderColor: 'border-purple-200/60 dark:border-purple-800/60',
    badgeClass: 'bg-purple-50 dark:bg-purple-950/40 text-purple-700 dark:text-purple-300 border-purple-200/60 dark:border-purple-800/60',
  },
  investment: {
    key: 'investment',
    label: '投资理财',
    emoji: '📈',
    icon: TrendingUp,
    color: 'text-blue-500 dark:text-blue-400',
    bgColor: 'bg-blue-50 dark:bg-blue-950/40',
    borderColor: 'border-blue-200/60 dark:border-blue-800/60',
    badgeClass: 'bg-blue-50 dark:bg-blue-950/40 text-blue-700 dark:text-blue-300 border-blue-200/60 dark:border-blue-800/60',
  },
  crypto: {
    key: 'crypto',
    label: '加密资产',
    emoji: '🪙',
    icon: Bitcoin,
    color: 'text-amber-500 dark:text-amber-400',
    bgColor: 'bg-amber-50 dark:bg-amber-950/40',
    borderColor: 'border-amber-200/60 dark:border-amber-800/60',
    badgeClass: 'bg-amber-50 dark:bg-amber-950/40 text-amber-700 dark:text-amber-300 border-amber-200/60 dark:border-amber-800/60',
  },
  real_estate: {
    key: 'real_estate',
    label: '房产物业',
    emoji: '🏠',
    icon: Building2,
    color: 'text-indigo-500 dark:text-indigo-400',
    bgColor: 'bg-indigo-50 dark:bg-indigo-950/40',
    borderColor: 'border-indigo-200/60 dark:border-indigo-800/60',
    badgeClass: 'bg-indigo-50 dark:bg-indigo-950/40 text-indigo-700 dark:text-indigo-300 border-indigo-200/60 dark:border-indigo-800/60',
  },
  vehicle: {
    key: 'vehicle',
    label: '机动车辆',
    emoji: '🚗',
    icon: Car,
    color: 'text-cyan-500 dark:text-cyan-400',
    bgColor: 'bg-cyan-50 dark:bg-cyan-950/40',
    borderColor: 'border-cyan-200/60 dark:border-cyan-800/60',
    badgeClass: 'bg-cyan-50 dark:bg-cyan-950/40 text-cyan-700 dark:text-cyan-300 border-cyan-200/60 dark:border-cyan-800/60',
  },
  iou: {
    key: 'iou',
    label: '借据/代垫',
    emoji: '🤝',
    icon: HandCoins,
    color: 'text-amber-600 dark:text-amber-400',
    bgColor: 'bg-amber-50 dark:bg-amber-950/40',
    borderColor: 'border-amber-200/60 dark:border-amber-800/60',
    badgeClass: 'bg-amber-50 dark:bg-amber-950/40 text-amber-700 dark:text-amber-300 border-amber-200/60 dark:border-amber-800/60',
  },
  other_asset: {
    key: 'other_asset',
    label: '其他资产',
    emoji: '💎',
    icon: Gem,
    color: 'text-rose-500 dark:text-rose-400',
    bgColor: 'bg-rose-50 dark:bg-rose-950/40',
    borderColor: 'border-rose-200/60 dark:border-rose-800/60',
    badgeClass: 'bg-rose-50 dark:bg-rose-950/40 text-rose-700 dark:text-rose-300 border-rose-200/60 dark:border-rose-800/60',
  },
  loan: {
    key: 'loan',
    label: '贷款按揭',
    emoji: '📑',
    icon: BadgePercent,
    color: 'text-rose-600 dark:text-rose-400',
    bgColor: 'bg-rose-50 dark:bg-rose-950/40',
    borderColor: 'border-rose-200/60 dark:border-rose-800/60',
    badgeClass: 'bg-rose-50 dark:bg-rose-950/40 text-rose-700 dark:text-rose-300 border-rose-200/60 dark:border-rose-800/60',
  },
  other_liability: {
    key: 'other_liability',
    label: '其他负债',
    emoji: '🧾',
    icon: Receipt,
    color: 'text-orange-600 dark:text-orange-400',
    bgColor: 'bg-orange-50 dark:bg-orange-950/40',
    borderColor: 'border-orange-200/60 dark:border-orange-800/60',
    badgeClass: 'bg-orange-50 dark:bg-orange-950/40 text-orange-700 dark:text-orange-300 border-orange-200/60 dark:border-orange-800/60',
  },
};

/**
 * 获取账户对应的配置（图标、颜色、背景色、Emoji 等）
 */
export function getAccountTypeConfig(acc) {
  const key = normalizeAccountTypeKey(acc);
  return ACCOUNT_TYPE_CONFIGS[key] || ACCOUNT_TYPE_CONFIGS.cash;
}

/**
 * 获取账户类型专属 Emoji（如 🏦 借记卡、💳 信用卡、📈 投资、📑 贷款、🤝 借据等）
 */
export function getAccountEmoji(acc) {
  const cfg = getAccountTypeConfig(acc);
  return cfg?.emoji || '🏦';
}

/**
 * 渲染账户 Logo 图标
 */
export function renderAccountLogo(acc, { className = 'w-4 h-4', containerClassName = '' } = {}) {
  const cfg = getAccountTypeConfig(acc);
  const IconComponent = cfg.icon;

  if (!containerClassName) {
    return <IconComponent className={`${className} ${cfg.color} shrink-0`} />;
  }

  return (
    <div className={`flex items-center justify-center shrink-0 ${cfg.bgColor} ${cfg.borderColor} ${containerClassName}`}>
      <IconComponent className={`${className} ${cfg.color}`} />
    </div>
  );
}

/**
 * 获取交易名称首字大写徽标与背景色样式
 * 保留交易名称的第一个字的大写显示在前面，并支持知名品牌色映射与现代质感底色
 */
export function getTransactionInitialBadge(name, merchantName) {
  const raw = String(name || merchantName || '').trim();
  if (!raw) {
    return {
      label: '账',
      bg: 'bg-zinc-100 dark:bg-zinc-800 text-zinc-700 dark:text-zinc-200 border border-zinc-200/80 dark:border-zinc-700/80',
    };
  }

  // 过滤开头的特殊标点符号，如 【 [ ( （ 《 < " ' # @ 等
  const cleaned = raw.replace(/^[^a-zA-Z0-9\u4e00-\u9fa5]+/, '');
  const target = cleaned || raw;
  const firstChar = (Array.from(target)[0] || '账').toUpperCase();

  const text = (raw + ' ' + (merchantName || '')).toLowerCase();

  // 余额对账与期初调整专属徽标
  if (text.includes('对账') || text.includes('adjustment') || text.includes('新余额')) {
    return { label: '平', bg: 'bg-purple-600 text-white font-bold shadow-xs' };
  }

  // 常见金融及互联网平台品牌专属背景色
  if (text.includes('支付宝') || text.includes('alipay')) {
    return { label: firstChar, bg: 'bg-[#1677FF] text-white' };
  }
  if (text.includes('财付通') || text.includes('微信') || text.includes('wechat')) {
    return { label: firstChar, bg: 'bg-[#07C160] text-white' };
  }
  if (text.includes('美团') || text.includes('meituan')) {
    return { label: firstChar, bg: 'bg-[#FFC300] text-zinc-900 font-bold' };
  }
  if (text.includes('京东') || text.includes('jd')) {
    return { label: firstChar, bg: 'bg-[#E1251B] text-white' };
  }
  if (text.includes('抖音') || text.includes('douyin') || text.includes('tiktok')) {
    return { label: firstChar, bg: 'bg-zinc-900 dark:bg-zinc-800 text-white' };
  }
  if (text.includes('招商') || text.includes('cmb')) {
    return { label: firstChar, bg: 'bg-red-600 text-white' };
  }
  if (text.includes('建设') || text.includes('建行') || text.includes('ccb')) {
    return { label: firstChar, bg: 'bg-blue-700 text-white' };
  }
  if (text.includes('工商') || text.includes('工行') || text.includes('icbc')) {
    return { label: firstChar, bg: 'bg-rose-700 text-white' };
  }
  if (text.includes('农业') || text.includes('农行') || text.includes('abc')) {
    return { label: firstChar, bg: 'bg-emerald-600 text-white' };
  }
  if (text.includes('中国银行') || text.includes('boc')) {
    return { label: firstChar, bg: 'bg-red-700 text-white' };
  }
  if (text.includes('交通银行') || text.includes('bocom')) {
    return { label: firstChar, bg: 'bg-blue-800 text-white' };
  }
  if (text.includes('apple') || text.includes('苹果')) {
    return { label: firstChar, bg: 'bg-zinc-900 dark:bg-zinc-700 text-white' };
  }

  // 默认中性优雅质感底色
  return {
    label: firstChar,
    bg: 'bg-zinc-100 dark:bg-zinc-800 text-zinc-700 dark:text-zinc-200 border border-zinc-200/80 dark:border-zinc-700/80',
  };
}

/**
 * 全局统一账户展示名称函数（所见即所得，彻底拒绝黑盒篡改用户输入）
 */
export function formatAccountDisplayName(acc) {
  if (!acc) return '';
  if (typeof acc === 'string') return acc.trim();
  const name = String(acc.name || acc.account_name || '').trim();
  const inst = String(acc.institution_name || '').trim();
  return name || inst || '默认账户';
}

/**
 * 格式化账户带有专属 Emoji 的下拉选项展示名（例如：🏦 招商银行 7931 (alice)、💳 招商银行 8866）
 */
export function formatAccountWithEmoji(acc) {
  if (!acc) return '';
  const emoji = getAccountEmoji(acc);
  const name = formatAccountDisplayName(acc);
  const owner = acc.owner_display_name || acc.owner;
  const isShared = acc.is_owner === false && owner;
  const ownerSuffix = isShared ? ` (${owner})` : '';
  const base = emoji ? `${emoji} ${name}` : name;
  return `${base}${ownerSuffix}`;
}
