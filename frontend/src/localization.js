import { useTranslation } from 'react-i18next';
import i18n from './i18n';
import catalog from './locales/ui.json';

// Shared language helpers are imported by context providers as well as pages.
// Reload their consumers together during development to preserve context identity.
if (import.meta.hot) import.meta.hot.accept(() => window.location.reload());

const translations = new Map();
const patterns = [];
const escape = value => value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
for (const [source, entry] of Object.entries(catalog)) {
  translations.set(source, entry);
  translations.set(entry.zh, entry);
  translations.set(entry.en, entry);
  for (const text of new Set([source, entry.zh, entry.en])) {
    if (!/\{p\d+\}/.test(text)) continue;
    if (!/[A-Za-z\p{Script=Han}]/u.test(text.replace(/\{p\d+\}/g, ''))) continue;
    const names = [];
    const expression = text.split(/(\{p\d+\})/).map(part => {
      if (!/^\{p\d+\}$/.test(part)) return escape(part);
      names.push(part.slice(1, -1));
      return '([\\s\\S]*?)';
    }).join('');
    patterns.push({ expression: new RegExp(`^${expression}$`), names, entry });
  }
}

export function currentLocale() {
  return i18n.resolvedLanguage?.startsWith('zh') || i18n.language?.startsWith('zh') ? 'zh-CN' : 'en-US';
}

// Components subscribe to language changes; tx can also serve event handlers.
export function useLocale() {
  useTranslation();
  return currentLocale();
}

const standardCategories = new Set([
  '餐饮美食', '超市便利', '生活缴费', '交通出行', '购物消费', '人情往来', '其他',
  '工资薪酬', '理财收益', '奖金补贴', '兼职副业', '其他收入', '未分类',
  '旅行住宿', '娱乐休闲', '教育学习', '医疗健康', '宠物用品', '个人/转账',
  'Groceries', 'Rent', 'Utilities', 'Dining', 'Transportation', 'Entertainment',
  'Healthcare', 'Shopping', 'Travel', 'Payment', 'Other', 'Gas', 'Car Insurance',
  '贷款利息', '贷款手续费',
  'Car Maintenance', 'Home Care', 'Pet Care', 'Pet Insurance', 'Vet', 'Gift',
  'Subscription', 'Parking', 'Tenant Insurance', 'Reimbursement',
  'Salary / Wages', 'Freelance / Side Income',
]);

export function categoryLabel(name) {
  return standardCategories.has(name) ? tx(name) : name;
}

// For date captions only. ISO values and the user's chosen input format stay intact.
export function dateLabel(text) {
  if (typeof text !== 'string') return text;
  if (currentLocale() === 'zh-CN') {
    const months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
    return tx(text.replace(/\b(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec) (\d{1,2}), (\d{4})\b/g,
      (_, month, day, year) => `${year}年${months.indexOf(month) + 1}月${Number(day)}日`));
  }
  const formatted = text
    .replace(/(\d{4})年(\d{1,2})月(\d{1,2})日/g, '$1-$2-$3')
    .replace(/(\d{4})年(\d{1,2})月/g, '$1-$2')
    .replace(/(\d{1,2})月/g, '$1');
  return /\p{Script=Han}/u.test(formatted.replace(' 至 ', ' ')) ? tx(text) : tx(formatted);
}

function interpolate(text, values) {
  return text.replace(/\{(p\d+)\}/g, (token, name) =>
    Object.prototype.hasOwnProperty.call(values, name) ? String(values[name] ?? '') : token);
}

export function tx(text, values = {}) {
  if (typeof text !== 'string') return text;
  const language = currentLocale() === 'zh-CN' ? 'zh' : 'en';
  const entry = translations.get(text);
  if (entry) return interpolate(entry[language], values);
  // Match only complete, known UI messages, preserving interpolated values.
  for (const pattern of patterns) {
    const match = pattern.expression.exec(text);
    if (!match) continue;
    const captured = Object.fromEntries(pattern.names.map((name, index) => [name, match[index + 1]]));
    return interpolate(pattern.entry[language], { ...captured, ...values });
  }
  return interpolate(text, values);
}
