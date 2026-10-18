/** 输入草稿（M7 CP-1 · B2）：localStorage 按工作区持久化。

草稿是体验优化不是生命线：存储不可用（隐私模式/配额）时静默降级为空。
键：`wuxing.draft.v1:<wsId>`；空串即删除（不留空键）。
*/
const keyOf = (wsId: string): string => `wuxing.draft.v1:${wsId}`;

export function loadDraft(wsId: string): string {
  try {
    return localStorage.getItem(keyOf(wsId)) ?? "";
  } catch (err) {
    void err; // 存储不可用：视为无草稿
    return "";
  }
}

export function saveDraft(wsId: string, text: string): void {
  try {
    if (text.trim() === "") localStorage.removeItem(keyOf(wsId));
    else localStorage.setItem(keyOf(wsId), text);
  } catch (err) {
    void err; // 存储不可用：不阻断输入
  }
}
