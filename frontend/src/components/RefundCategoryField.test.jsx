import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';
import RefundCategoryField, { transactionCategoryLabel } from './RefundCategoryField';

const linked = [{ id: 'dining', name: 'Original dining', icon: '🍴' }, { id: 'travel', name: 'Original travel', icon: '🚗' }];
const categories = [{ id: 'other', name: 'Other', icon: '📦' }];
const render = refund_info => renderToStaticMarkup(<RefundCategoryField transaction={{ transaction_type: 'refund', refund_info }}
  categories={categories} value="other" transactionType="refund" onChange={() => {}} />);

describe('refund category ownership', () => {
  it('replaces the selector with the original categories for a fully linked refund', () => {
    const html = render({ is_linked: true, category_editable: false, linked_categories: linked });
    expect(html).toContain('refund-category-readonly');
    expect(html).toContain('Original dining');
    expect(html).toContain('Original travel');
    expect(html).not.toContain('<select');
  });
  it('makes the remaining category editable and identifies the already linked categories', () => {
    const html = render({ is_linked: true, category_editable: true, linked_categories: linked });
    expect(html).toContain('edit-category-select');
    expect(html).toContain('refund-linked-categories');
    expect(html).not.toContain('refund-category-readonly');
  });
  it('keeps unlinked refunds editable', () => {
    const html = render({ is_linked: false, category_editable: true, linked_categories: [] });
    expect(html).toContain('edit-category-select');
    expect(html).not.toContain('refund-linked-categories');
  });
  it('uses original categories in both the detail and list rather than a stale refund category', () => {
    const info = { category_editable: false, linked_categories: linked };
    for (const field of ['refund_info', 'refund_category_info']) {
      expect(transactionCategoryLabel({ transaction_type: 'refund', category_name: 'Wrong refund category', [field]: info }))
        .toBe('Original dining / Original travel');
    }
    expect(transactionCategoryLabel({ transaction_type: 'refund', category_name: 'Remainder category',
      refund_info: { category_editable: true, linked_categories: linked } })).toBe('Remainder category');
  });
});
