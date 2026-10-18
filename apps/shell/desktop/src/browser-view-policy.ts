/** 多视图纯策略（O2-2 §11.5-②）——激活回退 / 内存会话 LRU / 派生键匹配。
 *
 * 零 Electron 依赖：可 node --test 直测；`browser-view.ts` 只做创建/销毁接线。
 */

/** order 为最近活跃升序（尾=最新）；返回关闭 `closing` 后的新活跃视图键。 */
export function nextActive(order: readonly string[], closing: string): string | null {
  const rest = order.filter((key) => key !== closing);
  return rest.length > 0 ? rest[rest.length - 1] : null;
}

/** keys 按最近使用升序；淘汰最旧直到剩余 ≤ cap（inUse 永不淘汰）。 */
export function lruEvictions(
  keys: readonly string[],
  inUse: readonly string[],
  cap: number,
): string[] {
  const keep = new Set(inUse);
  const out: string[] = [];
  let remaining = keys.length;
  for (const key of keys) {
    if (remaining <= cap) break;
    if (keep.has(key)) continue;
    out.push(key);
    remaining -= 1;
  }
  return out;
}

/** base 及其 overlay 派生键（`base-<token>`；不吞并 `base1` 等相似前缀）。 */
export function overlayKeysFor(
  keys: readonly string[],
  base: string,
): string[] {
  return keys.filter((key) => key === base || key.startsWith(`${base}-`));
}
