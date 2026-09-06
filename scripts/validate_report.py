"""Offline consistency checks; cannot authenticate a source or run Grok."""
import argparse
import ipaddress
import json
import math
from pathlib import Path
import re
from urllib.parse import urlparse
from schema_check import check, timestamp

ROOT = Path(__file__).resolve().parents[1]
POLICY, METRICS, SEEDS = [json.loads((ROOT / f"config/{n}.json").read_text()) for n in ("policy", "metrics", "seeds")]


def tri_or(a, b):
    return True if a is True or b is True else False if a is False and b is False else None


def value(c, name):
    m = c["metrics"].get(name)
    return m["value"] if m and m["quality"] == "VERIFIED" else None


def required_missing(c):
    return sorted(k for k in POLICY["common_required"] + POLICY["type_required"].get(c["classification"], []) if value(c, k) is None)


def d_predicates(c):
    """Disabled future-design predicates for boundary tests. Never issue PASS."""
    t = POLICY["thresholds"]
    def bounded(key, lo, hi):
        v = value(c, key)
        return None if v is None else lo <= v <= hi
    named, whale = value(c, "named_independent_buyers"), value(c, "whale_net_buy_usd")
    return {"mc": bounded("mc_usd", t["d_mc_min_usd"], t["d_mc_max_usd"]),
            "fo": bounded("fo_pct", t["d_fo_min_pct"], t["d_fo_max_pct"]),
            "turnover": bounded("turnover_24h_mc", t["d_turnover_min"], t["d_turnover_max"]),
            "buyers": tri_or(None if named is None else named >= t["d_named_min"], None if whale is None else whale > 0)}


def valid_recheck(t0, t1, asset0, asset1, rules0, rules1):
    """Time/identity test primitive only; not a scheduler or data recheck."""
    delta = (timestamp(t1)-timestamp(t0)).total_seconds()
    t = POLICY["thresholds"]
    return bool(asset0 and rules0 and asset0 == asset1 and rules0 == rules1 and t["d_recheck_min_seconds"] <= delta <= t["d_recheck_max_seconds"])


def expected_decision(c):
    missing, t = required_missing(c), POLICY["thresholds"]
    if c["object_kind"] != "token" or not c["identity_verified"] or not c["asset_key"]:
        return "UNKNOWN", ["ASSET_IDENTITY_UNVERIFIED"], missing
    reasons = []
    for field, limit in (("bundle_pct", t["bundle_max_pct"]), ("insider_pct", t["insider_max_pct"]),
                         ("fo_pct", t["fo_max_pct"]), ("fo_delta_24h_pp", t["fo_delta_max_pp"])):
        v = value(c, field)
        if v is not None and v > limit:
            reasons.append(field.upper()+"_ABOVE_MAX")
    for field, target in (("external_market", True), ("sellability_checked", True), ("bot_detected", False)):
        v = value(c, field)
        if v is not None and v is not target:
            reasons.append(field.upper()+"_REJECTED")
    fomo, mc = value(c, "fomo_independent_families"), value(c, "mc_usd")
    if fomo is not None and fomo >= t["fomo_family_block_at"]:
        reasons.append("FOMO_CLUSTER_BLOCK")
    if mc is not None and mc <= 0:
        reasons.append("INVALID_MARKET_CAP")
    if reasons:
        return "FAIL", sorted(reasons), missing
    kind = c["classification"]
    if kind == "AMBIGUOUS":
        return "UNKNOWN", ["CLASSIFICATION_AMBIGUOUS"], missing
    if kind == "NONE":
        return "FAIL", ["NO_ELIGIBLE_CLASS"], missing
    if kind in POLICY["disabled_types"]:
        return "DISABLED", ["TYPE_DISABLED"], missing
    if kind == "B":
        age = value(c, "permission_age_hours")
        if age is not None and age >= t["b_event_age_max_hours_exclusive"]:
            reasons.append("B_EVENT_EXPIRED")
        if mc is not None and mc >= t["b_mc_max_usd_exclusive"]:
            reasons.append("B_MARKET_CAP_ABOVE_LIMIT")
    if reasons:
        return "FAIL", sorted(reasons), missing
    if missing:
        return "UNKNOWN", ["REQUIRED_DATA_UNKNOWN"], missing
    return "OBSERVE", ["OBSERVATION_ONLY"], []


def public_https(url):
    p = urlparse(url)
    host = p.hostname or ""
    if p.scheme != "https" or not host or p.username or p.password or "." not in host:
        return False
    if host == "localhost" or host.endswith((".localhost", ".local", ".internal")):
        return False
    try:
        return ipaddress.ip_address(host).is_global
    except ValueError:
        return True  # Runtime fetcher must also validate DNS and redirects.


def validate(report, expected_runtime="LIVE"):
    def finite(node):
        if isinstance(node, float):
            return math.isfinite(node)
        if isinstance(node, dict):
            return all(finite(v) for v in node.values())
        if isinstance(node, list):
            return all(finite(v) for v in node)
        return True
    if not finite(report):
        return ["NON_FINITE_NUMBER"]
    schema = json.loads((ROOT / "schemas/report.schema.json").read_text())
    errors = check(report, schema)
    if errors:
        return errors
    def require(ok, code):
        if not ok:
            errors.append(code)
    require(report["runtime_mode"] == expected_runtime, "RUNTIME_MODE_MISMATCH")
    now = timestamp(report["evaluated_at"])
    start, end = timestamp(report["window_start"]), timestamp(report["window_end"])
    require((end-start).total_seconds() == 86400 and start < end <= now, "INVALID_RUN_WINDOW")
    evidence = {e["id"]: e for e in report["evidence"]}
    require(len(evidence) == len(report["evidence"]), "DUPLICATE_EVIDENCE_ID")
    def refs(ids, label, mandatory=False):
        require(not mandatory or bool(ids), label+": EVIDENCE_REQUIRED")
        require(all(i in evidence for i in ids), label+": EVIDENCE_NOT_FOUND")
        return [evidence[i] for i in ids if i in evidence]
    for e in evidence.values():
        require(public_https(e["url"]), e["id"]+": UNSAFE_SOURCE_URL")
        require(timestamp(e["observed_at"]) <= timestamp(e["fetched_at"]) <= now, e["id"]+": FUTURE_OR_REVERSED_EVIDENCE")
        if e["published_at"]:
            require(timestamp(e["published_at"]) <= timestamp(e["fetched_at"]), e["id"]+": FUTURE_PUBLICATION")
    primary = {s["handle"].lower() for g in ("priority_3", "priority_2") for s in SEEDS[g]}
    cn = {s.lower() for s in SEEDS["chinese_thermometer"]}
    coverage = {c["handle"].lower(): c["status"] for c in report["coverage"]}
    require(len(coverage) == len(report["coverage"]), "DUPLICATE_COVERAGE_HANDLE")
    if report["run_status"] == "SUCCESS":
        require(primary | cn <= coverage.keys() and all(s == "COMPLETE" for s in coverage.values()), "SUCCESS_WITH_INCOMPLETE_COVERAGE")
    if report["run_status"] != "FAILED":
        require(any(coverage.get(h) in ("COMPLETE", "PARTIAL") for h in primary), "FAILED_DISCOVERY_MUST_REPORT_FAILED")
    else:
        require(not report["objects"], "FAILED_RUN_CANNOT_PUBLISH_CANDIDATES")
    if report["weather"] == "quiet":
        require(report["run_status"] == "SUCCESS" and not report["objects"], "QUIET_IS_NOT_FAILURE")
    if not report["objects"] and report["run_status"] != "SUCCESS":
        require(report["weather"] == "unknown", "DEGRADED_EMPTY_WEATHER_MUST_BE_UNKNOWN")
    ids, assets = set(), set()
    for c in report["objects"]:
        label, key, grammars = c["id"], c["asset_key"], set(c["grammars"])
        require(label not in ids, "DUPLICATE_OBJECT_ID")
        ids.add(label)
        if c["identity_verified"]:
            require(c["object_kind"] == "token" and isinstance(key, str) and re.fullmatch(r"eip155:[1-9][0-9]*:0x[0-9a-f]{40}", key) is not None, label+": INVALID_VERIFIED_ASSET_ID")
        if key:
            require(key not in assets, "DUPLICATE_ASSET_KEY")
            assets.add(key)
        origin = c["origin"]
        handle = origin["handle"].lower()
        forbidden = {h.lower() for group in ("excluded_discovery", "temperature_only", "official_event_only", "chinese_thermometer") for h in SEEDS[group]}
        require(handle not in forbidden, label+": INELIGIBLE_DISCOVERY_SOURCE")
        if origin["path"] == "SEED":
            require(handle in primary and origin["parent_handle"] is None, label+": INVALID_SEED_PATH")
        else:
            require((origin["parent_handle"] or "").lower() in primary and handle in coverage, label+": INVALID_ONE_HOP_PATH")
        refs(origin["evidence_ids"], label+": origin", True)
        refs(c["grammar_evidence_ids"], label+": grammar", True)
        identity_sources = refs(c["identity_evidence_ids"], label+": identity", c["identity_verified"])
        if c["identity_verified"]:
            require(all(e["asset_key"] == key and e["source_kind"] in ("OFFICIAL", "CHAIN", "DATA_PROVIDER") for e in identity_sources), label+": INVALID_IDENTITY_EVIDENCE")
        refs(c["conflict"]["evidence_ids"], label+": conflict", c["conflict"]["status"] == "VERIFIED")
        if c["classification"] == "A":
            require(bool(grammars & {"VACUUM", "TANDEM", "MECHANISM"}) and "LOTTERY" not in grammars, label+": INVALID_A_GRAMMAR")
        if c["classification"] == "B":
            require("PERMISSION" in grammars and "LOTTERY" not in grammars, label+": INVALID_B_GRAMMAR")
        if grammars == {"LOTTERY"}:
            require(c["classification"] == "C", label+": LOTTERY_CANNOT_BYPASS_C")
        elif "LOTTERY" in grammars:
            require(c["classification"] in ("C", "AMBIGUOUS"), label+": MIXED_LOTTERY_CANNOT_BYPASS_C")
        fomo = value(c, "fomo_independent_families")
        if fomo is not None and fomo >= 2:
            require(c["p_level"] == "P2", label+": FOMO_P2_PRIORITY")
        elif c["p_level"] == "P0":
            require(c["cn_coverage_complete"] and c["cn_register"] == "NOT_OBSERVED_IN_SCOPE" and bool(grammars & {"PERMISSION", "VACUUM", "TANDEM"}), label+": INVALID_P0")
        elif c["p_level"] == "P1":
            require(c["cn_coverage_complete"] and c["cn_register"] == "FLASH" and bool(grammars & {"MECHANISM", "LOTTERY"}), label+": INVALID_P1")
        if c["cn_coverage_complete"]:
            require(all(coverage.get(h) == "COMPLETE" for h in cn), label+": FALSE_CN_COVERAGE")
        for name, m in c["metrics"].items():
            ev = refs(m["evidence_ids"], label+": "+name)
            if m["quality"] != "VERIFIED":
                require(m["value"] is None, label+": UNKNOWN_VALUE_MUST_BE_NULL:"+name)
                continue
            require(m["value"] is not None and bool(ev), label+": VERIFIED_NEEDS_VALUE_AND_EVIDENCE:"+name)
            require(bool(m["method_id"]) and m["method_id"].lower() not in {"unknown", "tbd", "estimated", "unverified"}, label+": METHOD_REQUIRED:"+name)
            require(bool(m["observed_at"] and m["fetched_at"]), label+": METRIC_TIME_REQUIRED:"+name)
            if m["observed_at"] and m["fetched_at"]:
                observed, fetched = timestamp(m["observed_at"]), timestamp(m["fetched_at"])
                require(observed <= fetched <= now and 0 <= (now-observed).total_seconds() <= METRICS[name]["max_age_seconds"], label+": INVALID_OR_STALE_METRIC:"+name)
                require(any(timestamp(e["observed_at"]) == observed for e in ev), label+": SOURCE_OBSERVATION_TIME_MISMATCH:"+name)
            require(all(e["source_kind"] in METRICS[name]["sources"] for e in ev), label+": WRONG_SOURCE_KIND:"+name)
            if c["object_kind"] == "token" and key:
                require(all(e["asset_key"] == key for e in ev), label+": CROSS_ASSET_EVIDENCE:"+name)
            ws, we = m["window_start"], m["window_end"]
            require((ws is None) == (we is None), label+": INCOMPLETE_METRIC_WINDOW:"+name)
            if ws and we:
                require(timestamp(ws) <= timestamp(we) <= now, label+": INVALID_METRIC_WINDOW:"+name)
            if name in {"fo_delta_24h_pp", "turnover_24h_mc", "named_independent_buyers", "whale_net_buy_usd", "dev_sold", "fomo_independent_families"}:
                require(bool(ws and we) and (timestamp(we)-timestamp(ws)).total_seconds() == 86400, label+": EXACT_24H_WINDOW_REQUIRED:"+name)
            if name in {"fo_delta_24h_pp", "holders_non_decreasing", "drawdown_verified", "fo_stable"}:
                require(len(ev) >= 2, label+": MULTI_POINT_EVIDENCE_REQUIRED:"+name)
            if name == "permission_age_hours":
                require(bool(ws and we) and timestamp(we) == now, label+": EVENT_WINDOW_REQUIRED")
                if ws and m["value"] is not None:
                    require(abs((now-timestamp(ws)).total_seconds()/3600-m["value"]) < 1e-6, label+": EVENT_AGE_MISMATCH")
                    require(any(e["published_at"] == ws for e in ev), label+": EVENT_PUBLICATION_MISMATCH")
        status, reasons, missing = expected_decision(c)
        require(c["status"] == status, label+": DECISION_MISMATCH:"+status)
        require(sorted(c["reason_codes"]) == sorted(reasons), label+": REASON_CODES_MISMATCH")
        require(sorted(c["missing_fields"]) == missing, label+": MISSING_FIELDS_MISMATCH")
    require(re.search(r"建议(?:立即)?买入|首仓\s*[0-9]|加仓至\s*[0-9]|门\s*[=＝]\s*可", json.dumps(report, ensure_ascii=False)) is None, "ACTIONABLE_OUTPUT_DETECTED")
    return errors


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("report", type=Path)
    parser.add_argument("--runtime", choices=["LIVE", "REPLAY"], default="LIVE")
    args = parser.parse_args()
    report = json.loads(args.report.read_text(), parse_constant=lambda v: (_ for _ in ()).throw(ValueError(v)))
    errors = validate(report, args.runtime)
    if errors:
        raise SystemExit("\n".join(errors))
    print("Report structure/semantics valid; source truth and live Grok behavior unverified.")


if __name__ == "__main__":
    main()
