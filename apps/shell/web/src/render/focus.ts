/** 焦点保持助手：列表重排/内容更新前后保持焦点与选区（E2E 覆盖）。 */

export interface FocusSnapshot {
  restore(): void;
}

export function captureFocus(root: HTMLElement): FocusSnapshot {
  const active = document.activeElement as HTMLElement | null;
  if (!active || !root.contains(active)) {
    return { restore: () => {} };
  }
  const key = active.dataset.focusKey ?? "";
  const selection =
    active instanceof HTMLInputElement || active instanceof HTMLTextAreaElement
      ? { start: active.selectionStart, end: active.selectionEnd }
      : null;
  return {
    restore() {
      if (!key) return;
      const next = root.querySelector<HTMLElement>(`[data-focus-key="${key}"]`);
      if (!next) return;
      next.focus();
      if (selection && (next instanceof HTMLInputElement || next instanceof HTMLTextAreaElement)) {
        next.setSelectionRange(selection.start, selection.end);
      }
    },
  };
}
