import { describe, expect, it } from 'vitest';
import { createLatestRequest } from './latestRequest';

describe('transaction page request coordination', () => {
  it('blocks repeated load-more requests until the current page completes', () => {
    const queue = createLatestRequest();
    const page = queue.start();
    expect(queue.start()).toBeNull();
    page.finish();
    expect(queue.start().isCurrent()).toBe(true);
  });

  it('aborts a previous filter request and ignores its late response', async () => {
    const queue = createLatestRequest();
    const previous = queue.start();
    const current = queue.start({ replace: true });
    let shown = null;
    await Promise.resolve().then(() => { if (current.isCurrent()) shown = 'new filter'; });
    await Promise.resolve().then(() => { if (previous.isCurrent()) shown = 'old filter'; });
    expect(previous.signal.aborted).toBe(true);
    expect(shown).toBe('new filter');
    previous.finish();
    expect(current.isCurrent()).toBe(true);
    expect(queue.start()).toBeNull();
  });

  it('cancels on unmount and permits a fresh Strict Mode effect', () => {
    const queue = createLatestRequest();
    const previous = queue.start();
    queue.cancel();
    expect(previous.signal.aborted).toBe(true);
    expect(previous.isCurrent()).toBe(false);
    expect(queue.start().isCurrent()).toBe(true);
  });
});
