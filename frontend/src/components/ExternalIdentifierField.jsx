import { tx, useLocale } from '../localization';

export default function ExternalIdentifierField({ id, value, onChange }) {
  useLocale();
  return (
    <div>
      <label htmlFor={id} className="flex flex-wrap items-baseline gap-x-2 text-xs font-medium text-zinc-600 dark:text-zinc-400 mb-1">
        <span>{tx('外部账户标识（可选）')}</span>
        <span className="font-mono text-[11px] text-zinc-500 dark:text-zinc-400">external_identifier</span>
      </label>
      <input
        id={id}
        name="external_identifier"
        type="text"
        maxLength={100}
        value={value || ''}
        placeholder={tx('例如 招商银行借记卡:2238')}
        aria-describedby={`${id}-help`}
        onChange={(event) => onChange(event.target.value)}
        className="w-full px-3 py-2 rounded-lg border border-zinc-200 dark:border-zinc-700 bg-white dark:bg-zinc-800 text-zinc-900 dark:text-white text-xs focus:ring-1 focus:ring-zinc-900"
      />
      <p id={`${id}-help`} className="mt-1 text-[11px] text-zinc-400">
        {tx('填写 POST 中的完整账户标识（如 招商银行借记卡:2238）。优先精确匹配；留空则按账户名称匹配。')}
      </p>
    </div>
  );
}
