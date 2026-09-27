"""Validate planning metadata and local links, not the warehouse application."""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
errors = []


def check(condition, message):
    if not condition:
        errors.append(message)


def read_json(path):
    try:
        return json.loads((ROOT / path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        errors.append(f"{path}: {exc}")
        return {}


tasks = read_json("docs/tasks.json").get("tasks", [])
cases = read_json("docs/acceptance.json").get("cases", [])
check(bool(tasks), "Task list is empty")
check(bool(cases), "Acceptance list is empty")
task_map = {t["id"]: t for t in tasks}
case_map = {c["id"]: c for c in cases}
check(len(task_map) == len(tasks), "Duplicate task IDs")
check(len(case_map) == len(cases), "Duplicate acceptance IDs")
questions = set(re.findall(r"\bQ\d{2}\b", (ROOT / "PROJECT.md").read_text(encoding="utf-8")))

for task in tasks:
    key = task["id"]
    status = task.get("status")
    check(status in {"queued", "ready", "in_progress", "review", "done", "blocked"}, f"{key}: invalid status")
    check(bool(task.get("scope")) and bool(task.get("deliverable")), f"{key}: missing scope/deliverable")
    check(bool(task.get("acceptance")), f"{key}: missing acceptance")
    for case in task.get("acceptance", []):
        check(case in case_map, f"{key}: unknown case {case}")
    for dep in task.get("depends_on", []):
        check(dep in task_map and dep != key, f"{key}: invalid dependency {dep}")
        if status in {"ready", "in_progress", "review", "done"} and dep in task_map:
            check(task_map[dep]["status"] == "done", f"{key}: dependency {dep} not done")
    for question in task.get("blocked_by", []):
        check(question in questions, f"{key}: unknown blocker {question}")
    if status in {"ready", "in_progress", "review", "done"}:
        check(not task.get("blocked_by"), f"{key}: unresolved blocker")
    if status in {"in_progress", "review", "done"}:
        check(bool(task.get("owner")), f"{key}: missing owner")
    if status in {"review", "done"}:
        check(bool(task.get("evidence")), f"{key}: missing evidence")


def visit(key, stack, seen):
    if key in stack:
        errors.append(f"Dependency cycle: {' -> '.join(stack + [key])}")
        return
    if key in seen or key not in task_map:
        return
    for dep in task_map[key].get("depends_on", []):
        visit(dep, stack + [key], seen)
    seen.add(key)


seen = set()
for key in task_map:
    visit(key, [], seen)

for case in cases:
    check(case.get("status") in {"not_run", "failed", "passed", "blocked"}, f"{case['id']}: invalid result")
    check(bool(case.get("scenario")), f"{case['id']}: missing scenario")
    if case.get("status") == "passed":
        check(bool(case.get("evidence")), f"{case['id']}: passed without evidence")

fixture = read_json("fixtures/synthetic/stock.json")
check(fixture.get("synthetic") is True, "Fixture must be marked synthetic")
for row in fixture.get("stock", []):
    check(isinstance(row.get("sku"), str), "Fixture SKU must remain text")
    check(isinstance(row.get("quantity"), (int, float)) and row["quantity"] >= 0, "Invalid fixture quantity")

for path in ROOT.rglob("*.md"):
    if any(part in {".git", "node_modules", "private-data", "customer-data"} for part in path.parts):
        continue
    for target in re.findall(r"\]\(([^)]+)\)", path.read_text(encoding="utf-8")):
        if "://" in target or target.startswith(("#", "mailto:")):
            continue
        check((path.parent / target.split("#")[0]).exists(), f"{path.relative_to(ROOT)}: missing link {target}")

check("@AGENTS.md" in (ROOT / "CLAUDE.md").read_text(encoding="utf-8"), "CLAUDE.md must reference shared rules")
if errors:
    raise SystemExit("\n".join(errors))
print(f"PASS: {len(tasks)} tasks, {len(cases)} acceptance definitions, synthetic fixture and local links")
print("Application, database, installer and printing tests have NOT been run by this check.")
