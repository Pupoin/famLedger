import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import i18n from '../i18n';
import SplitTransactionModal from './SplitTransactionModal';

vi.mock('../ToastContext', () => ({ useToast: () => ({ showToast: vi.fn() }) }));
beforeEach(() => i18n.changeLanguage('zh'));

describe('split editing uses fixed account booking money', () => {
  it('keeps the booking amount and currency when original and preference currencies differ', () => {
    const html = renderToStaticMarkup(<SplitTransactionModal isOpen transaction={{
      id:'expense', amount:'100', currency:'USD', original_amount:'80', original_currency:'EUR',
      display_amount:'700', display_currency:'CNY', transaction_type:'expense',
    }} />);
    const text = html.replace(/<[^>]*>/g, '');
    expect(text).toContain('$100.00');
    expect(text).toContain('USD');
    expect(text).not.toContain('700');
    expect(text).not.toContain('¥');
  });
  it.each(['expense', 'refund'])('renders initial split rows and categories above the transaction drawer for %s', transaction_type => {
    const html = renderToStaticMarkup(<SplitTransactionModal isOpen transaction={{ id: 'purchase', amount: '100', currency: 'CNY', transaction_type }}
      categories={[{ id: 'food', name: 'Food' }, { id: 'shopping', name: 'Shopping' }]} />);
    expect(html).toContain('role="dialog"'); expect(html).toContain('z-[80]');
    expect(html).toContain('value="food"'); expect(html).toContain('value="shopping"');
    expect(html.match(/value="50.00"/g)).toHaveLength(2);
  });
  it('offers clearing existing splits without changing the transaction amount', () => {
    const html = renderToStaticMarkup(<SplitTransactionModal isOpen transaction={{ id: 'purchase', currency: 'CNY', amount: '100', is_split: true,
      splits: [{ amount: '30', category_id: 'food' }, { amount: '70', category_id: 'shopping' }] }} />);
    expect(html).toContain('解除拆分'); expect(html).toContain('value="30.00"'); expect(html).toContain('value="70.00"');
  });
});
