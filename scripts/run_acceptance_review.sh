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
kill_tree() {  # 先杀子孙再杀自己：审查者起的 Chrome、测试服务器不能在超时后残留
  # 已知局限（Codex 2026-09-30 指出）：子进程若自己脱离父进程（setsid/双 fork）就找不到，可能残留
  local p
  for p in $(pgrep -P "$1"); do kill_tree "$p"; done
  kill "$1" 2>/dev/null
}

run_bounded() {
  "$@" &
  local pid=$!
  caffeinate -dims -w "$pid" >/dev/null 2>&1 &
  ( sleep "$TIMEOUT_S"; echo "超时 ${TIMEOUT_S}s，结束审查进程及其子进程" >>"$LOG"; kill_tree "$pid" ) &
  local killer=$!
  wait "$pid"; local rc=$?
  kill_tree "$killer"
  return $rc
}

run_codex() {
  REVIEWED_BY=codex
  echo "== 审查者: Codex ($(date +%H:%M:%S))" | tee -a "$LOG"
  run_bounded codex exec --sandbox danger-full-access --enable multi_agent -C "$REVIEW_DIR" -o "$OUT" \
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
  ( cd "$REVIEW_DIR" && run_bounded env HTTP_PROXY=http://127.0.0.1:7897 HTTPS_PROXY=http://127.0.0.1:7897 \
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
branch="$(git -C "$REPO" rev-parse --abbrev-ref HEAD)"
head_sha="$(git -C "$REPO" rev-parse HEAD)"

# 审查者在一次性副本里跑：它有完全权限（无头 Chrome 需要），指令里的「不许改」只是请求，
# 副本保证它就算改了也碰不到真仓库；跑完删掉副本。
WORK="/private/tmp/ingredient-review-$STAMP"
git clone -q --no-hardlinks "$REPO" "$WORK" || { echo "ACCEPTANCE_VERDICT: NONE 建审查副本失败" | tee -a "$LOG"; exit 3; }
git -C "$WORK" fetch -q "$REPO" "+refs/remotes/origin/*:refs/remotes/origin/*" 2>/dev/null
git -C "$WORK" checkout -q -B "$branch" "$head_sha"
[ -e "$REPO/prototype/.venv" ] && ln -s "$(cd "$REPO/prototype/.venv" && pwd -P)" "$WORK/prototype/.venv"
REVIEW_DIR="$WORK"
trap 'rm -rf "$WORK"' EXIT

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

# 报告里出现真实文件名（含客户名、单号）一律替换掉，再保存/抄进闸门
python3 - "$OUT" "$HOME/agent-archive/ingredient-approved-files.txt" <<'PY'
import os, sys
out, lst = sys.argv[1], sys.argv[2]
if os.path.exists(out) and os.path.exists(lst):
    text = open(out, encoding="utf-8", errors="replace").read()
    for n, path in enumerate(l.strip() for l in open(lst, encoding="utf-8") if l.strip()):
        name = os.path.basename(path)
        for token in sorted({path, name, os.path.splitext(name)[0]}, key=len, reverse=True):
            text = text.replace(token, f"[真实文件{n + 1}]")
    open(out, "w", encoding="utf-8").write(text)
PY

after="$(git -C "$REPO" rev-parse HEAD 2>/dev/null) $(git -C "$REPO" status --porcelain 2>/dev/null | shasum | cut -c1-12)"
echo "报告: $OUT"
echo "日志: $LOG"
if ! has_verdict "$OUT"; then echo "ACCEPTANCE_VERDICT: NONE 两个审查者都没有给出结论，见日志"; exit 3; fi
line="$(grep -m1 -E '^ACCEPTANCE_VERDICT:' "$OUT")"; echo "$line"

# 先算出结论，闸门和退出码都只看它
case "$(echo "$line" | awk '{print $2}')" in
  PASS) status="PASS" ;;
  CHANGES_REQUESTED) status="BLOCKED:CHANGES_REQUESTED" ;;
  *) status="BLOCKED:COULD_NOT_VERIFY" ;;
esac
reported="$(echo "$line" | awk '{print $3}')"
if [ "$status" = "PASS" ] && [ "$reported" != "$head_sha" ]; then  # 结论必须写明就是这个版本
  status="BLOCKED:SHA_MISMATCH"; echo "警告：审查者报告的版本 $reported 不是当前 HEAD $head_sha，不记为通过。" | tee -a "$LOG"
fi
if [ "$before" != "$after" ]; then
  status="BLOCKED:REPO_CHANGED"; echo "警告：审查期间仓库状态变了（$before → $after），结论作废，请重跑。" | tee -a "$LOG"
fi

if [ "$branch" = "HEAD" ]; then  # 游离检出没有分支，不写闸门，免得生成 HEAD.md 这种无主记录
  echo "当前是游离检出，结论只写在报告里，不写闸门。"
else
  # 写「审查闸门」：不是 PASS 就是叫停，.claude/hooks/review-gate.sh 和 AGENTS.md 会让开发者先停下处理
  gate_dir="$HOME/agent-archive/review-gate/Ingredient-System"; mkdir -p "$gate_dir"
  gate="$gate_dir/${branch//\//__}.md"
  { echo "status: $status"; echo "branch: $branch"; echo "sha: $head_sha"
    echo "time: $(date '+%Y-%m-%d %H:%M')"; echo "reviewer: ${REVIEWED_BY}"; echo "reviewer_log: $LOG"; echo "report: $OUT"; echo; cat "$OUT"; } > "$gate"
  cp "$gate" "$gate_dir/history-$STAMP-${branch//\//__}.md"
  echo "闸门: $gate ($status)"
fi
case "$status" in
  PASS) exit 0 ;;
  BLOCKED:CHANGES_REQUESTED) exit 1 ;;
  *) exit 2 ;;
esac
