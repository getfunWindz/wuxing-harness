/** 单飞守卫（防重入）：同一异步流程进行中，再次调用被忽略（返回 null）。
 *
 * 场景（2026-09-30 黄金测试修复）：新建工作区走系统对话框，用户以为没反应
 * 会连击——旧实现每次点击都发起一次对话框请求（生产=多个系统对话框；
 * 取消多余对话框又触发手输回退弹窗 =「选择无效」体感）。
 * 完成后/失败后守卫释放（可重试）；同步抛错同样释放。
 */
export function createSingleFlight<T>(fn: () => Promise<T>): () => Promise<T> | null {
  let running = false;
  return () => {
    if (running) return null;
    running = true;
    let p: Promise<T>;
    try {
      p = fn();
    } catch (err) {
      running = false;
      return Promise.reject(err instanceof Error ? err : new Error(String(err)));
    }
    return p.finally(() => { running = false; });
  };
}
