#!/usr/bin/env node
/** 部署前端产物 → wuxing/shell/web/static/next/（浏览器 /next/ 与 Electron 共用）。 */
import { copyFileSync, existsSync, mkdirSync, readdirSync, rmSync, statSync } from "node:fs";
import path from "node:path";
import process from "node:process";

const root = path.resolve(import.meta.dirname, "..");
const dist = path.join(root, "web", "dist");
const staticDir = path.join(root, "web", "static");
const target = path.resolve(root, "..", "..", "wuxing", "shell", "web", "static", "next");

/** 显式递归拷贝（fs.cpSync 在本机 Node 24.12 + 中文路径下崩溃退出 127——实测）。 */
function copyTree(src, dest) {
  mkdirSync(dest, { recursive: true });
  for (const entry of readdirSync(src)) {
    const from = path.join(src, entry);
    const to = path.join(dest, entry);
    if (statSync(from).isDirectory()) copyTree(from, to);
    else copyFileSync(from, to);
  }
}

if (!existsSync(dist)) {
  console.error("[deploy] 缺少构建产物——先运行 npm run build");
  process.exit(1);
}
rmSync(target, { recursive: true, force: true });
mkdirSync(target, { recursive: true });
copyTree(dist, target);
if (existsSync(staticDir)) {
  copyTree(staticDir, target);
}
console.log(`[deploy] 已部署 → ${target}`);
