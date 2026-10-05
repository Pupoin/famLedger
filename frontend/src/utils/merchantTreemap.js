// Row breaks favour wide tiles; visible areas remain proportional after gutters.
export function layoutMerchantTreemap(items, width, height, targetRatio = 3, gap = 6) {
  if (!Number.isFinite(width) || !Number.isFinite(height) || width <= 0 || height <= 0) return [];
  let nodes = (Array.isArray(items) ? items : [])
    .map((item, index) => ({ item, index, value: Number(item?.amount) }))
    .filter(node => Number.isFinite(node.value) && node.value > 0)
    .sort((a, b) => b.value - a.value || a.index - b.index);
  if (!nodes.length) return [];

  const maximum = nodes[0].value;
  nodes.forEach(node => { node.value /= maximum; });
  nodes = nodes.filter(node => node.value > 0);
  const total = nodes.reduce((sum, node) => sum + node.value, 0);
  const ratio = Number.isFinite(targetRatio) && targetRatio > 0 ? targetRatio : 3;
  const gutter = Number.isFinite(gap) && gap >= 0 ? gap : 6;
  let bestScore = Infinity;
  let bestRows = [];

  // Top seven merchants plus Other: at most 128 possible sets of row breaks.
  for (let breaks = 0; breaks < 2 ** (nodes.length - 1); breaks += 1) {
    const rows = [];
    let start = 0;
    for (let end = 0; end < nodes.length; end += 1) {
      if (end === nodes.length - 1 || (breaks & (2 ** end))) {
        const value = nodes.slice(start, end + 1).reduce((sum, node) => sum + node.value, 0);
        rows.push({ start, end, value, usableWidth: width - (end - start) * gutter });
        start = end + 1;
      }
    }
    const usableHeight = height - (rows.length - 1) * gutter;
    if (usableHeight <= 0 || rows.some(row => row.usableWidth <= 0)) continue;
    // A shared area-per-value factor makes every visible rectangle proportional.
    const areaScale = usableHeight / rows.reduce((sum, row) => sum + row.value / row.usableWidth, 0);
    let score = 0;
    for (const row of rows) {
      row.height = areaScale * row.value / row.usableWidth;
      for (let index = row.start; index <= row.end; index += 1) {
        const tileWidth = row.usableWidth * nodes[index].value / row.value;
        const deviation = Math.log(Math.max(tileWidth, Number.MIN_VALUE))
          - Math.log(Math.max(row.height, Number.MIN_VALUE)) - Math.log(ratio);
        score += nodes[index].value / total * deviation ** 2;
      }
    }
    if (score < bestScore) {
      bestScore = score;
      bestRows = rows;
    }
  }

  const tiles = [];
  let y = 0;
  for (const row of bestRows) {
    let x = 0;
    for (let index = row.start; index <= row.end; index += 1) {
      const tileWidth = row.usableWidth * nodes[index].value / row.value;
      tiles.push({ item: nodes[index].item, index: nodes[index].index, x, y, width: tileWidth, height: row.height });
      x += tileWidth + gutter;
    }
    y += row.height + gutter;
  }
  return tiles;
}
