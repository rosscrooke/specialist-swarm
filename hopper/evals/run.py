"""Run Hopper's agent evals.

    python -m evals.run                     # offline: deterministic, free — what CI runs
    python -m evals.run --live              # also grades Claude (Intent + Explainer); needs ANTHROPIC_API_KEY
    python -m evals.run --update-golden     # re-record evals/golden.json after an intended change
    python -m evals.run --record            # re-record the world-feed cassette (network), then the golden
    python -m evals.run --report summary.md # append a Markdown report (CI: $GITHUB_STEP_SUMMARY)

SF live feeds (511, NWS, OSRM, GBFS) are always off, and world trips and flights replay a
recorded cassette (evals/fixtures/world_cassette.json) with a frozen clock, so every run plans
on the same data and the numbers are reproducible. --live only switches the two Claude agents on.
"""
import argparse
import json
import os
import re
import sys
from datetime import timedelta
from pathlib import Path

os.environ["HOPPER_OFFLINE"] = "1"          # before app imports: fixture data, no network

from app import agents, bars, guard, tools, world   # noqa: E402
from app.server import app                          # noqa: E402
from evals import checks, replay                    # noqa: E402

HERE = Path(__file__).parent
CASES = json.loads((HERE / "cases.json").read_text())
GOLDEN_PATH = HERE / "golden.json"
MODES = ("hustle", "broke", "burn")
TOL = {"total_min_pct": 10, "cost_usd": 0.5, "kcal_pct": 15}
PLAN_KEYS = ("origin", "destination", "origin_place", "destination_place", "hour", "weather", "event",
             "avoid_steep", "max_cost")


def plan(case, mode):
    body = {k: case[k] for k in PLAN_KEYS if case.get(k) is not None}
    resp, feasible, *_ = agents.orchestrate({**body, "mode": mode, "_visitor": "evals"})
    return resp, feasible


def fingerprint(option):
    return {"legs": "+".join(f"{l['mode']}:{l['line']}" if l["line"] else l["mode"] for l in option["legs"]),
            "total_min": option["total_min"], "cost": option["cost"], "kcal": option["kcal"]}


def golden_diff(want, got):
    """Exact on the route (legs / airports / bars), tolerant on the numbers."""
    fails = []
    for k in ("legs", "airports", "bars"):
        if k in want and want[k] != got.get(k):
            fails.append(f"{k} changed: {want[k]} → {got.get(k)}")
    if "total_min" in want and abs(got["total_min"] - want["total_min"]) > want["total_min"] * TOL["total_min_pct"] / 100:
        fails.append(f"time {want['total_min']} → {got['total_min']} min")
    for k in ("cost", "total_low"):
        if k in want and abs(got[k] - want[k]) > max(TOL["cost_usd"], abs(want[k]) * 0.05):
            fails.append(f"{k} ${want[k]:.2f} → ${got[k]:.2f}")
    if "kcal" in want and abs(got["kcal"] - want["kcal"]) > max(10, want["kcal"] * TOL["kcal_pct"] / 100):
        fails.append(f"kcal {want['kcal']} → {got['kcal']}")
    return fails


class Report:
    def __init__(self):
        self.results, self.metrics = [], {}
        self.golden, self.record = {}, False

    def add(self, suite, case, fails, known=None):
        """`known` names an accepted, documented gap: its failures are reported but don't fail CI."""
        self.results.append({"suite": suite, "case": case, "ok": not fails or bool(known), "fails": fails,
                             "known": known if fails else None})

    def check_golden(self, name, got):
        if self.record:
            self.golden[name] = got
        elif name in self.golden:
            self.add("golden", name, golden_diff(self.golden[name], got))
        else:
            self.add("golden", name, ["no golden recorded — run with --update-golden"])

    @property
    def failures(self):
        return [r for r in self.results if not r["ok"]]

    def markdown(self, live):
        suites = {}
        for r in self.results:
            s = suites.setdefault(r["suite"], [0, 0])
            s[0] += r["ok"]
            s[1] += 1
        lines = [f"## Hopper agent evals ({'live Claude' if live else 'offline'})", "",
                 "| Suite | Passed |", "|---|---|"]
        lines += [f"| {s} | {ok}/{n} {'✅' if ok == n else '❌'} |" for s, (ok, n) in suites.items()]
        if self.metrics:
            lines += ["", "| Metric | Value |", "|---|---|"]
            lines += [f"| {k} | {v} |" for k, v in self.metrics.items()]
        known = [r for r in self.results if r.get("known")]
        if known:
            lines += ["", "### Known issues (reported, not failing)", ""]
            lines += [f"- **{r['suite']} · {r['case']}**: {'; '.join(r['fails'])} — {r['known']}" for r in known]
        if self.failures:
            lines += ["", "### Failures", ""]
            lines += [f"- **{r['suite']} · {r['case']}**: {'; '.join(r['fails'])}" for r in self.failures]
        return "\n".join(lines) + "\n"


def run_trips(report, cases, prefix=""):
    """Ground trips (SF or world): every Mode, every check, plus golden fingerprints."""
    spec = CASES["mode_spec"]
    for case in cases:
        by_mode, feasible_by_mode = {}, {}
        for mode in MODES:
            name = f"{prefix}{case['id']}/{mode}"
            try:
                resp, feasible = plan(case, mode)
            except agents.PlanError as e:
                report.add("integrity", name, [f"planner refused: {e}"])
                continue
            by_mode[mode], feasible_by_mode[mode] = resp, feasible
            report.add("integrity", name, checks.integrity(resp))
            report.add("explanation", name, checks.explanation(resp))
            report.add("labels", name, checks.labels(resp))
            report.add("mode", name, checks.mode_correctness(mode, resp, feasible, spec[mode]))
            report.check_golden(name, fingerprint(resp["options"][0]))
            for step in resp["trace"]:
                if step["agent"] == "Explainer" and step["kind"] == "llm":
                    m = re.match(r"(\d+) explanations(?:, (\d+) failed)?", step["detail"])
                    if m:
                        report.metrics.setdefault("_llm", [0, 0])
                        report.metrics["_llm"][0] += int(m.group(1)) + int(m.group(2) or 0)
                        report.metrics["_llm"][1] += int(m.group(2) or 0)
        if len(by_mode) == len(MODES):
            report.add("cross-mode", prefix + case["id"],
                       checks.cross_mode({m: r["options"][0] for m, r in by_mode.items()},
                                         {m: r.get("notice") for m, r in by_mode.items()},
                                         spec, feasible_by_mode["hustle"]))
        if prefix and by_mode:
            report.add("world", case["id"], checks.world_expectations(case, by_mode))
        elif case.get("expect"):
            report.add("expectations", case["id"], checks.expectations(case, by_mode))


def _post(path, body):
    guard.reset()                                    # the eval is one process, not an abusive visitor
    r = app.test_client().post(path, json=body)
    return r.status_code, r.get_json()


def run_flights(report):
    date = (world.local_now("America/Los_Angeles") + timedelta(days=14)).date().isoformat()
    for case in CASES["flights"]:
        for mode in case["modes"]:
            name = f"{case['id']}/{mode}"
            body = {k: case[k] for k in ("origin", "origin_place", "destination_place", "hour") if k in case}
            code, out = _post("/api/flights", {**body, "date": date, "mode": mode})
            if code != 200:
                report.add("flights", name, [f"HTTP {code}: {out.get('error')}"])
                continue
            report.add("flights", name, checks.flights(case, mode, out), case.get("known_issue"))
            top = out["options"][0]
            report.check_golden(f"flights/{name}", {"airports": f"{top['dep']['iata']}>{top['arr']['iata']}",
                                                    "total_min": top["total_min"], "total_low": top["total_low"]})


def run_crawls(report):
    code, out = _post("/api/crawl", {"start": "washington_sq", "stops": 3})
    report.add("bar crawl", "21+ gate", [] if code == 403 else [f"crawl without age check returned HTTP {code}"])
    by_id = {b["id"]: b for b in bars.load_bars()[0]}
    for case in CASES["crawls"]:
        body = {k: case[k] for k in ("start", "end", "stops", "vibe", "hour", "weather", "minutes_per_stop") if k in case}
        code, out = _post("/api/crawl", {**body, "age_confirmed": True})
        if code != 200:
            report.add("bar crawl", case["id"], [f"HTTP {code}: {out.get('error')}"])
            continue
        start = tools.latlon(case["start"])
        nearby = sum(1 for b in by_id.values() if bars.vibe_match(b, case["vibe"])
                     and tools.haversine_pts(start, [b["lat"], b["lon"]]) <= 0.6)
        for s in out["itinerary"]["stops"]:
            s["_vibe_ok"] = bars.vibe_match(by_id[s["osm_id"]], case["vibe"]) if s["osm_id"] in by_id else True
        report.add("bar crawl", case["id"], checks.crawl(case, out, nearby))
        report.check_golden(f"crawl/{case['id']}", {"bars": [s["name"] for s in out["itinerary"]["stops"]]})


def run_handoffs(report):
    """The planner routes requests it can't handle itself to the right sub-planner."""
    r, *_ = agents.orchestrate({"origin": "mission_16th", "destination": "castro", "mode": "barcrawl"})
    report.add("hand-off", "barcrawl mode → crawl planner", [] if r.get("redirect") == "barcrawl" else ["no redirect"])
    with replay.cassette(_points()):
        r, *_ = agents.orchestrate({"origin": "union_square", "destination_place": CASES["flights"][0]["destination_place"],
                                    "weather": "clear"})
    report.add("hand-off", "2,500 mi trip → flights", [] if r.get("redirect") == "flights" else ["no redirect"])


def run_intents(report, client):
    for case in CASES["intents"]:
        if case.get("llm_only") and client is None:
            continue
        parsed = agents.intent_agent(case["q"], agents.Trace(), client, case.get("sf_context", True))
        report.add("intent (Claude)" if client else "intent (rules)", case["q"], checks.intent(case, parsed))


def _points():
    places = [c[k] for c in CASES["world"] + CASES["flights"] for k in ("origin_place", "destination_place") if k in c]
    return replay.points_of(places)


def run(live=False, update_golden=False, record=False):
    report = Report()
    client = None
    if live:
        key = os.environ.get("ANTHROPIC_API_KEY")
        if not key:
            raise SystemExit("--live needs ANTHROPIC_API_KEY")
        from anthropic import Anthropic
        client = Anthropic(api_key=key)
        agents._llm = lambda: client                         # Claude on, live feeds still off
        guard.CLAUDE_DAILY_CAP = guard.CLAUDE_VISITOR_DAILY_CAP = 10 ** 6   # the eval isn't a visitor
    if record:
        with replay.cassette(_points(), record=True):        # one pass to fetch the world feeds
            run_trips(Report(), CASES["world"], prefix="world/")
            run_flights(Report())
        update_golden = True
    report.record = update_golden
    if not update_golden and GOLDEN_PATH.exists():
        report.golden = json.loads(GOLDEN_PATH.read_text())
    run_trips(report, CASES["trips"])
    with replay.cassette(_points()):
        run_trips(report, CASES["world"], prefix="world/")
        run_flights(report)
    run_crawls(report)
    run_handoffs(report)
    run_intents(report, None)                                # the rules parser is always graded
    if client:
        run_intents(report, client)
    llm = report.metrics.pop("_llm", None)
    if llm and llm[0]:
        report.metrics["Explainer: Claude sentences grounded on first try"] = \
            f"{llm[0] - llm[1]}/{llm[0]} ({100 * (llm[0] - llm[1]) / llm[0]:.0f}%)"
    if update_golden:
        GOLDEN_PATH.write_text(json.dumps(dict(sorted(report.golden.items())), indent=1, ensure_ascii=False) + "\n")
    return report


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--live", action="store_true", help="grade the Claude agents too")
    ap.add_argument("--update-golden", action="store_true", help="re-record evals/golden.json")
    ap.add_argument("--record", action="store_true", help="re-record the world-feed cassette (needs network)")
    ap.add_argument("--report", help="append a Markdown report to this file")
    ap.add_argument("--json", help="write every result as JSON to this file")
    args = ap.parse_args(argv)
    report = run(args.live, args.update_golden, args.record)
    md = report.markdown(args.live)
    print(md)
    if args.report:
        with open(args.report, "a") as f:
            f.write(md)
    if args.json:
        Path(args.json).write_text(json.dumps({"results": report.results, "metrics": report.metrics}, indent=1))
    return 1 if report.failures else 0


if __name__ == "__main__":
    sys.exit(main())
