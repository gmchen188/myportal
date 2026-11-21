#!/usr/bin/env bash
# 提交前的完整验证链 —— 与 CI 的 job 一一对应。
#
# **为什么要有这个脚本**
#
# 我提交过一次「本地 tsc exit 0、16 passed」的版本，CI 却是红的：
#   src/test/siem-cache.test.tsx(6,1): error TS6133: 'api' is declared but its value is never read.
#
# 原因是我跑 tsc 的时机在**写那个测试文件之前** —— 之后改了代码
# 却没有重跑完整的验证链。「本地绿」不等于「我改完之后绿」。
#
# CI 的 Web frontend job 有 4 个实质步骤：Type check / Unit tests /
# Build / Upload dist。**本地必须跑完等价物**才能说「本地绿」。
#
# 用法：bash scripts/verify.sh
set -uo pipefail

NODEDIR="C:/Users/gmche/AppData/Local/hermes/tools/node-26.12.1-win32-x64"
NODE="$NODEDIR/node.exe"
PY="C:/Python314/python.exe"
ROOT="C:/Users/gmche/Work/myPortal"
WEB="$ROOT/web"
BACK="$ROOT/backend"

FAILED=0

run_in() {
  # run_in <目录> <说明> <命令...>
  # 每步都必须在**正确的目录**里跑 —— vite build 找不到 index.html
  # 就是因为 cwd 不对（它按 cwd 找入口）。
  local dir="$1"; local name="$2"; shift 2
  echo ""
  echo "════ $name ════"
  if ( cd "$dir" && "$@" ); then
    echo "  ✓ $name"
  else
    echo "  ✗ $name"
    FAILED=1
  fi
}

# ── 后端：对应 CI 的 "Backend tests" ──────────────────────
run_in "$BACK" "Backend tests (pytest)" \
  "$PY" -m pytest tests -q

# ── 前端：对应 CI 的 "Web frontend" 的 4 步 ────────────────
run_in "$WEB" "Type check (tsc --noEmit)" \
  "$NODE" node_modules/typescript/bin/tsc --noEmit

run_in "$WEB" "Unit tests (vitest)" \
  "$NODE" node_modules/vitest/vitest.mjs run

# CI 构建时传 VITE_BASE（Pages 项目站点在 /<repo>/ 下）
run_in "$WEB" "Build (vite)" \
  env VITE_BASE=/myportal/ "$NODE" node_modules/vite/bin/vite.js build

echo ""
if [ "$FAILED" -eq 0 ]; then
  echo "════ 全部通过 ════"
else
  echo "════ 有失败项 —— 不要提交 ════"
fi
exit "$FAILED"
