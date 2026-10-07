import { describe, expect, it, vi } from 'vitest';
import { createModulePreloader } from './modulePreloader';

describe('report module preloading', () => {
  it('shares an idle prefetch with subsequent route navigation', async () => {
    const module = { default: () => null };
    const importer = vi.fn().mockResolvedValue(module);
    const load = createModulePreloader(importer);
    const prefetched = load();
    expect(load()).toBe(prefetched);
    await prefetched;
    expect(await load()).toBe(module);
    expect(importer).toHaveBeenCalledTimes(1);
  });

  it('allows navigation to retry an unsuccessful prefetch', async () => {
    const module = { default: () => null };
    const importer = vi.fn().mockRejectedValueOnce(new Error('offline')).mockResolvedValueOnce(module);
    const load = createModulePreloader(importer);
    await expect(load()).rejects.toThrow('offline');
    expect(await load()).toBe(module);
    expect(importer).toHaveBeenCalledTimes(2);
  });
});
