#!/bin/bash
# Runs every prompt in evals/prompts.txt through Claude Code headless on a cheap model, in an isolated
# workspace where only this skill is installed. Transcripts land in $OUT; grade them with evals/checks.md.
# usage: evals/run.sh [model] [out-dir]
set -euo pipefail
SKILL=$(cd "$(dirname "$0")/.." && pwd)
MODEL=${1:-claude-haiku-4-5-20251001}
OUT=${2:-$(mktemp -d)}
cd "$OUT"
i=0
while IFS= read -r prompt; do
  [ -z "$prompt" ] && continue
  i=$((i + 1))
  # Each case gets its own workspace, so parallel runs cannot read or overwrite each other's reports.
  mkdir -p "case$i/.claude/skills"
  ln -sfn "$SKILL" "case$i/.claude/skills/wiki-interest-research"
  (cd "case$i" && claude -p "$prompt" --model "$MODEL" --setting-sources project \
    --allowedTools "Bash Read Skill Glob" --output-format stream-json --verbose \
    < /dev/null > "../case$i.jsonl" 2> "../case$i.err") &  # claude -p also reads stdin
done < "$SKILL/evals/prompts.txt"
wait
for f in case*.jsonl; do
  python3 - "$f" <<'PY'
import json, sys
tools = []
for line in open(sys.argv[1]):
    d = json.loads(line)
    if d.get("type") == "assistant":
        tools += [c["input"].get("command", c["name"])[:160] for c in d["message"]["content"] if c["type"] == "tool_use"]
    if d.get("type") == "result":
        print(f"===== {sys.argv[1]}  turns={d['num_turns']}  cost=${d.get('total_cost_usd', 0):.3f}")
        print("\n".join("  $ " + t for t in tools))
        print(d.get("result", ""))
PY
done
echo "Transcripts and reports: $OUT"
