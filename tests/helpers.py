import copy
from datetime import timedelta
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from validate_report import POLICY, METRICS, SEEDS, timestamp

NOW = "2026-09-05T00:05:00+00:00"
END = "2026-09-05T00:00:00+00:00"
START = "2026-09-04T00:00:00+00:00"
ASSET = "eip155:1:0x" + "1"*40


def base_report():
    handles = [s["handle"] for g in ("priority_3", "priority_2") for s in SEEDS[g]] + SEEDS["chinese_thermometer"]
    return {"release_version": "1.0.0", "schema_version": "1.0.0", "product_mode": "OBSERVATION",
            "runtime_mode": "REPLAY", "run_id": "SYNTHETIC-DO-NOT-PUBLISH", "evaluated_at": NOW,
            "window_start": START, "window_end": END, "run_status": "SUCCESS", "weather": "quiet",
            "coverage": [{"handle": h, "status": "COMPLETE", "queries": ["from:"+h], "note": "合成覆盖，用于测试；未执行真实搜索"} for h in handles],
            "evidence": [], "objects": [], "stance_shifts": [], "fomo_panel": [],
            "lag": "合成测试，不代表实际中英文传播情况", "checks_24h": [], "disclaimer": POLICY["disclaimer"]}


def evidence(report, name, source="DATA_PROVIDER", observed=NOW, published=None):
    e = {"id": name, "url": "https://example.com/synthetic/"+name,
         "source_kind": source, "published_at": published, "observed_at": observed,
         "fetched_at": NOW, "asset_key": ASSET,
         "summary": "合成事实，不对应真实代币、页面或交易；仅用于离线逻辑测试"}
    report["evidence"].append(e)
    return name


def set_metric(report, c, name, v, quality="VERIFIED"):
    spec = METRICS[name]
    source = spec["sources"][0]
    refs = [evidence(report, name+"-now", source)]
    ws = we = None
    if name in {"fo_delta_24h_pp", "turnover_24h_mc", "named_independent_buyers", "whale_net_buy_usd", "dev_sold", "fomo_independent_families"}:
        we = NOW
        ws = (timestamp(NOW)-timedelta(days=1)).isoformat()
    if name in {"fo_delta_24h_pp", "holders_non_decreasing", "drawdown_verified", "fo_stable"}:
        refs.append(evidence(report, name+"-before", source, observed=(timestamp(NOW)-timedelta(days=1)).isoformat()))
    if name == "permission_age_hours":
        we = NOW
        ws = (timestamp(NOW)-timedelta(hours=v)).isoformat()
        report["evidence"][-1]["published_at"] = ws
    c["metrics"][name] = {"value": v, "unit": spec["unit"], "quality": quality,
                          "observed_at": NOW, "fetched_at": NOW, "window_start": ws, "window_end": we,
                          "method_id": "SYNTHETIC-fixture-v1-"+name, "evidence_ids": refs}


def complete_report(kind="A"):
    r = base_report()
    eid = evidence(r, "discovery", "X", published=END)
    c = {"id": "synthetic-token", "name": "合成测试对象（非真实标的）", "object_kind": "token", "asset_key": ASSET,
         "identity_verified": True, "identity_evidence_ids": ["mc_usd-now"], "origin": {"path": "SEED", "handle": "neodot", "parent_handle": None, "evidence_ids": [eid]},
         "conflict": {"status": "UNKNOWN", "note": "没有真实利益关系核验", "evidence_ids": []},
         "grammars": ["VACUUM"] if kind != "B" else ["PERMISSION"], "grammar_evidence_ids": [eid],
         "p_level": "P0", "cn_register": "NOT_OBSERVED_IN_SCOPE", "cn_coverage_complete": True,
         "classification": kind, "classification_reason": "合成规则用例",
         "metrics": {}, "status": "OBSERVE", "reason_codes": ["OBSERVATION_ONLY"], "missing_fields": [],
         "falsify_check": "仅检查合成数据一致性，不产生交易行为"}
    r["objects"] = [c]
    r["weather"] = "discovery"
    for name, v in {"mc_usd": 1000000, "external_market": True, "sellability_checked": True,
                    "bundle_pct": 10, "insider_pct": 10, "fo_pct": 20, "fo_delta_24h_pp": 2,
                    "bot_detected": False, "fomo_independent_families": 0}.items():
        set_metric(r, c, name, v)
    set_metric(r, c, "permission_age_hours" if kind == "B" else "third_party_metric", 12)
    return r


def example_reports():
    observed = complete_report()
    missing = copy.deepcopy(observed)
    c = missing["objects"][0]
    c["metrics"]["fo_pct"]["quality"] = "UNAVAILABLE"
    c["metrics"]["fo_pct"]["value"] = None
    c.update(status="UNKNOWN", reason_codes=["REQUIRED_DATA_UNKNOWN"], missing_fields=["fo_pct"])
    failed = base_report()
    failed.update(run_status="FAILED", weather="unknown", coverage=[])
    return {"replay-observe.json": observed, "replay-missing.json": missing,
            "replay-empty.json": base_report(), "replay-failed.json": failed}


if __name__ == "__main__":
    for name, report in example_reports().items():
        path = ROOT / "examples" / name
        path.parent.mkdir(exist_ok=True)
        path.write_text(json.dumps(report, ensure_ascii=False, indent=2)+"\n")
