/**
 * 获取用户当前配置的时区，支持自动检测浏览器本地时区或回退到 Asia/Shanghai。
 */
export function getUserTimezone() {
  try {
    if (typeof localStorage !== 'undefined') {
      const saved = localStorage.getItem('famledger_tz');
      if (saved && saved !== 'auto') return saved;
    }
  } catch {
    // 忽略特定环境中的存储访问异常
  }
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || 'Asia/Shanghai';
  } catch {
    return 'Asia/Shanghai';
  }
}

/**
 * Format a Date using its calendar date in the specified (or user's) timezone as YYYY-MM-DD.
 */
export function toLocalISODate(date = new Date(), customTz) {
  const tz = customTz || getUserTimezone();
  try {
    const formatter = new Intl.DateTimeFormat('zh-CN', {
      timeZone: tz,
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
    });
    const parts = formatter.formatToParts(date);
    const m = {};
    for (const p of parts) m[p.type] = p.value;
    return `${m.year}-${m.month}-${m.day}`;
  } catch {
    // fallback to device local only if Intl fails entirely
    const y = date.getFullYear();
    const mo = String(date.getMonth() + 1).padStart(2, "0");
    const d = String(date.getDate()).padStart(2, "0");
    return `${y}-${mo}-${d}`;
  }
}

/**
 * Format a Date using its time in the specified (or user's) timezone as HH:mm:ss (or HH:mm).
 */
export function toLocalISOTime(date = new Date(), withSeconds = true, customTz) {
  const tz = customTz || getUserTimezone();
  try {
    const formatter = new Intl.DateTimeFormat('zh-CN', {
      timeZone: tz,
      hour: '2-digit',
      minute: '2-digit',
      second: withSeconds ? '2-digit' : undefined,
      hour12: false,
    });
    const parts = formatter.formatToParts(date);
    const m = {};
    for (const p of parts) m[p.type] = p.value;
    return withSeconds ? `${m.hour}:${m.minute}:${m.second}` : `${m.hour}:${m.minute}`;
  } catch {
    const hh = String(date.getHours()).padStart(2, "0");
    const mm = String(date.getMinutes()).padStart(2, "0");
    if (!withSeconds) return `${hh}:${mm}`;
    const ss = String(date.getSeconds()).padStart(2, "0");
    return `${hh}:${mm}:${ss}`;
  }
}

/**
 * Format an ISO string, date string, or datetime to readable YYYY-MM-DD HH:mm:ss
 * in the user's selected timezone (defaults to Asia/Shanghai or browser local).
 */
export function formatDateTime(isoStringOrDate, customTz) {
  if (!isoStringOrDate) return '-';
  const tz = customTz || getUserTimezone();

  let dateObj = null;
  if (isoStringOrDate instanceof Date) {
    dateObj = isoStringOrDate;
  } else if (typeof isoStringOrDate === 'string') {
    let s = isoStringOrDate.trim();
    // 纯日期字符串（无时分秒）直接返回日期本身，避免无中生有拼接 00:00:00 造成数据困惑
    if (/^\d{4}-\d{2}-\d{2}$/.test(s)) {
      return s;
    }
    // 系统数据库内部所有时间戳约定按 UTC+0 存储
    // 若为类似 '2026-09-29 12:34:13' 或无时区标识的字符串，补充 'Z' 标识以确保正确按 UTC 解析
    if (!s.includes('Z') && !s.includes('+') && !s.includes('T')) {
      s = s.replace(' ', 'T') + 'Z';
    } else if (s.includes(' ') && !s.includes('T')) {
      s = s.replace(' ', 'T');
    }
    dateObj = new Date(s);
  }

  if (!dateObj || isNaN(dateObj.getTime())) {
    return String(isoStringOrDate);
  }

  try {
    const formatter = new Intl.DateTimeFormat('zh-CN', {
      timeZone: tz,
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
      hour12: false,
    });
    const parts = formatter.formatToParts(dateObj);
    const m = {};
    for (const p of parts) m[p.type] = p.value;
    return `${m.year}-${m.month}-${m.day} ${m.hour}:${m.minute}:${m.second}`;
  } catch (err) {
    return dateObj.toISOString().slice(0, 19).replace('T', ' ');
  }
}

/**
 * 将前端选择的本地日期 (YYYY-MM-DD) 与本地时间 (HH:mm:ss 或 HH:mm) 转换为标准的 UTC ISO 8601 字符串。
 * 严格基于用户配置的时区（默认为 Asia/Shanghai）折算，杜绝浏览器操作系统物理时区的干扰。
 * 格式示例：2026-09-29T15:42:58.000Z
 */
export function localToUTCISO(dateStr, timeStr, customTz) {
  if (!dateStr) return undefined;
  const cleanDate = dateStr.trim();
  let cleanTime = (timeStr && timeStr.trim()) ? timeStr.trim() : '12:00:00';
  if (cleanTime.split(':').length === 2) cleanTime += ':00';
  const tz = customTz || getUserTimezone();

  try {
    const targetIso = `${cleanDate}T${cleanTime}`;
    const base = new Date(targetIso + 'Z');
    if (isNaN(base.getTime())) return undefined;

    // 利用原生 Intl 解析配置时区相对 UTC 的真实偏移
    const parts = new Intl.DateTimeFormat('en-US', {
      timeZone: tz,
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
      hour12: false,
    }).formatToParts(base);

    const p = {};
    for (const part of parts) p[part.type] = part.value;
    const hour = p.hour === '24' ? '00' : p.hour;
    const inTz = new Date(`${p.year}-${p.month}-${p.day}T${hour}:${p.minute}:${p.second}Z`);
    const offsetMs = inTz.getTime() - base.getTime();
    return new Date(base.getTime() - offsetMs).toISOString();
  } catch {
    // 降级保护
    const dParts = cleanDate.split('-').map(Number);
    const tParts = cleanTime.split(':').map(Number);
    const fallback = new Date(
      dParts[0],
      (dParts[1] || 1) - 1,
      dParts[2] || 1,
      tParts[0] || 0,
      tParts[1] || 0,
      tParts[2] || 0
    );
    return isNaN(fallback.getTime()) ? undefined : fallback.toISOString();
  }
}
