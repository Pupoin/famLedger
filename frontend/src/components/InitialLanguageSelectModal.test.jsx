import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { expect, it } from 'vitest';
import InitialLanguageSelectModal from './InitialLanguageSelectModal';

it('asks in English and preselects English on first login', () => {
  const html = renderToStaticMarkup(<InitialLanguageSelectModal isOpen onSelectLanguage={() => {}} />);
  expect(html).toContain('Welcome! Choose your language');
  expect(html).toContain('lang="en"');
  expect(html).toMatch(/checked="" value="en"/);
  expect(html).toContain('Simplified Chinese');
});

it('does not ask again after a saved choice', () => {
  expect(renderToStaticMarkup(<InitialLanguageSelectModal isOpen={false} />)).toBe('');
});
