#!/bin/bash
# 独立验收：先用 Codex 跑 acceptance-reviewer；Codex 没给出结论（额度用完、报错、超时）就换 Claude Code 用同一份指令再跑。
# 审查指令只有一份：.codex/agents/acceptance-reviewer.toml 的 developer_instructions，两边共用。
# 用法: scripts/run_acceptance_review.sh            # 先 Codex，失败自动换 Claude
#       REVIEWER=claude scripts/run_acceptance_review.sh   # 直接用 Claude（测试兜底用）
#       REVIEWER=codex  scripts/run_acceptance_review.sh   # 只用 Codex，不兜底
# 结果: 报告写到 /private/tmp/ingredient-acceptance-report-<时间>.txt，最后一行打印 ACCEPTANCE_VERDICT。
# 退出码: 0=PASS 1=CHANGES_REQUESTED 2=COULD_NOT_VERIFY 3=两边都没给出结论
set -u
REPO="$(cd "$(dirname "$0")/.." && pwd)"
AGENT="$REPO/.codex/agents/acceptance-reviewer.toml"
STAMP="$(date +%Y%m%d-%H%M%S)"
OUT="/private/tmp/ingredient-acceptance-report-$STAMP.txt"
LOG="/private/tmp/ingredient-acceptance-log-$STAMP.txt"
MODE="${REVIEWER:-auto}"
TIMEOUT_S="${REVIEW_TIMEOUT_S:-2400}"
export DEVELOPER_DIR=/Library/Developer/CommandLineTools   # 绕过 Xcode 许可拦截

TASK='Independently review current HEAD of this repository against origin/main, following every gate in your instructions (first-time-user gate, words-versus-behavior gate, automated checks, UI gate with drive.mjs and shot.sh, approved real-file gate, stock non-mutation). Do not modify the repository, Desktop, source files, or user configuration. End with your full report; its first line must be the ACCEPTANCE_VERDICT line.'

has_verdict() { [ -s "$1" ] && grep -qE '^ACCEPTANCE_VERDICT: (PASS|CHANGES_REQUESTED|COULD_NOT_VERIFY)' "$1"; }

# 跑一个命令，超时就杀掉；caffeinate 防止合盖前熄屏打断
run_bounded() {
  "$@" &
  local pid=$!
  caffeinate -dims -w "$pid" >/dev/null 2>&1 &
  ( sleep "$TIMEOUT_S"; kill "$pid" 2>/dev/null ) &
  local killer=$!
  wait "$pid"; local rc=$?
  kill "$killer" 2>/dev/null
  return $rc
}

run_codex() {
  REVIEWED_BY=codex
  echo "== 审查者: Codex ($(date +%H:%M:%S))" | tee -a "$LOG"
  run_bounded codex exec --sandbox danger-full-access --enable multi_agent -C "$REPO" -o "$OUT" \
    "Use the custom acceptance-reviewer agent. Give it this task and return its report unchanged: $TASK" \
    < /dev/null >>"$LOG" 2>&1
  echo "codex 退出码 $?" >>"$LOG"
}

run_claude() {
  REVIEWED_BY=claude
  echo "== 审查者: Claude Code ($(date +%H:%M:%S))" | tee -a "$LOG"
  local instr
  instr="$(python3 -c 'import sys,tomllib;print(tomllib.load(open(sys.argv[1],"rb"))["developer_instructions"])' "$AGENT")" || return 1
  # 脚本里没有 shell 别名，代理要自己设；本机服务必须绕开代理
  ( cd "$REPO" && run_bounded env HTTP_PROXY=http://127.0.0.1:7897 HTTPS_PROXY=http://127.0.0.1:7897 \
      NO_PROXY="localhost,127.0.0.1,::1,*.local" \
      /opt/homebrew/bin/claude -p "$TASK" --model sonnet \
      --append-system-prompt "$instr" \
      --allowedTools "Bash" "Read" "Grep" "Glob" \
      --disallowedTools "Edit" "Write" "NotebookEdit" \
      < /dev/null >"$OUT" 2>>"$LOG" )
  echo "claude 退出码 $?" >>"$LOG"
}

# 开跑前先试一次无头浏览器：起不来（例如在 Codex 沙箱里跑）就直接停，不花 token 去得一个 COULD_NOT_VERIFY
probe="/private/tmp/ingredient-acceptance-probe-$STAMP.png"
if ! /Users/fangyuan/ai-hub/shared-skills/see-it-run/shot.sh "data:text/html,<p>probe</p>" "$probe" 400x200 >/dev/null 2>&1; then
  echo "ACCEPTANCE_VERDICT: NONE 无头 Chrome 在当前环境起不来（常见原因：在 Codex 沙箱里运行）。请在普通终端或 Claude Code 里运行本脚本。" | tee -a "$LOG"
  exit 3
fi
rm -f "$probe"

before="$(git -C "$REPO" rev-parse HEAD 2>/dev/null) $(git -C "$REPO" status --porcelain 2>/dev/null | shasum | cut -c1-12)"

case "$MODE" in
  claude) run_claude ;;
  codex)  run_codex ;;
  *)
    run_codex
    if ! has_verdict "$OUT"; then
      echo "Codex 没有给出结论（可能额度用完/报错/超时），改用 Claude Code。Codex 日志尾部：" | tee -a "$LOG"
      tail -5 "$LOG" | sed 's/^/  | /'
      run_claude
    fi ;;
esac

after="$(git -C "$REPO" rev-parse HEAD 2>/dev/null) $(git -C "$REPO" status --porcelain 2>/dev/null | shasum | cut -c1-12)"
[ "$before" = "$after" ] || echo "警告：审查期间仓库状态变了（$before → $after），结论作废，请重跑。" | tee -a "$LOG"

echo "报告: $OUT"
echo "日志: $LOG"
if ! has_verdict "$OUT"; then echo "ACCEPTANCE_VERDICT: NONE 两个审查者都没有给出结论，见日志"; exit 3; fi
[ "$before" = "$after" ] || exit 2
line="$(grep -m1 -E '^ACCEPTANCE_VERDICT:' "$OUT")"; echo "$line"
# 写「审查闸门」：不是 PASS 就是叫停状态，.claude/hooks/review-gate.sh 和 AGENTS.md 会让开发者先停下处理
branch="$(git -C "$REPO" rev-parse --abbrev-ref HEAD)"
gate_dir="$HOME/agent-archive/review-gate/Ingredient-System"; mkdir -p "$gate_dir"
gate="$gate_dir/${branch//\//__}.md"
status="$(echo "$line" | awk '{print $2}')"; [ "$status" = "PASS" ] || status="BLOCKED:$status"
{ echo "status: $status"; echo "branch: $branch"; echo "sha: $(git -C "$REPO" rev-parse HEAD)"
  echo "time: $(date '+%Y-%m-%d %H:%M')"; echo "reviewer: ${REVIEWED_BY}"; echo "reviewer_log: $LOG"; echo "report: $OUT"; echo; cat "$OUT"; } > "$gate"
cp "$gate" "$gate_dir/history-$STAMP-${branch//\//__}.md"
echo "闸门: $gate ($status)"
case "$line" in
  *": PASS "*) exit 0 ;;
  *CHANGES_REQUESTED*) exit 1 ;;
  *) exit 2 ;;
esac
