import React, { useState } from 'react';
import { Download, Upload, X } from 'lucide-react';
import { fetchWithAuth } from '../api/fetchWithAuth';
import { tx, categoryLabel } from '../localization';
import { useToast } from '../ToastContext';

const buttonClass = 'inline-flex items-center justify-center gap-1.5 px-3 py-2 text-xs font-semibold rounded-lg border border-zinc-200 dark:border-zinc-700 whitespace-nowrap';

export default function RulesTransfer({ onImported }) {
  const { showToast } = useToast();
  const [open, setOpen] = useState(false);
  const [bundle, setBundle] = useState(null);
  const [mode, setMode] = useState('append');
  const [preview, setPreview] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  const exportRules = async () => {
    try {
      const response = await fetchWithAuth('/api/v1/rules/export');
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || tx('导出失败'));
      const url = URL.createObjectURL(new Blob([JSON.stringify(data, null, 2) + '\n'], { type: 'application/json' }));
      const anchor = document.createElement('a');
      anchor.href = url;
      anchor.download = 'famledger-rules.json';
      anchor.click();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (err) { showToast(tx(err.message), 'error'); }
  };

  const importRules = async (previewOnly) => {
    setBusy(true); setError('');
    try {
      const response = await fetchWithAuth('/api/v1/rules/import', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ bundle, mode, preview: previewOnly }),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : tx('规则文件无效'));
      if (previewOnly) setPreview(data);
      else {
        showToast(tx('已导入 {p0} 条规则', { p0: data.rule_count }), 'success');
        setOpen(false); onImported();
      }
    } catch (err) { setError(tx(err.message)); setPreview(null); }
    finally { setBusy(false); }
  };

  return <>
    <div className="flex gap-2 flex-wrap">
      <button className={buttonClass} onClick={() => { setOpen(true); setBundle(null); setPreview(null); setError(''); }}><Upload size={14} />{tx('导入规则')}</button>
      <button className={buttonClass} onClick={exportRules}><Download size={14} />{tx('导出规则')}</button>
    </div>
    {open && <div className="fixed inset-0 z-50 flex items-center justify-center p-3 bg-black/40">
      <div className="w-full max-w-lg max-h-[90vh] overflow-y-auto rounded-2xl bg-white dark:bg-zinc-900 p-5 space-y-4 shadow-xl">
        <div className="flex items-center justify-between"><h3 className="font-bold">{tx('导入规则与自动化')}</h3><button aria-label={tx('关闭')} disabled={busy} onClick={() => setOpen(false)}><X size={20} /></button></div>
        <p className="text-xs text-zinc-500">{tx('支持完整规则 JSON 和旧 category_rules.json。导入后用于新交易；历史交易需另行预演并应用。')}</p>
        <input aria-label={tx('规则文件')} type="file" accept=".json,application/json" disabled={busy} className="w-full text-sm" onChange={async event => {
          setBundle(null); setPreview(null); setError('');
          try {
            const file = event.target.files?.[0];
            if (!file) return;
            if (file.size > 2000000) throw new Error(tx('规则文件不能超过 2 MB'));
            setBundle(JSON.parse(await file.text()));
          } catch (err) { setError(tx('规则文件无效') + ': ' + err.message); }
        }} />
        <select aria-label={tx('导入方式')} className="w-full p-2 rounded-lg border dark:bg-zinc-800" disabled={busy} value={mode} onChange={event => { setMode(event.target.value); setPreview(null); }}>
          <option value="append">{tx('新增规则（保留现有规则）')}</option>
          <option value="merge">{tx('按规则名称合并（同名规则更新）')}</option>
        </select>
        {error && <p role="alert" className="text-sm text-rose-500 break-words">{error}</p>}
        {preview && <div className="text-xs space-y-2 p-3 rounded-lg bg-zinc-50 dark:bg-zinc-800">
          <p>{tx('新增 {p0} 条，更新 {p1} 条，新建分类 {p2} 个', { p0: preview.rules_created, p1: preview.rules_updated, p2: preview.categories_created })}</p>
          <ol className="space-y-1 max-h-48 overflow-auto">{preview.rules.map((rule, i) => <li key={i}>#{rule.priority} {categoryLabel(rule.name)} · {rule.action_count} {tx('动作')} · {tx(rule.is_active ? '启用' : '停用')}</li>)}</ol>
        </div>}
        <div className="flex justify-end gap-2">
          <button className={buttonClass} disabled={!bundle || busy} onClick={() => importRules(true)}>{tx('检查文件')}</button>
          <button className={buttonClass + ' bg-zinc-900 text-white dark:bg-white dark:text-zinc-900 disabled:opacity-40'} disabled={!preview || busy} onClick={() => importRules(false)}>{busy ? tx('处理中…') : tx('确认导入')}</button>
        </div>
      </div>
    </div>}
  </>;
}
