/** 品牌组件（外观复现 A3 → 水墨融入 v1，2026-09-19）
 *
 * 用户裁决（评审页会话）：
 *  - 粒子：21 粒 · 三墨阶（焦墨屑 / 浓墨点 / 淡墨晕）· 慢速左飘 · 若隐若现（淡入→飘散→淡出→间歇）——
 *    2026-09-19 用户反馈：可见度加强（密度不变 21 粒；速度 ≈+35%；不透明度 ≈+30%；间歇缩短）
 *  - 飞白：在「无形」渐隐区画竖向枯笔笔丝（以所在容器底色蚀刻；底色取 CSS 变量 --brand-etch-bg）
 *  - 字体：与主标题统一衬线（见 theme/components.css）
 * 参数为「默认档」；主题与自定义入口批次将开放为可配置项（不在本批）。
 */
import { h } from "../render/dom.ts";

/** 墨色三阶（rgb 分量字符串） */
const TONE_JIAO = "30, 30, 30";   // 焦墨屑
const TONE_NONG = "44, 42, 38";   // 浓墨点
const TONE_DAN = "48, 47, 45";    // 淡墨晕

const DUST_COUNT = 21;

/** 品牌元素（中英文 + 飞白 canvas + 墨粒子 canvas）。variant: "sm"（顶栏）| "hero"（欢迎页）。 */
export function createBrand(variant: "sm" | "hero" = "sm"): HTMLElement {
  const cls = variant === "hero" ? "brand brand-hero" : "brand";
  return h("span", { class: cls, attrs: { "data-brand": "" } },
    h("span", { class: "brand-mark", text: "无形" }),
    h("span", { class: "brand-en", text: "WUXING" }),
    h("canvas", { class: "brand-etch", attrs: { "aria-hidden": "true" } }),
    h("canvas", { class: "brand-dust", attrs: { "aria-hidden": "true" } }));
}

const activeDust = new WeakSet<HTMLCanvasElement>();
const activeEtch = new WeakSet<HTMLCanvasElement>();

/** 在已插入的 DOM 范围内挂载全部品牌墨粒子（幂等）。 */
export function mountBrandDust(scope: HTMLElement): void {
  if (typeof window === "undefined") return;
  if (window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
  scope.querySelectorAll<HTMLCanvasElement>("[data-brand] > canvas.brand-dust").forEach((canvas) => {
    if (activeDust.has(canvas)) return;
    activeDust.add(canvas);
    startDust(canvas);
  });
}

/** 在已插入的 DOM 范围内挂载全部品牌飞白蚀刻（幂等；静态绘制，布局变化重绘）。 */
export function mountBrandEtch(scope: HTMLElement): void {
  if (typeof window === "undefined") return;
  scope.querySelectorAll<HTMLElement>("[data-brand]").forEach((brand) => {
    const canvas = brand.querySelector<HTMLCanvasElement>("canvas.brand-etch");
    if (!canvas || activeEtch.has(canvas)) return;
    activeEtch.add(canvas);
    const redraw = (): void => { drawEtch(canvas, brand); };
    requestAnimationFrame(redraw);
    if (typeof ResizeObserver !== "undefined") new ResizeObserver(redraw).observe(brand);
  });
}

function hash(n: number): number {
  const s = Math.sin(n * 127.1 + 311.7) * 43758.5453;
  return s - Math.floor(s);
}

/** 飞白蚀刻：竖向笔丝（左密右疏，61% 区内）+ 边缘蚀刻点。 */
function drawEtch(canvas: HTMLCanvasElement, brand: HTMLElement): void {
  const mark = brand.querySelector<HTMLElement>(".brand-mark");
  if (!mark) return;
  const ctx = canvas.getContext("2d");
  if (!ctx) return;
  const dpr = Math.min(window.devicePixelRatio || 1, 2);
  const rect = canvas.getBoundingClientRect();
  const w = Math.max(1, Math.round(rect.width));
  const hgt = Math.max(1, Math.round(rect.height));
  canvas.width = Math.round(w * dpr);
  canvas.height = Math.round(hgt * dpr);
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, w, hgt);

  const markRect = mark.getBoundingClientRect();
  const x0 = markRect.left - rect.left;
  const y0 = markRect.top - rect.top;
  const mw = markRect.width;
  const mh = markRect.height;
  const zoneW = mw * 0.61;
  const paper = (getComputedStyle(brand).getPropertyValue("--brand-etch-bg") || "").trim() || "#ffffff";

  ctx.fillStyle = paper;
  const N = 60;
  for (let i = 0; i < N; i++) {
    const t = Math.pow(hash(i * 7.3 + 1.7), 2.2);
    const x = x0 + t * zoneW;
    const wdt = 0.5 + hash(i * 3.9 + 11.1) * 1.2;
    const alpha = (0.07 + hash(i * 5.7 + 3.3) * 0.3) * (1 - t * 0.85);
    if (alpha < 0.03) continue;
    ctx.globalAlpha = alpha;
    const yy0 = y0 + hash(i * 2.1) * mh * 0.35;
    const yy1 = y0 + mh - hash(i * 4.7) * mh * 0.35;
    ctx.fillRect(x, yy0, wdt, yy1 - yy0);
  }
  for (let s = 0; s < 22; s++) {
    const ts = Math.pow(hash(s * 9.1 + 5.5), 1.8);
    const sx = x0 + ts * zoneW + hash(s * 1.3) * 3;
    const sy = y0 + hash(s * 6.1) * mh;
    ctx.globalAlpha = (0.1 + hash(s * 8.8) * 0.3) * (1 - ts * 0.7);
    ctx.beginPath();
    ctx.arc(sx, sy, 0.5 + hash(s * 2.9) * 1.1, 0, Math.PI * 2);
    ctx.fill();
  }
  ctx.globalAlpha = 1;
}

interface Particle {
  x: number; y: number; vx: number; vy: number;
  r: number; aMax: number; kind: number;
  life: number; maxLife: number; wait: number;
}

/** 生成/重置一粒墨点（三墨阶之一）。stagger>0 时先等待再出现（若隐若现）。 */
function resetParticle(p: Particle, w: number, hgt: number, stagger: boolean): void {
  p.kind = Math.random();
  if (p.kind > 0.88) { p.r = 0.4 + Math.random() * 0.5; p.aMax = 0.25 + Math.random() * 0.17; }
  else if (p.kind > 0.55) { p.r = 0.7 + Math.random() * 0.9; p.aMax = 0.13 + Math.random() * 0.14; }
  else { p.r = 1.2 + Math.random() * 2.0; p.aMax = 0.055 + Math.random() * 0.06; }
  p.vx = -(0.038 + Math.random() * 0.135);
  p.vy = -(0.009 + Math.random() * 0.05);
  p.x = Math.random() * w;
  p.y = hgt * (0.06 + Math.random() * 0.88);
  p.maxLife = 420 + Math.random() * 720;
  p.life = stagger ? 0 : Math.random() * p.maxLife;
  p.wait = stagger ? 45 + Math.random() * 320 : 0;
}

function startDust(canvas: HTMLCanvasElement): void {
  const context = canvas.getContext("2d");
  if (!context) return;
  const ctx: CanvasRenderingContext2D = context;   // 闭包内类型收窄保持
  let w = 1;
  let hgt = 1;

  function fit(): void {
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    const r = canvas.getBoundingClientRect();
    w = Math.max(1, Math.round(r.width));
    hgt = Math.max(1, Math.round(r.height));
    canvas.width = Math.round(w * dpr);
    canvas.height = Math.round(hgt * dpr);
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  }
  fit();
  if (typeof ResizeObserver !== "undefined") {
    new ResizeObserver(fit).observe(canvas);
  } else {
    window.addEventListener("resize", fit);
  }

  const particles: Particle[] = [];
  for (let i = 0; i < DUST_COUNT; i++) {
    const p: Particle = { x: 0, y: 0, vx: 0, vy: 0, r: 1, aMax: 0.1, kind: 0, life: 0, maxLife: 500, wait: 0 };
    resetParticle(p, w, hgt, false);
    particles.push(p);
  }
  for (const p of particles) p.life = Math.random() * p.maxLife;   // 初始错峰

  let last = performance.now();

  function tick(now: number): void {
    if (!canvas.isConnected) return;   // 组件已移除 → 停帧
    requestAnimationFrame(tick);
    if (document.hidden) { last = now; return; }
    const dt = Math.min(48, now - last);
    last = now;
    const step = dt / 16.67;
    ctx.clearRect(0, 0, w, hgt);
    for (const p of particles) {
      if (p.wait > 0) {   // 间歇期（若隐若现：不在场）
        p.wait -= step;
        if (p.wait <= 0) resetParticle(p, w, hgt, false);
        continue;
      }
      p.x += p.vx * step;
      p.y += p.vy * step;
      p.life += step;
      if (p.life > p.maxLife || p.x < -10 || p.y < -10) {
        p.wait = 90 + Math.random() * 360;
        continue;
      }
      /* 寿命两端淡入淡出；区域边缘自然消散 */
      const env = Math.min(1, p.life / 90) * Math.min(1, (p.maxLife - p.life) / 160);
      const edge = Math.max(0, Math.min(1, Math.min(
        Math.min(p.x, w - p.x) / 14,
        Math.min(p.y, hgt - p.y) / 10)));
      const a = p.aMax * env * edge;
      if (a <= 0.002) continue;
      if (p.kind <= 0.55) {   // 淡墨晕：径向渐变软团
        const g = ctx.createRadialGradient(p.x, p.y, 0, p.x, p.y, p.r * 2.4);
        g.addColorStop(0, `rgba(${TONE_DAN}, ${a})`);
        g.addColorStop(1, `rgba(${TONE_DAN}, 0)`);
        ctx.fillStyle = g;
        ctx.beginPath();
        ctx.arc(p.x, p.y, p.r * 2.4, 0, Math.PI * 2);
        ctx.fill();
      } else {   // 浓墨点 / 焦墨屑：微椭圆（随飘散方向）
        ctx.globalAlpha = a;
        ctx.beginPath();
        ctx.ellipse(p.x, p.y, p.r * 1.5, p.r * 0.9, 0, 0, Math.PI * 2);
        ctx.fillStyle = `rgba(${p.kind > 0.88 ? TONE_JIAO : TONE_NONG}, 1)`;
        ctx.fill();
        ctx.globalAlpha = 1;
      }
    }
  }
  requestAnimationFrame(tick);
}
