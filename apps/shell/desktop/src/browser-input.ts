/** 内置浏览器 · 输入坐标换算（O2-2 P2；纯函数，零 Electron 依赖，可单测）。
 *
 * CDP `DOM.getContentQuads` 的 quad 为**文档坐标系** CSS 像素；
 * `Input.dispatchMouseEvent` 需要**视口坐标系**——减去 layoutViewport.pageX/pageY
 * （pageX/pageY 即页面滚动偏移）。
 * P3：evaluate 返回值展示序列化亦在此层（可单测）。
 */

export interface LayoutViewport {
  pageX: number;
  pageY: number;
}

/** quads（每项 8 数：[x1,y1,x2,y2,x3,y3,x4,y4]）→ 视口坐标中心点；无有效 quad → null。 */
export function quadsToPoint(
  quads: number[][],
  viewport: LayoutViewport,
): { x: number; y: number } | null {
  const quad = quads.find((q) => Array.isArray(q) && q.length >= 8);
  if (quad === undefined) return null;
  const cx = (quad[0] + quad[2] + quad[4] + quad[6]) / 4;
  const cy = (quad[1] + quad[3] + quad[5] + quad[7]) / 4;
  return { x: cx - viewport.pageX, y: cy - viewport.pageY };
}

/** evaluate 返回值 → 展示文本（字符串直出；null/数/布尔 String；对象 JSON；不可序列化回退）。 */
export function serializeValue(raw: unknown): string {
  if (raw === undefined) return "undefined";
  if (typeof raw === "string") return raw;
  if (raw === null || typeof raw === "number" || typeof raw === "boolean") {
    return String(raw);
  }
  try {
    return JSON.stringify(raw) ?? String(raw);
  } catch {
    return String(raw);
  }
}
