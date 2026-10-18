#!/usr/bin/env node
/** 架构红线检查（P1a）：导入方向 + 危险模式（禁静默吞错）。
 *
 * 注：TS 7（原生版）未暴露 `preProcessFile` 等 JS 编译器 API（实测），
 * 因此导入提取使用「先剥注释、再正则」的保守策略（fixture 测试锁定行为，零依赖）。
 */
import { readdirSync, readFileSync, statSync } from "node:fs";
import path from "node:path";
import process from "node:process";

const ROOT = process.argv[2] ?? path.resolve(import.meta.dirname, "..");
const SRC = path.join(ROOT, "web", "src");
const CSS_SRC = path.join(ROOT, "web", "static");

const RULES = [
  {
    id: "runtime-no-ui",
    message: "runtime 层不得依赖 render/views/components（数据对象层与 UI 无关）",
    include: /[\\/]runtime[\\/]/,
    importBan: [/[\\/]render[\\/]/, /[\\/]views[\\/]/, /[\\/]components[\\/]/],
  },
  {
    id: "runtime-no-dom",
    message: "runtime 层（connection 除外）不得触碰浏览器全局",
    include: /[\\/]runtime[\\/]/,
    exclude: /[\\/]runtime[\\/]connection[\\/]/,
    tokenBan: [
      /\bdocument\b/,
      /\bwindow\b/,
      /\bEventSource\b/,
      /\bfetch\s*\(/,
      /\bXMLHttpRequest\b/,
      /\blocalStorage\b/,
    ],
  },
  {
    id: "connection-transport-only",
    message: "connection 层仅承载出网（不得触碰 document/window/localStorage）",
    include: /[\\/]runtime[\\/]connection[\\/]/,
    tokenBan: [/\bdocument\b/, /\bwindow\b/, /\blocalStorage\b/],
  },
  {
    id: "render-no-runtime",
    message: "render 层为通用 DOM 机制，不得反向依赖 runtime",
    include: /[\\/]render[\\/]/,
    importBan: [/[\\/]runtime[\\/]/],
  },
  {
    id: "views-no-connection",
    message: "视图/组件不得直连 connection 层（经领域服务）",
    include: /[\\/](views|components)[\\/]/,
    importBan: [/[\\/]runtime[\\/]connection[\\/]/],
  },
  {
    id: "protocol-pure",
    message: "protocol 层不得依赖其他 src 目录",
    include: /[\\/]protocol[\\/]/,
    importBan: [/\.\.[\\/]/],
  },
  {
    id: "no-silent-catch",
    message: "禁止静默吞错（.catch(() => null/undefined) 或空 catch）",
    include: /[\\/]src[\\/]/,
    tokenBan: [
      /\.catch\(\s*\(\s*\)\s*=>\s*(null|undefined)\s*\)/,
      /catch\s*(\([^)]*\))?\s*\{\s*\}/,
    ],
  },
];

/** 折叠动画单源守卫（2026-10-16 用户美学原则）：所有收起/展开同一动画。 */
const CSS_RULES = [
  {
    id: "fold-motion-token",
    message: "折叠动画必须使用 var(--motion-structural)（单源令牌）",
    test: (src) => {
      for (const m of src.matchAll(/transition\s*:\s*([^;]+);/g)) {
        if (/grid-template-rows/.test(m[1])
            && !/var\(--motion-structural\)/.test(m[1])) return true;
      }
      return false;
    },
  },
  {
    id: "no-height-collapse",
    message: "禁止 height/max-height 折叠过渡（统一走 grid-template-rows 同令牌）",
    test: (src) => /transition\s*:[^;]*(?:^|[^\w-])(?:max-)?height\b/.test(src),
  },
];

function walkCss(dir) {
  const files = [];
  for (const name of readdirSync(dir)) {
    const full = path.join(dir, name);
    const stat = statSync(full);
    if (stat.isDirectory()) files.push(...walkCss(full));
    else if (name.endsWith(".css")) files.push(full);
  }
  return files;
}

function walk(dir) {
  const files = [];
  for (const name of readdirSync(dir)) {
    const full = path.join(dir, name);
    const stat = statSync(full);
    if (stat.isDirectory()) files.push(...walk(full));
    else if (name.endsWith(".ts")) files.push(full);
  }
  return files;
}

function stripComments(source) {
  return source
    .replace(/\/\*[\s\S]*?\*\//g, "")
    .replace(/\/\/[^\n]*/g, "");
}

/** 保守导入提取：静态 from / 副作用 import / 动态 import()（已剥注释）。 */
function extractImportSpecifiers(source) {
  const code = stripComments(source);
  const specs = [];
  const patterns = [
    /\bfrom\s*["']([^"']+)["']/g,
    /\bimport\s*\(\s*["']([^"']+)["']\s*\)/g,
    /\bimport\s+["']([^"']+)["']/g,
  ];
  for (const pattern of patterns) {
    let match;
    while ((match = pattern.exec(code)) !== null) {
      if (match[1]) specs.push(match[1]);
    }
  }
  return specs;
}

function main() {
  const violations = [];
  let files = [];
  let cssFiles = [];
  try {
    files = walk(SRC);
  } catch {
    files = [];            // CSS-only 夹具/目录缺失容忍（至少一边存在即可）
  }
  try {
    cssFiles = walkCss(CSS_SRC);
  } catch {
    cssFiles = [];
  }
  if (files.length === 0 && cssFiles.length === 0) {
    console.error(`[arch] 源目录不存在：${SRC}`);
    process.exit(1);
  }
  for (const file of files) {
    const rel = path.relative(ROOT, file);
    const source = readFileSync(file, "utf8");
    const code = stripComments(source);
    const imported = extractImportSpecifiers(source).map((spec) =>
      spec.startsWith(".") ? path.resolve(path.dirname(file), spec) : spec);
    for (const rule of RULES) {
      if (rule.include && !rule.include.test(rel)) continue;
      if (rule.exclude && rule.exclude.test(rel)) continue;
      for (const spec of imported) {
        for (const ban of rule.importBan ?? []) {
          if (ban.test(spec)) {
            violations.push(
              `${rel}: [${rule.id}] ${rule.message}（导入 ${path.relative(ROOT, spec)}）`,
            );
          }
        }
      }
      for (const ban of rule.tokenBan ?? []) {
        if (ban.test(code)) {
          violations.push(`${rel}: [${rule.id}] ${rule.message}`);
        }
      }
    }
  }
  for (const file of cssFiles) {
    const rel = path.relative(ROOT, file);
    const source = readFileSync(file, "utf8");
    for (const rule of CSS_RULES) {
      if (rule.test(source)) {
        violations.push(`${rel}: [${rule.id}] ${rule.message}`);
      }
    }
  }
  if (violations.length > 0) {
    for (const line of violations) console.error(`[arch] FAIL ${line}`);
    console.error(`[arch] 失败：${violations.length} 处违规`);
    process.exit(1);
  }
  console.log(`[arch] 检查通过（${files.length} TS + ${cssFiles.length} CSS）`);
}

main();
