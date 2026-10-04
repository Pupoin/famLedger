import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it, vi } from 'vitest';
import SplitTransactionModal from './SplitTransactionModal';

vi.mock('../ToastContext', () => ({ useToast: () => ({ showToast: vi.fn() }) }));

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
});
