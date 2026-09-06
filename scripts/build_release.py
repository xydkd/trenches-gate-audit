"""Build self-contained Grok prompt and Draft 2020-12 report schema. No network."""
import argparse
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read_json(name):
    return json.loads((ROOT / name).read_text())


def obj(properties, required=None):
    return {"type": "object", "properties": properties,
            "required": list(properties) if required is None else required,
            "additionalProperties": False}


def enum(*values):
    return {"enum": list(values)}


def array(items, **limits):
    return {"type": "array", "items": items, **limits}


def schema():
    policy, metrics = read_json("config/policy.json"), read_json("config/metrics.json")
    string = {"type": "string", "minLength": 1}
    nullable = {"type": ["string", "null"], "minLength": 1}
    timestamp = {"type": "string", "format": "date-time"}
    nullable_time = {"type": ["string", "null"], "format": "date-time"}
    refs = array(string, uniqueItems=True)
    shared_metric = obj({
        "value": {"type": ["number", "boolean", "null"]}, "unit": string,
        "quality": enum("VERIFIED", "UNAVAILABLE", "UNVERIFIED", "STALE", "CONFLICT"),
        "observed_at": nullable_time, "fetched_at": nullable_time,
        "window_start": nullable_time, "window_end": nullable_time,
        "method_id": nullable, "evidence_ids": refs})
    metric_schemas = {}
    for key, spec in metrics.items():
        value = {"type": [spec["type"], "null"]}
        for bound in ("minimum", "maximum"):
            if bound in spec:
                value[bound] = spec[bound]
        metric_schemas[key] = {"allOf": [{"$ref": "#/$defs/metric"},
            {"properties": {"value": value, "unit": {"const": spec["unit"]}}}]}
    evidence = obj({
        "id": string, "url": {"type": "string", "format": "uri"},
        "source_kind": enum("X", "OFFICIAL", "PRIMARY_ANALYSIS", "DATA_PROVIDER", "CHAIN"),
        "published_at": nullable_time, "observed_at": timestamp, "fetched_at": timestamp,
        "asset_key": nullable, "summary": string})
    candidate = obj({
        "id": string, "name": string,
        "object_kind": enum("project", "chain", "token"),
        "asset_key": nullable, "identity_verified": {"type": "boolean"},
        "identity_evidence_ids": refs,
        "origin": obj({"path": enum("SEED", "ONE_HOP"), "handle": string,
                       "parent_handle": nullable, "evidence_ids": refs}),
        "conflict": obj({"status": enum("VERIFIED", "UNKNOWN", "NOT_OBSERVED"),
                         "note": string, "evidence_ids": refs}),
        "grammars": array(enum("PERMISSION", "VACUUM", "TANDEM", "MECHANISM", "LOTTERY", "LAG"), minItems=1, uniqueItems=True),
        "grammar_evidence_ids": refs,
        "p_level": enum("P0", "P1", "P2", "CONFIRMATION", "UNKNOWN"),
        "cn_register": enum("NOT_OBSERVED_IN_SCOPE", "FLASH", "CONVICTION", "UNKNOWN"),
        "cn_coverage_complete": {"type": "boolean"},
        "classification": enum("A", "B", "C", "D", "AMBIGUOUS", "NONE"),
        "classification_reason": string,
        "metrics": obj(metric_schemas, []),
        "status": enum(*policy["allowed_statuses"]),
        "reason_codes": array(string, minItems=1, uniqueItems=True),
        "missing_fields": array(enum(*metrics), uniqueItems=True),
        "falsify_check": string})
    result = obj({
        "release_version": {"const": policy["version"]},
        "schema_version": {"const": policy["schema_version"]},
        "product_mode": {"const": "OBSERVATION"},
        "runtime_mode": enum("LIVE", "REPLAY"),
        "run_id": string, "evaluated_at": timestamp,
        "window_start": timestamp, "window_end": timestamp,
        "run_status": enum("SUCCESS", "PARTIAL", "FAILED"),
        "weather": enum("discovery", "confirmation", "extreme-FOMO", "quiet", "unknown"),
        "coverage": array(obj({"handle": string, "status": enum("COMPLETE", "PARTIAL", "FAILED"),
                               "queries": array(string, minItems=1), "note": string})),
        "evidence": array(evidence),
        "objects": array(candidate, maxItems=policy["max_objects"]),
        "stance_shifts": array(string), "fomo_panel": array(string),
        "lag": string, "checks_24h": array(string, maxItems=3),
        "disclaimer": {"const": policy["disclaimer"]}})
    return {"$schema": "https://json-schema.org/draft/2020-12/schema", "$defs": {"metric": shared_metric}, **result}


def products():
    policy, seeds, metrics = [read_json(f"config/{name}.json") for name in ("policy", "seeds", "metrics")]
    out_schema = schema()
    prompt = (ROOT / "prompts/grok-observation.template.md").read_text()
    for key, value in {"POLICY": policy, "SEEDS": seeds, "METRICS": metrics, "SCHEMA": out_schema}.items():
        prompt = prompt.replace("{{" + key + "}}", json.dumps(value, ensure_ascii=False, separators=(",", ":")))
    for key, value in policy["thresholds"].items():
        prompt = prompt.replace("{{" + key + "}}", str(value))
    if "{{" in prompt:
        raise ValueError("Unexpanded prompt placeholder")
    header = "# Grok 发布提示词 v1.0.0\n\n此文件由构建脚本生成。实际任务复制 [dist/GROK_TASK_PROMPT.txt](dist/GROK_TASK_PROMPT.txt) 全文。不要复制旧归档。\n\n"
    output = {
        "schemas/report.schema.json": json.dumps(out_schema, ensure_ascii=False, indent=2) + "\n",
        "dist/GROK_TASK_PROMPT.txt": prompt,
        "04-PROMPT-v2.md": header + "```text\n" + prompt + "```\n"}
    manifest = {"release_version": policy["version"], "source_base": "615db59d7aa33ae3d2a2c72a64b413fea8688a0f",
                "files": {k: hashlib.sha256(v.encode()).hexdigest() for k, v in output.items()}}
    for name in ("config/policy.json", "config/seeds.json", "config/metrics.json", "prompts/grok-observation.template.md"):
        manifest["files"][name] = hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
    output["dist/manifest.json"] = json.dumps(manifest, ensure_ascii=False, indent=2) + "\n"
    return output


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    mismatch = []
    for name, content in products().items():
        path = ROOT / name
        if args.check:
            if not path.exists() or path.read_text() != content:
                mismatch.append(name)
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content)
    if mismatch:
        raise SystemExit("Generated files differ: " + ", ".join(mismatch))
    print("Release build " + ("verified" if args.check else "written"))


if __name__ == "__main__":
    main()
