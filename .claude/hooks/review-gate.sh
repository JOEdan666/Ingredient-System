#!/bin/bash
# 审查叫停：当前分支最近一次独立验收不是 PASS 时，把结论塞进 AI 的上下文，逼它先处理审查意见。
# Claude Code 在会话开始和每次用户发言时运行它（.claude/settings.json）；Codex 按 AGENTS.md 手动运行。
export DEVELOPER_DIR=/Library/Developer/CommandLineTools
repo="$(git rev-parse --show-toplevel 2>/dev/null)" || exit 0
branch="$(git -C "$repo" rev-parse --abbrev-ref HEAD 2>/dev/null)" || exit 0
gate="$HOME/agent-archive/review-gate/Ingredient-System/${branch//\//__}.md"
[ -f "$gate" ] || exit 0
status="$(sed -n 's/^status: //p' "$gate" | head -1)"
[ "$status" = "PASS" ] && exit 0
echo "⛔ 审查叫停（分支 ${branch}，状态 ${status}）。在做任何新功能之前："
echo "1. 读完下面的审查意见；2. 在 docs/HANDOFF.md 写「审查叫停回应」，逐条写 接受并修 / 有异议+证据；"
echo "3. 修完后跑 scripts/run_acceptance_review.sh，拿到 PASS 才算解除。不许绕开、不许说完成。"
echo "----- 审查结论 ($gate) -----"
head -c 6000 "$gate"
