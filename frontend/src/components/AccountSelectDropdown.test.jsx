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

  it.each([true, false])('keeps the primary owner after candidates load with is_owner=%s', (isOwner) => {
    const summary = { id: parent.id, name: parent.name, account_type: 'credit_card', owner: 'Alice' };
    const loaded = { ...summary, is_owner: isOwner, can_manage: true };
    for (const accounts of [[], [loaded]]) {
      const html = renderToStaticMarkup(<AccountSelectDropdown
        value={parent.id} accounts={accounts} selectedAccountFallback={summary}
        showPrimaryOwner emptyLabel="无 (独立主卡)"
      />);
      expect(html).toContain('主卡所有者：Alice');
      expect(html).not.toContain('Alice 共享');
      expect(html).toContain(parent.name);
    }
  });

  it('shows the newly selected primary owner instead of the old relationship owner', () => {
    const other = { id: 'other-primary', name: 'Bob 的主卡', account_type: 'credit_card', owner: 'Bob', is_owner: true };
    const html = renderToStaticMarkup(<AccountSelectDropdown
      value={other.id} accounts={[other]} selectedAccountFallback={parent} showPrimaryOwner
    />);
    expect(html).toContain('主卡所有者：Bob');
    expect(html).not.toContain('主卡所有者：Alice');
    expect(html).toContain(other.name);
  });

  it('hides the primary owner when unlinking even when the former primary is still a candidate', () => {
    const html = renderToStaticMarkup(<AccountSelectDropdown
      value="" accounts={[{ ...parent, is_owner: true }]} selectedAccountFallback={parent}
      showPrimaryOwner emptyLabel="无 (独立主卡)"
    />);
    expect(html).toContain('无 (独立主卡)');
    expect(html).not.toContain('主卡所有者：Alice');
  });

  it('translates the primary owner after the selectable account replaces the relationship summary', () => {
    i18n.changeLanguage('en');
    const html = renderToStaticMarkup(<AccountSelectDropdown
      value={parent.id} accounts={[{ ...parent, is_owner: true, relationship_only: undefined }]}
      selectedAccountFallback={parent} showPrimaryOwner
    />);
    expect(html).toContain('Primary card owner: Alice');
    expect(html).not.toContain('Alice shared');
  });

  it('keeps normal transaction account selectors using their shared-account label', () => {
    const html = renderToStaticMarkup(<AccountSelectDropdown
      value={parent.id} accounts={[{ ...parent, relationship_only: undefined }]}
    />);
    expect(html).toContain('Alice 共享');
    expect(html).not.toContain('主卡所有者：Alice');
  });
});
