/** 运行模式 = 模块配置表（不是代码分支）。 */

export interface RunPreset {
  readonly id: string;
  readonly modules: readonly string[];
}

export function definePreset(preset: RunPreset): RunPreset {
  return preset;
}

export function resolvePreset(presets: readonly RunPreset[], id: string): RunPreset {
  const preset = presets.find((item) => item.id === id);
  if (!preset) {
    throw new Error(`未知运行模式：${id}`);
  }
  return preset;
}
