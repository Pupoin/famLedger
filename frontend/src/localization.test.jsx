import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, describe, expect, it, vi } from 'vitest';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { createRequire } from 'node:module';
import i18n from './i18n';
import catalog from './locales/ui.json';
import { tx, categoryLabel, dateLabel, currentLocale } from './localization';
import AccountSelectDropdown from './components/AccountSelectDropdown';
import ReimbursementBadge from './components/ReimbursementBadge';
import SureCashflowSankey from './components/ds/SureCashflowSankey';
import { apiErrorMessage } from './api/errorMessages';

vi.mock('./CurrencyContext', () => ({ useCurrency: () => ({ symbol: '$' }) }));
vi.mock('./ToastContext', () => ({ useToast: () => ({ showToast: () => {} }) }));
afterEach(() => i18n.changeLanguage('en'));

describe('bilingual UI and unchanged financial data', () => {
  it('translates both original Chinese and English labels when switching languages', async () => {
    await i18n.changeLanguage('en');
    expect(tx('信用卡')).toBe('Credit card');
    expect(currentLocale()).toBe('en-US');
    await i18n.changeLanguage('zh');
    expect(tx('信用卡')).toBe('信用卡');
    expect(tx('Username')).toBe('用户名');
    expect(currentLocale()).toBe('zh-CN');
  });

  it('preserves interpolated user content, zero amounts and unknown labels', async () => {
    await i18n.changeLanguage('en');
    expect(tx('主卡所有者：{p0}', { p0: '取消' })).toBe('Primary card owner: 取消');
    expect(tx('退款: -{p0}', { p0: 0 })).toContain('0');
    expect(categoryLabel('餐饮美食')).toBe('Dining');
    expect(categoryLabel('我的餐饮美食')).toBe('我的餐饮美食');
    expect(tx(null)).toBeNull();
    expect(tx('客户自定义名称_未翻译')).toBe('客户自定义名称_未翻译');
  });

  it('translates backend explanations without changing inserted family names', async () => {
    await i18n.changeLanguage('en');
    expect(apiErrorMessage('该家庭组已处于解散归档状态')).not.toMatch(/\p{Script=Han}/u);
    const message = tx('家庭组「我的测试家庭」已成功解散，所有成员已平稳恢复至个人独立空间，账户与历史账务完整保留。');
    expect(message).toContain('我的测试家庭');
    expect(message).toMatch(/dissolv/i);
    await i18n.changeLanguage('zh');
    expect(apiErrorMessage([{ loc: ['body', 'amount'], msg: 'Input should be greater than 0', input: 'SECRET' }])).toBe('amount: 输入值必须大于 0');
  });

  it('formats date captions without mixing Chinese units into English ranges', async () => {
    await i18n.changeLanguage('en');
    expect(dateLabel('2026年07月06日 至 2026年10月03日')).toBe('2026-07-06 to 2026-10-03');
    expect(dateLabel('2026年07月06日 – 2026年10月03日')).toBe('2026-07-06 – 2026-10-03');
    expect(dateLabel('2026年10月')).toBe('2026-10');
    await i18n.changeLanguage('zh');
    expect(dateLabel('2026年10月')).toBe('2026年10月');
    expect(dateLabel('Oct 04, 2026')).toBe('2026年10月4日');
  });

  it('keeps account names, owner names and select values intact in English', async () => {
    await i18n.changeLanguage('en');
    const account = { id: 'private-primary', name: '取消', account_type: 'credit_card', owner: '信用卡', is_owner: false, relationship_only: true };
    const html = renderToStaticMarkup(<AccountSelectDropdown value={account.id} selectedAccountFallback={account} accounts={[]} emptyLabel="无 (独立主卡)" />);
    expect(html).toContain('取消');
    expect(html).toContain('Primary card owner: 信用卡');
    expect(html).toContain('value="private-primary"');
    expect(html).not.toContain('value="Credit card"');
  });

  it('translates reimbursement status while retaining the stored status and counterparty', async () => {
    const transaction = { is_reimbursable: true, reimbursement_status: '审批中', counterparty: '我的公司', extra: { reimbursement_type: 'corporate' } };
    await i18n.changeLanguage('en');
    const html = renderToStaticMarkup(<ReimbursementBadge txn={transaction} />);
    expect(html).toContain('我的公司');
    expect(html).not.toContain('审批中');
    expect(transaction.reimbursement_status).toBe('审批中');
    await i18n.changeLanguage('zh');
    expect(renderToStaticMarkup(<ReimbursementBadge txn={transaction} />)).toContain('审批中');
  });

  it('changes Sankey labels while preserving all SVG paths and monetary values', async () => {
    const data = { income_sources: [{ name: '工资薪酬', amount: 20 }], pool: { name: 'Cash Flow', amount: 12.34 }, expense_destinations: [{ name: '餐饮美食', amount: 12.34 }] };
    const render = () => renderToStaticMarkup(<MemoryRouter><SureCashflowSankey data={data} /></MemoryRouter>);
    await i18n.changeLanguage('en');
    const english = render();
    await i18n.changeLanguage('zh');
    const chinese = render();
    const paths = html => [...html.matchAll(/\sd="([^"]+)"/g)].map(match => match[1]);
    expect(paths(english)).toEqual(paths(chinese));
    expect(paths(english).length).toBeGreaterThan(0);
    expect(english).toContain('Dining');
    expect(chinese).toContain('餐饮美食');
    expect(english).toContain('$12.34');
    expect(chinese).toContain('$12.34');
  });
});

describe('translation coverage', () => {
  it('provides both languages and preserves every interpolation placeholder', () => {
    const names = value => [...new Set(value.match(/\{p\d+\}/g) || [])].sort();
    for (const [source, entry] of Object.entries(catalog)) {
      expect(entry.zh, source).toBeTruthy();
      expect(entry.en, source).toBeTruthy();
      expect(names(entry.zh), source).toEqual(names(source));
      expect(names(entry.en), source).toEqual(names(source));
    }
  });

  it('covers every literal UI translation call across all frontend source files', () => {
    const parser = createRequire(import.meta.url)('@babel/parser');
    const directory = path.dirname(fileURLToPath(import.meta.url));
    const missing = [];
    function visit(node, filename) {
      if (!node || typeof node !== 'object') return;
      if (node.type === 'CallExpression' && node.callee?.name === 'tx' && node.arguments[0]?.type === 'StringLiteral') {
        const source = node.arguments[0].value;
        if (source && !catalog[source]) missing.push(`${filename}:${node.loc.start.line}: ${source}`);
      }
      for (const [key, value] of Object.entries(node)) {
        if (['loc', 'extra', 'leadingComments', 'trailingComments', 'innerComments'].includes(key)) continue;
        if (Array.isArray(value)) value.forEach(child => visit(child, filename));
        else if (value && typeof value === 'object') visit(value, filename);
      }
    }
    function scan(folder) {
      for (const entry of fs.readdirSync(folder, { withFileTypes: true })) {
        const filename = path.join(folder, entry.name);
        if (entry.isDirectory()) scan(filename);
        else if (/\.(js|jsx)$/.test(filename) && !filename.includes('.test.')) visit(parser.parse(fs.readFileSync(filename, 'utf8'), { sourceType: 'module', plugins: ['jsx'] }), filename);
      }
    }
    scan(directory);
    expect(missing).toEqual([]);
  });

  it('binds localization helpers in every frontend module to prevent runtime reference errors', () => {
    const require = createRequire(import.meta.url);
    const parser = require('@babel/parser');
    const traverse = require('@babel/traverse').default;
    const helpers = new Set(['tx', 'useLocale', 'categoryLabel', 'dateLabel', 'currentLocale']);
    const missing = [];
    function scan(folder) {
      for (const entry of fs.readdirSync(folder, { withFileTypes: true })) {
        const filename = path.join(folder, entry.name);
        if (entry.isDirectory()) scan(filename);
        else if (/\.(js|jsx)$/.test(filename) && !filename.includes('.test.')) {
          const ast = parser.parse(fs.readFileSync(filename, 'utf8'), { sourceType: 'module', plugins: ['jsx'] });
          traverse(ast, {
            ReferencedIdentifier(reference) {
              if (helpers.has(reference.node.name) && !reference.scope.hasBinding(reference.node.name)) {
                missing.push(`${filename}:${reference.node.loc.start.line}: ${reference.node.name}`);
              }
            },
          });
        }
      }
    }
    scan(path.dirname(fileURLToPath(import.meta.url)));
    expect(missing).toEqual([]);
  });
});
