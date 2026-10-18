/** 渲染机制层：DOM 构造与批量挂载（呈现层经 `h()` 使用，不散落 DOM API）。 */

export type Child = Node | string | number | null | undefined | false;

export interface DomProps {
  class?: string;
  dataset?: Record<string, string>;
  style?: Partial<CSSStyleDeclaration>;
  attrs?: Record<string, string>;
  text?: string;
  [key: string]: unknown;
}

export function h(tag: string, props?: DomProps | null, ...children: Child[]): HTMLElement {
  const element = document.createElement(tag);
  if (props) {
    for (const [key, value] of Object.entries(props)) {
      if (value === undefined || value === null) continue;
      if (key.startsWith("on") && typeof value === "function") {
        element.addEventListener(key.slice(2).toLowerCase(), value as EventListener);
      } else if (key === "class") {
        element.className = String(value);
      } else if (key === "dataset") {
        Object.assign(element.dataset, value as Record<string, string>);
      } else if (key === "style") {
        Object.assign(element.style, value as Partial<CSSStyleDeclaration>);
      } else if (key === "attrs") {
        for (const [attr, attrValue] of Object.entries(value as Record<string, string>)) {
          element.setAttribute(attr, attrValue);
        }
      } else if (key === "text") {
        element.textContent = String(value);
      } else {
        (element as unknown as Record<string, unknown>)[key] = value;
      }
    }
  }
  appendChildren(element, children);
  return element;
}

export function appendChildren(host: Node, children: readonly Child[]): void {
  for (const child of children) {
    if (child === null || child === undefined || child === false) continue;
    host.appendChild(typeof child === "object" ? child : document.createTextNode(String(child)));
  }
}

export function clear(host: Node): void {
  while (host.firstChild) {
    host.removeChild(host.firstChild);
  }
}

export function mount(host: HTMLElement, ...children: Child[]): void {
  clear(host);
  appendChildren(host, children);
}

const SVG_NS = "http://www.w3.org/2000/svg";

/** 线性图标（SVG path 序列）——静态资源禁 emoji（测试守卫），图标一律 SVG。 */
export function svgIcon(paths: readonly string[], size = 16): SVGElement {
  const el = document.createElementNS(SVG_NS, "svg");
  el.setAttribute("viewBox", "0 0 24 24");
  el.setAttribute("width", String(size));
  el.setAttribute("height", String(size));
  el.setAttribute("fill", "none");
  el.setAttribute("stroke", "currentColor");
  el.setAttribute("stroke-width", "1.8");
  el.setAttribute("stroke-linecap", "round");
  el.setAttribute("stroke-linejoin", "round");
  for (const d of paths) {
    const path = document.createElementNS(SVG_NS, "path");
    path.setAttribute("d", d);
    el.appendChild(path);
  }
  return el;
}
