import React, { useState } from 'react';

export default function InitialLanguageSelectModal({ isOpen, onSelectLanguage }) {
  const [selected, setSelected] = useState('en');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState('');
  if (!isOpen) return null;
  const confirm = async () => {
    if (submitting) return;
    setSubmitting(true);
    setError('');
    try { await onSelectLanguage(selected); }
    catch { setError('Could not save your language. Please try again.'); }
    finally { setSubmitting(false); }
  };
  return (
    <div className="fixed inset-0 z-[10000] flex items-center justify-center p-4 bg-black/70 backdrop-blur-xs" data-testid="initial-language-select-modal">
      <div role="dialog" aria-modal="true" aria-labelledby="initial-language-title" lang="en" className="w-full max-w-md p-6 rounded-2xl bg-white dark:bg-zinc-900 border border-zinc-200 dark:border-zinc-800 shadow-2xl space-y-4">
        <h2 id="initial-language-title" className="text-xl font-bold text-zinc-900 dark:text-white">Welcome! Choose your language</h2>
        <p className="text-sm text-zinc-500">Which language would you like to use? You can change it later in Settings.</p>
        <fieldset disabled={submitting} className="space-y-2">
          <legend className="sr-only">Display language</legend>
          {[{code:'en', label:'English'}, {code:'zh', label:'简体中文 (Simplified Chinese)'}].map(({code, label}) => (
            <label key={code} className="flex items-center gap-3 p-3 rounded-xl border border-zinc-200 dark:border-zinc-700 text-sm text-zinc-900 dark:text-white cursor-pointer">
              <input type="radio" name="initial-language" value={code} checked={selected === code} onChange={() => setSelected(code)} />
              {label}
            </label>
          ))}
        </fieldset>
        {error && <p role="alert" className="text-sm text-rose-600">{error}</p>}
        <button type="button" onClick={confirm} disabled={submitting} className="w-full p-3 rounded-xl bg-zinc-900 dark:bg-white text-white dark:text-zinc-900 font-semibold disabled:opacity-50">{submitting ? 'Saving…' : 'Continue'}</button>
      </div>
    </div>
  );
}
