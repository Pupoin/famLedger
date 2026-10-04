import i18n from '../i18n';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { beforeEach, describe, expect, it } from 'vitest';
import AccountSelectDropdown from './AccountSelectDropdown';

beforeEach(() => i18n.changeLanguage('zh'));

describe('existing private primary card relationship', () => {
  const parent = {
    id: 'private-primary', name: 'Alice 的信用卡主卡', account_type: 'credit_card',
    owner: 'Alice', is_owner: false, relationship_only: true,
  };

  it('shows the linked primary and its owner when the primary is absent from selectable accounts', () => {
    const html = renderToStaticMarkup(<AccountSelectDropdown
      value={parent.id} accounts={[]} selectedAccountFallback={parent}
      emptyLabel="无 (独立主卡)" placeholder="选择所属信用卡主卡"
    />);
    expect(html).toContain(parent.name);
    expect(html).toContain('主卡所有者：Alice');
    expect(html).not.toContain('Alice 共享');
    expect(html).not.toContain('选择所属信用卡主卡');
    expect(html).toMatch(/<option[^>]*value="private-primary"[^>]*disabled/);
  });

  it('does not show the old relationship after the user chooses to unlink', () => {
    const html = renderToStaticMarkup(<AccountSelectDropdown
      value="" accounts={[]} selectedAccountFallback={parent} emptyLabel="无 (独立主卡)"
    />);
    expect(html).toContain('无 (独立主卡)');
    expect(html).not.toContain(parent.name);
    expect(html).not.toContain('主卡所有者：Alice');
  });
});
