# dominion-flow-jira-demo

Demo repository for the **Dominion Dynamics × Flow Engineering** trial workshop.
It shows software verification evidence flowing automatically from CI into Flow,
traced to requirements in the Flow project
[Dominion Scout Arctic Anti-Icing Demo](https://branch.flowengineering.com/demo/dominion-scout-arctic-edge-jira-demo).

> **Jira edition.** Same demo as `dominion-flow-ci-demo`, but tickets live in **Jira** (project
> **DDM – Dominion Demo (Flow)** on flowengineering-v3.atlassian.net) instead of Linear, and the Flow project is
> *Dominion Scout & Arctic Edge – Jira demo*. GitHub Actions stands in for Buildkite / their CI.
> All Jira calls are made by **Flow's own Jira integration** (Flow automations), so this repo holds no Jira credentials.

## What's in here

| Path | What it is | Flow requirement |
| -- | -- | -- |
| `dominion_ci/latency_budget.py` | C2 datalink end-to-end latency budget (GCS + ground terminal + RF + air vehicle), flags configs over 250 ms total / 120 ms RF | REQ-45162 (allocates REQ-45141, REQ-45148) |
| `dominion_ci/heater_power.py` | Wing anti-icing heater power command, 2.4–3.0 kW in icing | REQ-45163 |
| `tests/test_latency_budget.py` | Unit tests | TES-45252 |
| `tests/test_latency_sweep.py` | Parametrized sweep of 21 planned link configurations (**one intentionally fails**) | TES-45254 |
| `tests/test_heater_power.py` | Unit tests | TES-45257 |
| `tests/test_heater_sweep.py` | Parametrized 60-case OAT × LWC envelope sweep | TES-45259 |
| coverage / bandit / workflow timing | Gates: ≥ 80 % coverage, 0 high-severity findings, results in Flow ≤ 30 min | TES-45242 / REQ-45158, TES-45245 / REQ-45159, TES-45248 / REQ-45160 |
| `flow_ids.json` | Map of Flow human IDs (TES-/REQ-) to Flow item IDs | |
| `scripts/post_to_flow.py` | Reads JUnit XML + coverage + bandit, groups by Flow test case, posts to Flow | |
| `.github/workflows/flow-ci.yml` | CI: ruff, bandit, pytest → JUnit XML → Flow | |

Every test carries its Flow IDs:

```python
@pytest.mark.flow(test_case="TES-45254", requirements=["REQ-45162", "REQ-45148"])
def test_planned_configuration_within_budget(config, flow_measure): ...
```

`conftest.py` writes those IDs (and any measured value) into the JUnit XML as test properties.

## How results reach Flow (and Jira)

1. The workflow runs on every pull request, every push to `main`, and on demand (*Run workflow*).
2. `scripts/post_to_flow.py` groups the JUnit results by Flow test case, then:
   * **Jira:** fires the Flow automation **CI failure → Jira issue** (`source: "ci-jira-sync"`). A failing test
     case opens, or updates, a Bug in Jira project DDM titled `CI failure: REQ-… <requirement> (TES-…)`
     (label `ci-failure`, unassigned) with the failing tests, the GitHub run link and the Flow link. When that test case
     passes later, Flow renames it `✅ Fixed in PR #n – …`, appends the passing evidence and moves it to **Done**.
     The issue is linked in Flow on the Test Result (*Jira Issue*) and on the requirement (*Jira Ticket*).
   * **Pull request →** a Flow branch named **`GitHub PR #<n> – <PR title>`** is created (or reused on
     later pushes). A Test Result per test case and the requirement Actual Values are written on it, so the branch's
     **Review** tab shows exactly what the PR changed.
   * **Push to `main` →** the Flow automation **Ingest CI test results** (`source: "ci-test-results"`) records the results.
3. On pull requests, Flow's verdict is posted back as **one sticky PR comment** ("Flow requirements check",
   by `github-actions[bot]`, updated in place on re-runs): overall verdict, a table of the affected requirements
   with the status Flow computed on the PR branch, measured vs limit and number of tests, plus links to the Flow
   branch and any Jira issue. If Flow could not be reached, the comment says so instead of claiming a pass.
4. The job summary on GitHub lists the Flow branch, every test case result and the Jira issues.

The intentionally failing case on `main` — *Inuvik relay corridor 300 km / interleaver 8* (≈ 147 ms RF,
≈ 261 ms end to end) — makes TES-45254 **Fail**, pushes REQ-45162's actual value over its 250 ms limit and
opens a Jira Bug in DDM. The branch `demo/inuvik-interleaver-fix` changes that one line to interleaver 4:
open a PR from it and Flow creates a `GitHub PR #n` branch where REQ-45162 turns **Pass** and the Jira issue is
marked fixed.

## Setup

Repository secret (Settings → Secrets and variables → Actions): `FLOW_API_KEY` – Flow API key with access to the demo
project. `FLOW_CUSTOMER` is `demo` (plain text in the workflows). No Jira secret: Flow's Jira integration does the Jira work,
which needs Jira project DDM allowlisted in Flow (Settings → Integrations → Jira) and the automation owner's Atlassian
account connected in Flow.

Run locally:

```bash
pip install -e ".[dev]"
mkdir -p reports
bandit -r dominion_ci -f json -o reports/bandit.json
pytest --junitxml=reports/junit.xml -o junit_family=xunit1 --cov=dominion_ci --cov-report=xml:reports/coverage.xml
python scripts/post_to_flow.py --dry-run         # print the payload
FLOW_API_KEY=... FLOW_CUSTOMER=demo python scripts/post_to_flow.py   # post it
```

Note: the Flow project's Base branch is protected, so automation writes land on the review branch
*"Automation: Ingest CI test results"* until it is reviewed and merged in Flow.

## Related: the manual test loop in Jira

Hardware / HIL tests use two more Flow automations in the same project: **Run test in Jira** (right-click a test case →
Automations → a Jira Task in DDM with steps, the requirements it verifies and an empty Results section, plus a linked
Inconclusive Test Result in Flow) and **Populate test results from Jira** (daily 4 AM PT, or run it by hand: reads Done
issues and sets Pass/Fail + measured values in Flow).

## Resetting the demo (practice runs)

Actions tab → **Demo reset** → **Run workflow** (about 2–3 minutes). It closes open pull requests without merging,
rebuilds `demo/inuvik-interleaver-fix` as a one-line fix on main, has Flow close old `CI failure: REQ-…` Jira Bugs
(moved to Done, labelled `demo-reset`, renamed `[demo reset] …`), and re-runs main CI so the latency requirement is red
again in Flow with one fresh open Jira Bug. The job summary lists the new issue and the next PR number.
