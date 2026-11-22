"""Demo reset helpers, used by .github/workflows/demo-reset.yml.

  python scripts/demo_reset.py close-issues   # Flow closes open 'CI failure: REQ-…' Jira Bugs in DDM
  python scripts/demo_reset.py verify         # read the latency requirement back from Flow

Needs FLOW_API_KEY / FLOW_CUSTOMER. Never prints secrets. Jira calls are made by Flow's own Jira
integration (automation "CI failure → Jira issue", reset mode), so no Jira credentials live in GitHub.
"""
from __future__ import annotations

import ast
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
import post_to_flow as p

LATENCY_REQ = p.LATMODEL_REQ


def summary(text: str) -> None:
    print(text)
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if path:
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(text + "\n")


def close_issues() -> int:
    res = p.trigger("ci-jira-sync", {"reset": True})
    out = (res[0].get("integration_response") or "") if res else ""
    result: dict = {}
    for line in out.splitlines():
        if line.startswith("RESULT="):
            result = ast.literal_eval(line[len("RESULT="):])
    if not result and res and res[0].get("status") != "completed":
        summary(f"- ⚠️ Jira reset did not run: {(res[0].get('error') or out)[:300]}")
        return 0  # keep going: main CI still resets Flow
    closed = result.get("closed", [])
    summary(f"- Jira: closed {len(closed)} old CI failure issue(s) as Done, labelled demo-reset "
            f"({', '.join(closed) or 'none open'})")
    return 0


def verify() -> int:
    branch = p.branch_id_by_name(p.MAIN_REVIEW_BRANCH)
    v = p.get_entity(p.IDS["requirements"][LATENCY_REQ]["id"], branch)["values"]
    status, actual, upper = v.get("verification"), p.num(v.get(p.ACTUAL)), p.num(v.get(p.UPPER))
    jira = v.get(p.REQ_JIRA) or []
    name = "Main" if branch == "master" else p.MAIN_REVIEW_BRANCH
    summary(f"- Flow starting branch **{name}** ({p.APP_URL}/{branch}/table): "
            f"{LATENCY_REQ} {v.get('name')} is **{status}**, {actual} ms vs ≤ {upper} ms; Jira: {', '.join(jira) or 'none'}")
    return 0 if status == "Fail" else 1


if __name__ == "__main__":
    sys.exit({"close-issues": close_issues, "verify": verify}[sys.argv[1]]())
