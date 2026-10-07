import { tx, currentLocale } from '../localization';
/** Keep FastAPI validation objects out of React text and avoid exposing input payloads. */
export function apiErrorMessage(detail, fallback = '请求失败，请核对输入') {
  if (typeof detail === 'string' && detail.trim()) return tx(detail);
  if (Array.isArray(detail)) {
    const messages = detail.filter(item => typeof item?.msg === 'string').map(item => {
      const field = Array.isArray(item.loc) ? item.loc.slice(1).join('.') : '';
      if (field === 'loan.final_payment_day') {
        return tx('最后一期还款日只需填写1–31的整数，年月由计划确定。');
      }
      if (field === 'loan.final_payment_date') {
        return tx('最后一期还款日期请填写有效的年月日。');
      }
      return field ? `${field}: ${tx(item.msg)}` : tx(item.msg);
    });
    if (messages.length) return messages.join(currentLocale() === 'zh-CN' ? '；' : '; ');
  }
  return tx(fallback);
}

/** Proxies and unexpected backend errors can return text instead of JSON. */
export async function readJsonResponse(response, fallback = '请求失败，请核对输入') {
  let body;
  try {
    body = await response.json();
  } catch {
    throw new Error(response.ok
      ? tx('服务器响应格式不正确，请刷新后重试。')
      : tx('请求失败（HTTP {p0}），请稍后重试。', {p0: response.status}));
  }
  if (!response.ok) throw new Error(apiErrorMessage(body?.detail, response.status >= 500
    ? tx('请求失败（HTTP {p0}），请稍后重试。', {p0: response.status}) : fallback));
  return body;
}
