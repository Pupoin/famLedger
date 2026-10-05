// 40px weekday labels, 8px gutter, 32px cells and 4px between weeks.
export function calendarWeeksForWidth(width) {
  return Math.max(1, Math.floor((width - 44) / 36));
}

export function expandedCalendarStart(start, end, weeks) {
  if (!start || !end || !weeks) return start;
  const day = new Date(`${end}T00:00:00Z`);
  day.setUTCDate(day.getUTCDate() - (day.getUTCDay() + 6) % 7 - (weeks - 1) * 7);
  const minimumStart = day.toISOString().slice(0, 10);
  return start < minimumStart ? start : minimumStart;
}
