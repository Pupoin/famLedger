import { describe, expect, it } from 'vitest';
import { layoutMerchantTreemap } from './merchantTreemap';

describe('merchant treemap area is proportional to spending', () => {
  it.each([
    [320, 242, [500, 250, 100, 50, 25, 10, 5, 60]],
    [600, 274, [500, 250, 100, 50, 25, 10, 5, 60]],
    [1000, 274, [500, 250, 100, 50, 25, 10, 5, 60]],
    [320, 242, [9000, 1, 2, 3, 4, 5, 6, 10]],
    [600, 274, [100, 100, 100, 100, 100, 100, 100, 100]],
    [600, 274, [12.34]],
  ])('keeps visible areas proportional in %ipx × %ipx with uniform gaps', (width, height, amounts) => {
    const items = amounts.map((amount, index) => ({ name: `Merchant ${index}`, amount: String(amount), is_other: index === 7 }));
    const total = amounts.reduce((sum, value) => sum + value, 0);
    const tiles = layoutMerchantTreemap(items, width, height);
    expect(tiles).toHaveLength(amounts.length);
    const visibleArea = tiles.reduce((sum, tile) => sum + tile.width * tile.height, 0);
    expect(visibleArea).toBeLessThanOrEqual(width * height + 1e-8);
    for (const tile of tiles) {
      expect(tile.width * tile.height / visibleArea).toBeCloseTo(amounts[tile.index] / total, 10);
      expect(tile.x).toBeGreaterThanOrEqual(0);
      expect(tile.y).toBeGreaterThanOrEqual(0);
      expect(tile.x + tile.width).toBeLessThanOrEqual(width + 1e-8);
      expect(tile.y + tile.height).toBeLessThanOrEqual(height + 1e-8);
      for (const other of tiles) {
        if (tile === other) continue;
        const intersectionWidth = Math.min(tile.x + tile.width, other.x + other.width) - Math.max(tile.x, other.x);
        const intersectionHeight = Math.min(tile.y + tile.height, other.y + other.height) - Math.max(tile.y, other.y);
        expect(intersectionWidth <= -6 + 1e-8 || intersectionHeight <= -6 + 1e-8).toBe(true);
      }
    }
    expect(items.map(item => item.amount)).toEqual(amounts.map(String));
  });

  it('rejects nonpositive and nonfinite amounts without giving them area', () => {
    const tiles = layoutMerchantTreemap([0, -1, NaN, Infinity, 'invalid', 12].map(amount => ({ amount })), 300, 200);
    expect(tiles).toHaveLength(1);
    expect(tiles[0].width * tiles[0].height).toBeCloseTo(60000, 6);
    expect(layoutMerchantTreemap([], 300, 200)).toEqual([]);
    expect(layoutMerchantTreemap([{ amount: 1 }], 0, 200)).toEqual([]);
  });
});
