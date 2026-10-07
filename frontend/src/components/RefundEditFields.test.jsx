import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { beforeEach, describe, expect, it } from 'vitest';
import i18n from '../i18n';
import RefundEditFields from './RefundEditFields';

beforeEach(() => i18n.changeLanguage('zh'));
const render = changes => renderToStaticMarkup(<RefundEditFields transaction={{ transaction_type: 'refund' }}
  candidates={[{ id: 'purchase', narration: 'Original purchase', remaining_refundable: '70', original_currency: 'CNY', transacted_at: '2026-09-09' }]}
  loading={false} search="" onSearch={() => {}} originalId="purchase" onOriginalChange={() => {}}
  originalAmount="" onOriginalAmountChange={() => {}} refundAmount="" onRefundAmountChange={() => {}}
  currency="USD" onUnlink={() => {}} unlinking={false} privacyMode={false} {...changes} />);

describe('refund editor', () => {
  it('provides matching and explicit two-currency allocation without submitting on selection', () => {
    const html = render();
    expect(html).toContain('Original purchase'); expect(html).toContain('原消费冲抵金额');
    expect(html).toContain('使用退款原币金额'); expect(html).toContain('USD'); expect(html).toContain('CNY');
    expect(html).toContain('保存交易时同时提交退款匹配与冲抵额度。');
  });
  it('keeps fully allocated refunds following their original category and offers unlinking', () => {
    const html = render({ transaction: { transaction_type: 'refund', refund_info: { is_linked: true,
      is_fully_allocated: true, allocated_amount: '70', currency: 'CNY' } } });
    expect(html).toContain('解除与原消费的冲抵关联');
    expect(html).toContain('已关联退款随原消费分类');
    expect(html).not.toContain('<select');
    expect(html).toMatch(/<button type="button"/);
  });
  it('masks refund allocation amounts and candidate amounts in privacy mode', () => {
    const html = render({ privacyMode: true, originalId: '', transaction: { transaction_type: 'refund',
      refund_info: { is_linked: true, allocated_amount: '70', currency: 'CNY' } } });
    expect(html).toContain('••••••'); expect(html.replace(/<[^>]*>/g, '')).not.toContain('70');
  });
  it('defaults to recommendations and allows opting into all historical purchases', () => {
    const shared = { originalId: '', onRecommendationsChange: () => {} };
    const defaultHtml = render(shared);
    expect(defaultHtml).toContain('搜索全部历史消费');
    expect(defaultHtml).not.toMatch(/data-testid="search-historical-refund-purchases"[^>]*checked/);
    expect(defaultHtml).not.toContain('type="search"');
    const historicalHtml = render({ ...shared, recommendationsOnly: false });
    expect(historicalHtml).toMatch(/data-testid="search-historical-refund-purchases"[^>]*checked/);
    expect(historicalHtml).toContain('type="search"');
  });
  it('offers an immediate allocation action without unlocking the transaction editor', () => {
    const html = render({ currency: 'CNY', transaction: { transaction_type: 'refund', original_currency: 'CNY', original_amount: '50' }, onAllocate: () => {} });
    const button = html.match(/<button[^>]*data-testid="confirm-refund-allocation"[^>]*>/)[0];
    expect(button).not.toMatch(/\sdisabled(?:=|\s|>)/);
    expect(html).toContain('确认冲抵');
  });
  it('disables mutations for readonly transactions and invalid cross-currency quantities', () => {
    for (const changes of [{ canManage: false }, { originalAmount: '80' }]) {
      const html = render({ transaction: { transaction_type: 'refund', original_currency: 'USD', original_amount: '50' }, onAllocate: () => {}, ...changes });
      expect(html.match(/<button[^>]*data-testid="confirm-refund-allocation"[^>]*>/)[0]).toMatch(/\sdisabled(?:=|\s|>)/);
    }
  });
  it('shows candidate scores and query errors in the panel', () => {
    const html = render({ candidates: [{ id: 'purchase', narration: 'Purchase', original_currency: 'CNY', remaining_refundable: '70', similarity_score: .873 }], error: 'Candidate lookup failed' });
    expect(html).toContain('87%'); expect(html).toContain('Candidate lookup failed');
  });
});
