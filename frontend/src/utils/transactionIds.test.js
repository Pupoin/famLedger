import { webcrypto } from 'node:crypto';
import { describe, expect, it, vi } from 'vitest';
import { createTransactionExternalId } from './transactionIds';

describe('transaction external IDs on secure and LAN HTTP pages', () => {
  it('uses native randomUUID when available', () => {
    const uuid = '01234567-89ab-4cde-8fab-0123456789ab';
    const cryptoApi = { randomUUID: vi.fn(() => uuid), getRandomValues: vi.fn() };
    expect(createTransactionExternalId(cryptoApi)).toBe(`manual:${uuid}`);
    expect(cryptoApi.getRandomValues).not.toHaveBeenCalled();
  });

  it('produces unique UUID v4 IDs when randomUUID is unavailable over HTTP', () => {
    const cryptoApi = { getRandomValues: (bytes) => webcrypto.getRandomValues(bytes) };
    const ids = Array.from({ length: 1000 }, () => createTransactionExternalId(cryptoApi));
    expect(new Set(ids).size).toBe(ids.length);
    for (const id of ids) {
      expect(id).toMatch(/^manual:[\da-f]{8}-[\da-f]{4}-4[\da-f]{3}-[89ab][\da-f]{3}-[\da-f]{12}$/);
    }
  });
});
