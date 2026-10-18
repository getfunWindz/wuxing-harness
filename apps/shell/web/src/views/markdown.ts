/** 轻量 Markdown → DOM（报告内嵌渲染——M7 挂账 C 关闭的一部分）。
    支持：# 标题（映射 h3-h6，旧壳口径）/ - 列表 / ``` 代码块 / 段落。 */
export function renderMarkdown(text: string): HTMLElement {
  const host = document.createElement("div");
  host.className = "report-md";
  const lines = String(text).split(/\r?\n/);
  let list: HTMLUListElement | null = null;
  let code: HTMLPreElement | null = null;
  for (const line of lines) {
    if (line.trim().startsWith("```")) {
      if (code) { host.appendChild(code); code = null; } else { code = document.createElement("pre"); }
      continue;
    }
    if (code) {
      code.textContent = `${code.textContent ?? ""}${(code.textContent ?? "") === "" ? "" : "\n"}${line}`;
      continue;
    }
    const heading = /^(#{1,6})\s+(.*)$/.exec(line);
    if (heading) {
      list = null;
      const level = Math.min(6, (heading[1] ?? "#").length + 2);
      const el = document.createElement(`h${level}`);
      el.textContent = heading[2] ?? "";
      host.appendChild(el);
      continue;
    }
    const item = /^\s*[-*]\s+(.*)$/.exec(line);
    if (item) {
      if (!list) {
        list = document.createElement("ul");
        host.appendChild(list);
      }
      const li = document.createElement("li");
      li.textContent = item[1] ?? "";
      list.appendChild(li);
      continue;
    }
    if (line.trim() === "") {
      list = null;
      continue;
    }
    list = null;
    const p = document.createElement("p");
    p.textContent = line;
    host.appendChild(p);
  }
  if (code) host.appendChild(code);
  return host;
}
