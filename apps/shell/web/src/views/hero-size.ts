/** hero 输入框高度计算（Wave-2 T4 纯函数——隐藏态不量测）。
 *
 * Bug#4（真机复现）：hero 隐藏时 offsetHeight=0，autoGrow 把 textarea 压成
 * 0 高度——切回新建会话时占位符不可见。修复：隐藏态不写内联高度
 * （保持上次合法值）；可见时按 scrollHeight 计算（未布局回退 auto / 封顶）。
 */
export interface TextareaHeightInput {
  /** 可见态（host 可见 且 offsetParent 非空——隐藏态测量无效）。 */
  readonly visible: boolean;
  readonly scrollHeight: number;
  readonly max: number;
}

/** 返回内联高度（"NNpx"/"auto"）；null = 不改内联高度（隐藏态）。 */
export function computeTextareaHeight(input: TextareaHeightInput): string | null {
  if (!input.visible) return null;                 // 隐藏：不动内联高度（保持上次合法值）
  if (input.scrollHeight <= 0) return "auto";      // 未布局：回退自然高度
  return `${Math.min(input.scrollHeight, input.max)}px`;
}
