#!/usr/bin/env python3
"""Send CI results to Flow and keep Jira in sync (through Flow's own Jira integration).

What happens on every GitHub Actions run:

1. Read JUnit XML (pytest), coverage.xml and bandit JSON and group the results by the
   Flow test case each test is tagged with (see conftest.py).
2. Jira: fire the Flow automation "CI failure → Jira issue" (webhook ci-jira-sync).
   A failing test case opens (or updates) the Bug "CI failure: REQ-… <requirement>" in Jira project
   DDM; a passing one renames it "✅ Fixed in …" and moves it to Done. Flow makes the Jira calls with
   its own Jira connection, so CI needs no Jira credentials.
3. Flow:
   * Pull request -> a Flow branch named "GitHub PR #<n> – <PR title>" is created (or reused)
     and a Test Result per test case plus requirement Actual Values are written on it, so the
     branch's Review tab shows exactly what this PR changed.
   * Push to main / manual run -> the Flow automation "Ingest CI test results" (webhook
     ci-test-results) records the results on its review branch.

Env: FLOW_API_KEY (secret), FLOW_CUSTOMER (e.g. "demo"), optional FLOW_API_BASE,
PR_NUMBER / PR_TITLE / PR_URL (set by the workflow on pull_request events),
GITHUB_TOKEN (pull requests: one sticky "Flow requirements check" comment, updated on re-runs),
and the GITHUB_* variables provided by GitHub Actions.
"""
from __future__ import annotations

import argparse
import ast
import datetime as dt
import json
import os
import sys
import urllib.request
import xml.etree.ElementTree as ET
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
IDS = json.loads((ROOT / "flow_ids.json").read_text())
PROJECT = IDS["project_id"]
APP_URL = IDS["project_url"]
API = os.environ.get("FLOW_API_BASE", "https://backend.branch.flowengineering.com")

COVERAGE_TC, COVERAGE_REQ, COVERAGE_MIN = "TES-45242", "REQ-45158", 80.0
STATIC_TC, STATIC_REQ = "TES-45245", "REQ-45159"
PUBLISH_TC, PUBLISH_REQ = "TES-45248", "REQ-45160"
SWEEP_TC, LATMODEL_REQ = "TES-45254", "REQ-45162"
MAIN_REVIEW_BRANCH = "Automation: Ingest CI test results"

# Flow field keys (Test Result / Requirement)
RESULT, MEASURED, TEST_DATE = "D5myzo6EgUPreacLcZew3", "measured", "testDate"
BASELINE, BUILD, RUN_LINK, JIRA = "softwareBaseline", "buildLot", "ciRunUrl", "jira_issue"
REQ_JIRA = "newJiraIssueField"  # Requirement field "Jira Ticket"
ACTUAL, UPPER, LOWER = "SZEURRJ3MXuRBeiw1jNnI", "value", "CasMf8leEE2hiAtnFnSLc"


# ----------------------------------------------------------------------------- results
def parse_junit(path: Path) -> dict:
    groups: dict = defaultdict(lambda: {"passed": 0, "failed": 0, "failures": [], "measured": [], "requirements": []})
    for case in ET.parse(path).getroot().iter("testcase"):
        props = {p.get("name"): p.get("value") for p in case.iter("property")}
        tc = props.get("flow_test_case")
        if not tc or case.find("skipped") is not None:
            continue
        g = groups[tc]
        if not g["requirements"] and props.get("flow_requirements"):
            g["requirements"] = props["flow_requirements"].split(",")
        if case.find("failure") is not None or case.find("error") is not None:
            g["failed"] += 1
            g["failures"].append(case.get("name"))
        else:
            g["passed"] += 1
        if props.get("flow_measured") not in (None, ""):
            g["measured"].append(float(props["flow_measured"]))
    return groups


def tc_entry(ref, outcome, measured=None, passed=0, failed=0, failures=None, requirements=None) -> dict:
    return {"id": IDS["test_cases"][ref]["id"], "ref": ref, "outcome": outcome, "measured": measured,
            "passed": passed, "failed": failed, "failures": failures or [], "requirements": requirements or []}


def req_entry(ref: str, value) -> dict:
    return {"id": IDS["requirements"][ref]["id"], "ref": ref, "value": value}


def build_payload(junit: Path, coverage: Path | None, bandit: Path | None, started: str | None) -> dict:
    test_cases, req_values = [], []
    for ref, g in sorted(parse_junit(junit).items()):
        if ref not in IDS["test_cases"]:
            continue
        measured = max(g["measured"]) if g["measured"] else None
        test_cases.append(tc_entry(ref, "fail" if g["failed"] else "pass", measured, g["passed"], g["failed"],
                                   g["failures"], g["requirements"]))
        if ref == SWEEP_TC and measured is not None:
            req_values.append(req_entry(LATMODEL_REQ, measured))  # worst planned-config budget, ms
    if coverage and coverage.exists():
        pct = round(float(ET.parse(coverage).getroot().get("line-rate")) * 100, 1)
        test_cases.append(tc_entry(COVERAGE_TC, "pass" if pct >= COVERAGE_MIN else "fail", pct,
                                   requirements=[COVERAGE_REQ], failures=[] if pct >= COVERAGE_MIN else [f"coverage {pct}% < 80%"]))
        req_values.append(req_entry(COVERAGE_REQ, pct))
    if bandit and bandit.exists():
        results = json.loads(bandit.read_text()).get("results", [])
        high = sum(1 for r in results if r.get("issue_severity") == "HIGH")
        test_cases.append(tc_entry(STATIC_TC, "pass" if high == 0 else "fail", high, requirements=[STATIC_REQ],
                                   failures=[f"{high} high-severity bandit findings"] if high else []))
        req_values.append(req_entry(STATIC_REQ, high))
    if started:
        start = dt.datetime.fromisoformat(started.replace("Z", "+00:00"))
        minutes = round((dt.datetime.now(dt.timezone.utc) - start).total_seconds() / 60, 1)
        test_cases.append(tc_entry(PUBLISH_TC, "pass" if minutes <= 30 else "fail", minutes, requirements=[PUBLISH_REQ]))
        req_values.append(req_entry(PUBLISH_REQ, minutes))
    server = os.environ.get("GITHUB_SERVER_URL", "https://github.com")
    repo = os.environ.get("GITHUB_REPOSITORY", "adamkelleyflowengineering/dominion-flow-jira-demo")
    run_id = os.environ.get("GITHUB_RUN_ID")
    pr = os.environ.get("PR_NUMBER") or None
    return {
        "commit": os.environ.get("PR_HEAD_SHA") or os.environ.get("GITHUB_SHA", "local"),
        "branch": os.environ.get("GITHUB_HEAD_REF") or os.environ.get("GITHUB_REF_NAME", "local"),
        "run_number": os.environ.get("GITHUB_RUN_NUMBER", "local"),
        "run_url": f"{server}/{repo}/actions/runs/{run_id}" if run_id else "local run",
        "date": dt.datetime.now(dt.timezone.utc).date().isoformat(),
        "pr": {"number": int(pr), "title": os.environ.get("PR_TITLE", ""), "url": os.environ.get("PR_URL", "")} if pr else None,
        "test_cases": test_cases,
        "requirement_values": req_values,
    }


# ----------------------------------------------------------------------------- Flow API
def flow(method: str, path: str, body=None, timeout=120):
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(API + path, data=data, method=method, headers={
        "X-API-Key": os.environ["FLOW_API_KEY"], "customer": os.environ.get("FLOW_CUSTOMER", "demo"),
        "Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=timeout) as resp:  # nosec B310 - fixed https endpoint
        raw = resp.read()
        return json.loads(raw) if raw else {}


def trigger(source: str, context: dict) -> list:
    return flow("POST", "/ai/trigger", {"project_id": PROJECT, "source": source, "context": context, "wait": True},
                timeout=300).get("results", [])


def list_branches() -> list:
    res = flow("GET", f"/project/{PROJECT}/branch")
    return res if isinstance(res, list) else res.get("items", res.get("branches", []))


def ensure_pr_branch(pr: dict) -> tuple[str, str]:
    prefix = f"GitHub PR #{pr['number']} "
    for b in list_branches():
        if isinstance(b, dict) and str(b.get("name", "")).startswith(prefix):
            return b["id"], b["name"]
    name = (prefix + "– " + (pr["title"] or "")).strip()[:100]
    created = flow("POST", f"/project/{PROJECT}/branch", {
        "name": name, "parent_id": "master",
        "description": f"CI results from GitHub pull request #{pr['number']}: {pr['url']}\n"
                       "Created automatically by the dominion-flow-jira-demo workflow."})
    return created["id"], name


def branch_id_by_name(name: str) -> str:
    for b in list_branches():
        if isinstance(b, dict) and b.get("name") == name:
            return b["id"]
    return "master"


def item_link(branch_id: str, entity_id: str) -> str:
    return f"{APP_URL}/{branch_id}/table?focusedId={entity_id}&detailsId={entity_id}"


def get_entity(entity_id: str, branch_id: str) -> dict:
    e = flow("GET", f"/project/{PROJECT}/entities/{entity_id}?branch_id={branch_id}")
    return e[0] if isinstance(e, list) else e


def num(v):
    return v.get("value") if isinstance(v, dict) else v


# ----------------------------------------------------------------------------- Jira (via Flow)
def jira_sync(payload: dict, label: str, branch_id: str) -> dict:
    failing, passing = [], []
    for tc in payload["test_cases"]:
        reqs = [r for r in tc.get("requirements", []) if r in IDS["requirements"]]
        if not reqs:
            continue
        req = get_entity(IDS["requirements"][reqs[0]]["id"], branch_id)
        tce = get_entity(tc["id"], branch_id)
        title = f"CI failure: {reqs[0]} {req['values'].get('name')} ({tc['ref']})"
        item = {"key": tc["ref"], "title": title, "req_ref": reqs[0], "req_name": req["values"].get("name"),
                "tc_ref": tc["ref"], "tc_name": tce["values"].get("name"), "measured": tc["measured"],
                "flow_link": item_link(branch_id, req["id"])}
        if tc["outcome"] == "fail":
            lim = num(req["values"].get(UPPER))
            lo = num(req["values"].get(LOWER))
            item["limit"] = f"≤ {lim}" if lim is not None else (f"≥ {lo}" if lo is not None else "see requirement")
            item["failures"] = tc["failures"]
            failing.append(item)
        else:
            passing.append(item)
    if not failing and not passing:
        return {}
    pr = payload.get("pr") or {}
    results = trigger("ci-jira-sync", {"label": label, "run_url": payload["run_url"], "commit": payload["commit"],
                                       "pr_url": pr.get("url", ""), "failing": failing, "passing": passing})
    for r in results:
        text = r.get("integration_response") or ""
        if "RESULT=" in text:
            return ast.literal_eval(text.split("RESULT=", 1)[1].split("\n", 1)[0].strip())
    for r in results:
        print("Jira sync (Flow automation 'CI failure → Jira issue') did not return issues:",
              (r.get("error") or r.get("integration_response") or "")[:300])
    return {}


def requirement_links(payload: dict, tickets: dict) -> list:
    """The CI failure Jira issue of each failing/fixed test case, for its first requirement's Jira Ticket field."""
    out = []
    for t in payload["test_cases"]:
        reqs = [r for r in t.get("requirements", []) if r in IDS["requirements"]]
        if t["ref"] in tickets and reqs:
            out.append({"id": IDS["requirements"][reqs[0]]["id"], "ref": reqs[0], "url": tickets[t["ref"]]["url"]})
    return out


# ----------------------------------------------------------------------------- writes
def write_pr_branch(branch_id: str, payload: dict, tickets: dict) -> int:
    sha = str(payload["commit"])[:7]
    pr = payload["pr"]
    tcs = [t for t in payload["test_cases"]]
    created = flow("POST", f"/project/{PROJECT}/entities/batch", {"branchId": branch_id, "entities": [
        {"entityType": "testRun", "name": f"{get_entity(t['id'], branch_id)['values'].get('name')} – PR #{pr['number']} @ {sha}"}
        for t in tcs]})
    flow("POST", f"/project/{PROJECT}/entities/links/batch", {"branchId": branch_id, "links": [
        {"sourceId": t["id"], "destinationId": c["id"]} for t, c in zip(tcs, created)]})
    updates = []
    for t, c in zip(tcs, created):
        paras = [f"Automated CI result from GitHub Actions: {t['passed']} passed, {t['failed']} failed.",
                 f"Pull request #{pr['number']}: {pr['title']} – {pr['url']}",
                 f"Workflow run: {payload['run_url']}", f"Commit: {payload['commit']} on {payload['branch']}"]
        if t["failures"]:
            paras.append("Failing tests: " + "; ".join(t["failures"][:20]))
        vals = {RESULT: "Pass" if t["outcome"] == "pass" else "Fail", TEST_DATE: payload["date"],
                BASELINE: f"dominion-flow-jira-demo@{sha}", BUILD: f"GitHub Actions run {payload['run_number']} (PR #{pr['number']})",
                RUN_LINK: payload["run_url"],
                "description": [{"type": "p", "children": [{"text": p}]} for p in paras]}
        if t["measured"] is not None:
            vals[MEASURED] = t["measured"]
        if t["ref"] in tickets:
            vals[JIRA] = [tickets[t["ref"]]["url"]]
        updates += [{"entityId": c["id"], "key": k, "value": v} for k, v in vals.items()]
    updates += [{"entityId": r["id"], "key": ACTUAL, "value": r["value"]} for r in payload["requirement_values"]]
    updates += [{"entityId": r["id"], "key": REQ_JIRA, "value": [r["url"]]} for r in requirement_links(payload, tickets)]
    flow("PUT", f"/project/{PROJECT}/entities/values/batch", {"branchId": branch_id, "updates": updates})
    return len(created)


# ----------------------------------------------------------------------------- PR comment
COMMENT_MARKER = "<!-- flow-requirements-check -->"
STATUS_ICON = {"Pass": "✅ Pass", "Fail": "❌ Fail", "Inconclusive": "⚪ Inconclusive"}


def affected_requirements(payload: dict) -> list:
    refs: list = []
    for t in payload["test_cases"]:
        refs += [r for r in t.get("requirements", []) if r in IDS["requirements"]]
    refs += [r["ref"] for r in payload["requirement_values"]]
    return list(dict.fromkeys(refs))


def tests_per_requirement(payload: dict) -> dict:
    counts: dict = defaultdict(int)
    for t in payload["test_cases"]:
        for r in t.get("requirements", []):
            counts[r] += t["passed"] + t["failed"] or 1
    return counts


def fmt(v) -> str:
    return f"{v:g}" if isinstance(v, (int, float)) else str(v)


def requirement_rows(payload: dict, branch_id: str) -> list:
    """Read each affected requirement back from Flow on the branch (Verification is Flow's own formula)."""
    import time
    written = {r["ref"]: r["value"] for r in payload["requirement_values"]}
    refs = affected_requirements(payload)
    rows = []
    for attempt in range(6):
        time.sleep(3)
        rows = []
        for ref in refs:
            v = get_entity(IDS["requirements"][ref]["id"], branch_id)["values"]
            rows.append({"ref": ref, "name": v.get("name"), "status": v.get("verification") or "Inconclusive",
                         "actual": num(v.get(ACTUAL)), "upper": num(v.get(UPPER)), "lower": num(v.get(LOWER)),
                         "unit": v.get("unit") or ""})
        if all(r["actual"] == written[r["ref"]] for r in rows if r["ref"] in written):
            break
    return rows


def build_comment(payload: dict, rows: list | None, branch_name: str, branch_url: str, tickets: dict,
                  error: str | None) -> str:
    pr = payload["pr"]
    sha = str(payload["commit"])[:7]
    out = [COMMENT_MARKER, "## Flow requirements check", ""]
    if error or rows is None:
        failed_tcs = [t["ref"] for t in payload["test_cases"] if t["outcome"] == "fail"]
        out += ["⚠️ **Flow did not record this run**, so requirement status was **not** verified in Flow.",
                f"Error: `{error}`", "",
                (f"Local test outcome only (not from Flow): {len(failed_tcs)} of {len(payload['test_cases'])} "
                f"Flow test cases failed{': ' + ', '.join(failed_tcs) if failed_tcs else ''}."),
                "", f"Re-run this check once Flow is reachable. [GitHub run]({payload['run_url']})"]
        return "\n".join(out)
    counts = tests_per_requirement(payload)
    failing = [r for r in rows if r["status"] == "Fail"]
    pending = [r for r in rows if r["status"] not in ("Pass", "Fail")]
    if failing:
        verdict = f"❌ **{len(failing)} requirement{'s' if len(failing) != 1 else ''} failing** of {len(rows)} linked to this PR"
    elif pending:
        verdict = (f"✅ **No requirement failing** – {len(rows) - len(pending)} pass, {len(pending)} still need "
                   "other evidence (e.g. hardware tests)")
    else:
        verdict = f"✅ **All {len(rows)} linked requirements pass**"
    out += [verdict, "",
            "| Flow ID | Requirement | Status | Measured vs limit | Tests |",
            "| -- | -- | -- | -- | --: |"]
    order = {"Fail": 0, "Inconclusive": 1, "Pass": 2}
    for r in sorted(rows, key=lambda r: (order.get(r["status"], 1), r["ref"])):
        unit = f" {r['unit']}" if r["unit"] and r["unit"] not in ("count",) else ""
        if r["actual"] is not None and r["upper"] is not None:
            mv = f"{fmt(r['actual'])}{unit} vs ≤ {fmt(r['upper'])}{unit}"
        elif r["actual"] is not None and r["lower"] is not None:
            mv = f"{fmt(r['actual'])}{unit} vs ≥ {fmt(r['lower'])}{unit}"
        elif r["actual"] is not None:
            mv = f"{fmt(r['actual'])}{unit}"
        else:
            mv = "–"
        out.append(f"| {r['ref']} | {r['name']} | {STATUS_ICON.get(r['status'], r['status'])} | {mv} | {counts.get(r['ref'], '–')} |")
    out += ["", f"**Flow branch:** [{branch_name}]({branch_url}) – open the **Review** tab to see every item this PR changed.",
            f"Project: {APP_URL}/"]
    if tickets:
        out += ["**Jira:** " + ", ".join(
            f"[{v['identifier']}]({v['url']}) {v['action']}" for v in tickets.values())]
    out += ["", (f"<sub>Status is read back from Flow's own Verification on this branch · commit `{sha}` · "
                f"[GitHub run]({payload['run_url']}) · PR #{pr['number']}</sub>")]
    return "\n".join(out)


def upsert_pr_comment(pr_number: int, body: str) -> str:
    token = os.environ.get("GITHUB_TOKEN")
    repo = os.environ.get("GITHUB_REPOSITORY")
    if not token or not repo:
        print("No GITHUB_TOKEN/GITHUB_REPOSITORY: PR comment skipped")
        return "skipped"
    api = os.environ.get("GITHUB_API_URL", "https://api.github.com")

    def gh(method, path, data=None):
        request = urllib.request.Request(api + path, method=method,
                                         data=json.dumps(data).encode() if data is not None else None,
                                         headers={"Authorization": f"Bearer {token}",
                                                  "Accept": "application/vnd.github+json",
                                                  "X-GitHub-Api-Version": "2022-11-28"})
        with urllib.request.urlopen(request, timeout=30) as resp:  # nosec B310 - fixed https endpoint
            raw = resp.read()
            return json.loads(raw) if raw else {}

    page = 1
    while True:
        comments = gh("GET", f"/repos/{repo}/issues/{pr_number}/comments?per_page=100&page={page}")
        for c in comments:
            if COMMENT_MARKER in (c.get("body") or ""):
                gh("PATCH", f"/repos/{repo}/issues/comments/{c['id']}", {"body": body})
                return f"updated {c.get('html_url')}"
        if len(comments) < 100:
            break
        page += 1
    c = gh("POST", f"/repos/{repo}/issues/{pr_number}/comments", {"body": body})
    return f"created {c.get('html_url')}"


def summary(lines: list) -> None:
    text = "\n".join(lines)
    print(text)
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if path:
        with open(path, "a") as fh:
            fh.write(text + "\n")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--junit", default="reports/junit.xml", type=Path)
    ap.add_argument("--coverage", default="reports/coverage.xml", type=Path)
    ap.add_argument("--bandit", default="reports/bandit.json", type=Path)
    ap.add_argument("--started", default=os.environ.get("WORKFLOW_STARTED_AT"))
    ap.add_argument("--no-jira", action="store_true", help="skip the Jira sync")
    ap.add_argument("--dry-run", action="store_true", help="print the payload, do not post")
    args = ap.parse_args()
    payload = build_payload(args.junit, args.coverage, args.bandit, args.started)
    if args.dry_run:
        print(json.dumps(payload, indent=2))
        return 0
    pr = payload["pr"]
    branch_name, branch_id, tickets, how, error = MAIN_REVIEW_BRANCH, "master", {}, "", None
    try:
        if pr:
            branch_id, branch_name = ensure_pr_branch(pr)
            label = f"PR #{pr['number']}"
        else:
            branch_id = branch_id_by_name(MAIN_REVIEW_BRANCH)
            label = str(payload["branch"])
        tickets = {} if args.no_jira else jira_sync(payload, label, branch_id)
        if pr:
            n = write_pr_branch(branch_id, payload, tickets)
            how = f"wrote {n} test results + {len(payload['requirement_values'])} requirement values directly"
        else:
            for t in payload["test_cases"]:
                if t["ref"] in tickets:
                    t["jira_issue"] = tickets[t["ref"]]["url"]
            res = trigger("ci-test-results", dict(payload, requirement_links=requirement_links(payload, tickets)))
            out = (res[0].get("integration_response") or "") if res else ""
            how = "; ".join(ln.strip() for ln in out.splitlines() if ln.startswith(("Test results created", "Requirement values")))
            how = how or "Flow automation 'Ingest CI test results' did not report results"
            branch_id = branch_id_by_name(MAIN_REVIEW_BRANCH)
    except Exception as exc:  # noqa: BLE001 - report the failure instead of claiming a pass
        error = f"{type(exc).__name__}: {str(exc)[:200]}"
        how = f"FAILED to record results in Flow ({error})"
    branch_url = f"{APP_URL}/{branch_id}/table"
    if pr:
        rows = None
        if not error:
            try:
                rows = requirement_rows(payload, branch_id)
            except Exception as exc:  # noqa: BLE001
                error = f"could not read requirement status back from Flow: {type(exc).__name__}"
        try:
            print("PR comment:", upsert_pr_comment(pr["number"], build_comment(payload, rows, branch_name, branch_url,
                                                                               tickets, error)))
        except Exception as exc:  # noqa: BLE001
            print(f"PR comment failed: {type(exc).__name__}: {str(exc)[:200]}")
    lines = ["## Flow", f"- Flow branch: **{branch_name}** – {branch_url}", f"- {how}", "", "## Test cases"]
    lines += [f"- {'✅' if t['outcome'] == 'pass' else '❌'} {t['ref']} {t['outcome'].upper()}"
              + (f" (measured {t['measured']})" if t["measured"] is not None else "") for t in payload["test_cases"]]
    if tickets:
        lines += ["", "## Jira"]
        lines += [f"- {k}: {v['identifier']} {v['action']} – {v['url']}" for k, v in tickets.items()]
    summary(lines)
    return 1 if error else 0

if __name__ == "__main__":
    sys.exit(main())
