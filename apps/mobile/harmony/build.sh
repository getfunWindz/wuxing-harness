#!/usr/bin/env bash
# WUXING 鸿蒙壳构建辅助（Windows/git-bash）。
# 约束：hvigor 要求纯 ASCII 工程路径（subst 映射不生效）→ 镜像到 C:\tmp 构建，再回拷 HAP。
# 用法：./build.sh [hvigor 任务，默认 assembleHap]
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
MIRROR="${WUXING_HARMONY_MIRROR:-/c/tmp/wuxing-harmony-build}"
DEVECO="${WUXING_DEVECO:-/c/Program Files/Huawei/DevEco Studio}"
SDK="${WUXING_DEVECO_SDK:-$DEVECO/sdk}"
TASK="${1:-assembleHap}"
shift || true

rm -rf "$MIRROR"
mkdir -p "$MIRROR"
cp -r "$HERE"/. "$MIRROR"/
rm -rf "$MIRROR/.hvigor" "$MIRROR/oh_modules" "$MIRROR/entry/oh_modules" "$MIRROR/entry/build" "$MIRROR/build"
cd "$MIRROR"
"$DEVECO/tools/ohpm/bin/ohpm.bat" install >/dev/null
DEVECO_SDK_HOME="$SDK" "$DEVECO/tools/hvigor/bin/hvigorw.bat" \
  --no-daemon --mode module -p module=entry@default "$TASK" "$@"

mkdir -p "$HERE/entry/build/outputs"
if find entry/build -name '*.hap' | head -1 | grep -q .; then
  find entry/build -name '*.hap' -exec cp {} "$HERE/entry/build/outputs/" \;
  echo "[harmony] HAP 回拷：$HERE/entry/build/outputs/"
  ls -la "$HERE/entry/build/outputs/"
fi
