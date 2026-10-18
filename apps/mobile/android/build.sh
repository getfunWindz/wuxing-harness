#!/usr/bin/env bash
# WUXING Android 本地构建辅助（Windows/git-bash）。
# 用法：./build.sh [gradle 任务，默认 :app:assembleDebug]
# 说明：
#  - JDK 必须是含 jlink 的完整 JDK 17+（DevEco JBR 为精简版，无 jlink，不能编译 API>=31）
#  - 仓库路径含非 ASCII（"Pi 工作区"）→ 经 X: 盘符映射（subst）从 ASCII 路径构建
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$HERE/../../.." && pwd)"
: "${WUXING_JDK:=/c/tmp/jdk/jdk-17.0.20.1+1}"
export JAVA_HOME="$WUXING_JDK"
if [ ! -d /x/apps/mobile/android ]; then
  subst X: "$(cygpath -w "$REPO")"
fi
cd /x/apps/mobile/android
TASK="${1:-:app:assembleDebug}"
shift || true
./gradlew --no-daemon "$TASK" "$@"
