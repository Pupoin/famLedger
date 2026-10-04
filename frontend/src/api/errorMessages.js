import { tx, currentLocale } from '../localization';
/** Keep FastAPI validation objects out of React text and avoid exposing input payloads. */
export function apiErrorMessage(detail, fallback = '请求失败，请核对输入') {
  if (typeof detail === 'string' && detail.trim()) return tx(detail);
  if (Array.isArray(detail)) {
    const messages = detail.filter(item => typeof item?.msg === 'string').map(item => {
      const field = Array.isArray(item.loc) ? item.loc.slice(1).join('.') : '';
      return field ? `${field}: ${tx(item.msg)}` : tx(item.msg);
    });
    if (messages.length) return messages.join(currentLocale() === 'zh-CN' ? '；' : '; ');
  }
  return tx(fallback);
}
