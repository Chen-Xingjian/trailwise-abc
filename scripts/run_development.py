"""Collect genuine local RAG/no-RAG development responses without automatic grading.

Unavailable preflight creates no run. Evidence previews never count as model runs.
The user has authorized local development: old dataset executable_now=false flags
describe an unperformed preflight, not an additional approval requirement.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse, urlunparse

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.citations import citation_ids

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATASET = ROOT / "evaluation/development.json"
FROZEN_REVIEW = ROOT.parent / "outputs/nepal_review_round3_frozen_20261118"
ENV_KEYS = ("MODEL_ID", "MODEL_BASE_URL", "MODEL_TIMEOUT", "MAX_TOKENS", "TEMPERATURE",
            "EMBEDDING_MODE", "EMBEDDING_MODEL", "EMBEDDING_DEVICE")


def utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds")


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n")


def local_api_url(value: str) -> str:
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
        raise ValueError("The development runner only calls a loopback application endpoint.")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("The API endpoint must not contain credentials, a query or a fragment.")
    return value.rstrip("/")


def public_endpoint(value: object) -> object:
    if not isinstance(value, str):
        return value
    parsed = urlparse(value)
    if not parsed.scheme or not parsed.hostname:
        return value
    host = f"[{parsed.hostname}]" if ":" in parsed.hostname else parsed.hostname
    if parsed.port is not None:
        host += f":{parsed.port}"
    return urlunparse((parsed.scheme, host, parsed.path, "", "", ""))


def environment_observation() -> dict:
    """Read only an explicit non-secret allowlist; never log an API key or all env."""
    dotenv = {}
    path = ROOT / ".env"
    if path.is_file():
        for raw in path.read_text().splitlines():
            line = raw.strip()
            if line.startswith("export "):
                line = line[7:].strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            if key in ENV_KEYS:
                value = value.strip()
                if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
                    value = value[1:-1]
                dotenv[key] = public_endpoint(value) if key.endswith("_URL") else value
    process = {key: (public_endpoint(os.environ[key]) if key.endswith("_URL") else os.environ[key])
               for key in ENV_KEYS if key in os.environ}
    return {
        "process_env": process,
        "dotenv_literal_observation": dotenv,
        "verification": "Runner-side observations only; these do not prove a separately started server's effective settings.",
    }


def status_snapshot(status: dict) -> dict:
    generation = status.get("generation_config") or status.get("generation") or {}
    allowed_generation = {key: generation[key] for key in
                          ("temperature", "max_tokens", "model_base_url", "model_timeout", "seed")
                          if key in generation}
    if "model_base_url" in allowed_generation:
        allowed_generation["model_base_url"] = public_endpoint(allowed_generation["model_base_url"])
    return {
        "release_id": status.get("release_id"),
        "accepted_fact_count": status.get("accepted_fact_count"),
        "indexed_fact_count": status.get("indexed_fact_count"),
        "model": {key: status.get("model", {}).get(key) for key in ("connected", "model_id", "message")},
        "embedding": {key: status.get("embedding", {}).get(key) for key in ("mode", "ready", "message")},
        "index": {key: status.get("index", {}).get(key) for key in ("ready", "mode", "fingerprint")},
        "generation_config": allowed_generation or None,
        "generation_config_verification": "SERVER_REPORTED" if allowed_generation else "NOT_REPORTED_BY_SERVER",
    }


def check_preflight(status: dict, dataset: dict) -> None:
    if not status.get("model", {}).get("connected") or not status.get("model", {}).get("model_id"):
        raise ValueError("A genuine local generation model is not connected.")
    embedding = status.get("embedding", {})
    if embedding.get("mode") != "sentence-transformers" or embedding.get("ready", True) is False:
        raise ValueError("Use the configured sentence-transformers embedding model; hash mode is not a model-comparison run.")
    if status.get("index", {}).get("ready", True) is False:
        raise ValueError("The retrieval index is unavailable.")
    if not status.get("index", {}).get("fingerprint"):
        raise ValueError("The server did not identify its index fingerprint.")
    if status.get("release_id") != dataset.get("data_release_id"):
        raise ValueError("The server release does not match this development dataset.")


def check_output(path: Path) -> None:
    resolved = path.resolve()
    if resolved.is_relative_to(FROZEN_REVIEW.resolve()):
        raise ValueError("Run output must not modify the frozen R03 review.")
    for directory in (resolved, *resolved.parents):
        candidate = directory / "release_manifest.json"
        if candidate.is_file():
            try:
                manifest = json.loads(candidate.read_text())
            except (OSError, ValueError):
                continue
            if manifest.get("frozen"):
                raise ValueError("Run output must not be inside a frozen review snapshot.")
    if path.exists() and any(path.iterdir()):
        raise ValueError("Run output already contains files; choose a new directory.")


def safe_csv(value: object) -> str:
    text = "" if value is None else str(value)
    if text.lstrip().startswith(("=", "+", "-", "@")) or text.startswith(("\t", "\r", "\n")):
        return "'" + text
    return text


def diagnostic(item: dict, mode: str, response: dict) -> dict:
    kind = response.get("answer_kind", "unknown")
    evidence = response.get("evidence") or []
    supplied = {e["fact_id"] for e in evidence if isinstance(e, dict) and e.get("fact_id")}
    required = set(item.get("required_fact_ids", []))
    citations = citation_ids(response.get("answer") or "")
    recall = None
    if mode == "rag" and kind == "llm" and required and item.get("comparison_group") != "BOUNDARY":
        recall = len(required & supplied) / len(required)
    return {
        "retrieved_fact_ids": sorted(supplied),
        "required_fact_ids": sorted(required),
        "required_fact_recall_at_k": recall,
        "recall_label": "Retrieval diagnostic only; not answer accuracy. Not computed for boundary/policy-only or non-LLM responses.",
        "citation_ids": sorted(citations),
        "citations_not_in_supplied_evidence": sorted(citations - supplied),
        "citation_ids_all_supplied": citations <= supplied if citations else None,
        "citation_membership_is_not_support_correctness": True,
        "citation_support_correctness": None,
    }


def write_grading(path: Path, records: list[dict], items: dict[str, dict]) -> None:
    columns = ["item_id", "comparison_group", "mode", "answer_kind", "response_class", "model_id",
               "question", "reference_answer", "answer", "rubric", "critical_error", "critical_error_override", "maximum_points", "human_score",
               "human_notes", "required_fact_recall_at_k", "citation_membership_diagnostic"]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        for record in records:
            item = items[record["item_id"]]
            writer.writerow({key: safe_csv(value) for key, value in {
                "item_id": record["item_id"], "comparison_group": record["comparison_group"],
                "mode": record["mode"], "answer_kind": record["answer_kind"],
                "response_class": record["response_class"], "model_id": record.get("model_id"),
                "question": item["question_en"], "reference_answer": item["reference_answer_en"],
                "answer": record.get("answer"),
                "rubric": " | ".join(f"{x['points']}: {x['criterion']}" for x in item["scoring"]["criteria"]),
                "critical_error": item["scoring"].get("critical_error"),
                "critical_error_override": item["scoring"].get("critical_error_override"),
                "maximum_points": item["scoring"]["maximum_points"], "human_score": None, "human_notes": None,
                "required_fact_recall_at_k": record["retrieval_diagnostic"]["required_fact_recall_at_k"],
                "citation_membership_diagnostic": record["retrieval_diagnostic"]["citation_ids_all_supplied"],
            }.items()})


def run(args: argparse.Namespace) -> int:
    base_url = local_api_url(args.base_url)
    dataset_path = args.dataset.resolve()
    dataset = json.loads(dataset_path.read_text())
    if dataset.get("retrieval_use") is not False or dataset.get("final_test_set"):
        raise ValueError("Use the development protocol, kept outside retrieval and final testing.")
    available = dataset.get("items") or []
    if not available or args.limit is not None and not 1 <= args.limit <= len(available):
        raise ValueError("--limit must select at least one and at most the available number of questions.")
    selected = available[:args.limit] if args.limit is not None else available
    if len({q["item_id"] for q in selected}) != len(selected):
        raise ValueError("Development item IDs must be unique.")
    timeout = httpx.Timeout(args.timeout, connect=min(10.0, args.timeout))
    with httpx.Client(timeout=timeout, follow_redirects=False, trust_env=False) as client:
        try:
            response = client.get(base_url + "/api/status")
            response.raise_for_status()
            before = response.json()
            check_preflight(before, dataset)
        except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
            print(json.dumps({"status": "unavailable", "reason": str(exc), "run_created": False}))
            return 2

        run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%S.%fZ")
        output = args.output.resolve() if args.output else ROOT / "evaluation/runs" / run_id
        check_output(output)
        output.mkdir(parents=True, exist_ok=True)
        order = [
            {"item_id": item["item_id"], "mode": mode}
            for index, item in enumerate(selected)
            for mode in (("rag", "baseline") if index % 2 == 0 else ("baseline", "rag"))
        ]
        item_map = {q["item_id"]: q for q in selected}
        started = utc_now()
        manifest = {
            "run_id": run_id, "started_at_utc": started, "finished_at_utc": None,
            "status": "RUNNING", "run_type": "SMOKE" if len(selected) < len(available) else "DEVELOPMENT",
            "dataset_id": dataset.get("dataset_id"), "dataset_sha256": digest(dataset_path),
            "release_id": before["release_id"], "script_sha256": digest(Path(__file__)),
            "base_url": base_url, "request_timeout_seconds": args.timeout,
            "request_parameters": {"reference_id": None, "top_k": 3},
            "full_dataset_item_count": len(available), "selected_item_ids": list(item_map),
            "planned_response_count": len(order), "execution_order": order,
            "order_policy": "Paired per question, alternating which condition goes first; all calls sequential.",
            "preflight": status_snapshot(before), "postflight": None,
            "runner_environment_observation": environment_observation(),
            "model_identifier": before["model"]["model_id"], "quantization": None,
            "scope_and_configuration_note": "Both arms use the same configured local model and decoding settings. The model-only control receives the user question without reviewed evidence or document rules. The RAG system also has retrieval, evidence checks and structured answer paths. Runner environment is not proof of server-effective configuration; prefer server-reported settings.",
            "old_executable_flag_note": "False flags in the prepared dataset describe an unperformed implementation preflight. The user's local development request authorizes this genuine configured-model run.",
            "metrics": {"human_score": None, "answer_accuracy": None, "citation_support_correctness": None},
            "scoring_plan_basis": "Maximum points apply per condition; no cross-condition combined answer accuracy is computed.",
            "model_gain_claim": None,
            "limitations": ["Development material, not an unseen final test.", "Scope/policy responses are pipeline behavior, not LLM generation or retrieval superiority.", "Citation-ID membership is not claim-support correctness."],
        }
        if not manifest["preflight"]["generation_config"]:
            manifest["limitations"].append("The server did not report effective generation settings; configuration equivalence is not independently established by client env observations.")
        write_json(output / "manifest.json", manifest)
        records = []
        interrupted = False
        fatal_error = None
        try:
            with (output / "responses.jsonl").open("w", encoding="utf-8") as handle:
                for sequence, call in enumerate(order, 1):
                    item = item_map[call["item_id"]]
                    body = {"question": item["question_en"], "mode": call["mode"], "reference_id": None, "top_k": 3}
                    begun = utc_now()
                    clock = time.perf_counter()
                    error = None
                    http_status = None
                    try:
                        response = client.post(base_url + "/api/ask", json=body)
                        http_status = response.status_code
                        response.raise_for_status()
                        payload = response.json()
                        if not isinstance(payload, dict) or not isinstance(payload.get("answer"), str):
                            raise ValueError("The API response lacks a text answer.")
                    except (httpx.HTTPError, ValueError, TypeError) as exc:
                        error = {"type": type(exc).__name__, "message": str(exc)}
                        payload = {"answer": "", "answer_kind": "error", "mode": call["mode"], "evidence": []}
                    kind = payload.get("answer_kind", "unknown")
                    classification = {"llm": "MODEL_RESPONSE", "scope_limit": "PIPELINE_POLICY_RESPONSE",
                                      "evidence_preview": "PREVIEW_NOT_MODEL", "error": "MISSING_OR_FAILED_RESPONSE"}.get(kind, "UNKNOWN_RESPONSE")
                    inconsistencies = []
                    if payload.get("release_id") not in {None, before["release_id"]}:
                        inconsistencies.append("Response release differs from preflight.")
                    if kind == "llm" and payload.get("model_id") != before["model"]["model_id"]:
                        inconsistencies.append("Generated response model differs from preflight.")
                    record = {
                        "run_id": run_id, "item_id": item["item_id"], "sequence": sequence,
                        "comparison_group": item.get("comparison_group", item.get("score_group")),
                        "mode": call["mode"], "request": body, "started_at_utc": begun,
                        "finished_at_utc": utc_now(), "client_latency_ms": round((time.perf_counter() - clock) * 1000),
                        "http_status": http_status, "answer": payload.get("answer", ""), "answer_kind": kind,
                        "response_class": classification, "model_id": payload.get("model_id"),
                        "actual_llm_response": kind == "llm", "pipeline_policy_response": kind == "scope_limit",
                        "eligible_for_llm_gain_claim": kind == "llm" and item.get("comparison_group") == "FACTUAL" and not inconsistencies,
                        "error": error, "consistency_errors": inconsistencies,
                        "retrieval_diagnostic": diagnostic(item, call["mode"], payload),
                        "human_score": None, "human_notes": None, "api_response": payload,
                    }
                    records.append(record)
                    handle.write(json.dumps(record, ensure_ascii=False, allow_nan=False) + "\n")
                    handle.flush()
                    print(f"{sequence}/{len(order)} {item['item_id']} {call['mode']}: {classification}", flush=True)
        except KeyboardInterrupt:
            interrupted = True
        except Exception as exc:
            fatal_error = {"type": type(exc).__name__, "message": str(exc)}
        finally:
            try:
                final = client.get(base_url + "/api/status", timeout=min(15.0, args.timeout))
                final.raise_for_status()
                manifest["postflight"] = status_snapshot(final.json())
            except (httpx.HTTPError, ValueError, TypeError) as exc:
                manifest["postflight_error"] = {"type": type(exc).__name__, "message": str(exc)}
            except KeyboardInterrupt:
                interrupted = True
                manifest["postflight_error"] = {"type": "KeyboardInterrupt", "message": "Postflight interrupted."}
            failures = [r for r in records if r["error"] or r["consistency_errors"] or
                        r["answer_kind"] not in {"llm", "scope_limit"} or
                        r["comparison_group"] == "FACTUAL" and r["answer_kind"] != "llm"]
            config_drift = []
            after = manifest.get("postflight")
            if after:
                for path, old, new in [
                    ("release_id", before["release_id"], after["release_id"]),
                    ("model_id", before["model"]["model_id"], after["model"]["model_id"]),
                    ("embedding.mode", before["embedding"]["mode"], after["embedding"]["mode"]),
                    ("index.fingerprint", before["index"]["fingerprint"], after["index"]["fingerprint"]),
                    ("generation_config", manifest["preflight"]["generation_config"], after["generation_config"]),
                ]:
                    if old != new:
                        config_drift.append(path)
            manifest.update({
                "finished_at_utc": utc_now(),
                "status": "INTERRUPTED" if interrupted else "INCOMPLETE" if failures or len(records) != len(order) or config_drift or fatal_error or manifest.get("postflight_error") else "COLLECTED_AWAITING_HUMAN_GRADING",
                "response_count": len(records), "actual_llm_response_count": sum(r["actual_llm_response"] for r in records),
                "pipeline_policy_response_count": sum(r["pipeline_policy_response"] for r in records),
                "failed_or_non_llm_factual_response_count": len(failures), "configuration_drift": config_drift,
                "answer_kind_counts": {kind: sum(r["answer_kind"] == kind for r in records) for kind in sorted({r["answer_kind"] for r in records})},
                "human_grading_status": "PENDING", "all_human_scores": None,
                "fatal_error": fatal_error,
                "group_scoring_plan": {group: {"item_count": sum(q.get("comparison_group") == group for q in selected),
                    "maximum_points": sum(q["scoring"]["maximum_points"] for q in selected if q.get("comparison_group") == group)}
                    for group in ("FACTUAL", "BOUNDARY")},
            })
            write_grading(output / "grading.csv", records, item_map)
            manifest["files"] = {name: {"sha256": digest(output / name), "bytes": (output / name).stat().st_size}
                                 for name in ("responses.jsonl", "grading.csv")}
            write_json(output / "manifest.json", manifest)
        print(json.dumps({"status": manifest["status"], "output": str(output), "responses": len(records), "human_scores": None}))
        return 130 if interrupted else 1 if manifest["status"] == "INCOMPLETE" else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8765")
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--output", type=Path, help="New run directory; defaults to evaluation/runs/<UTC timestamp>.")
    parser.add_argument("--limit", type=int, help="Select the first N questions for a paired smoke run.")
    parser.add_argument("--timeout", type=float, default=150.0, help="HTTP request timeout in seconds (default: 150).")
    args = parser.parse_args()
    if args.timeout <= 0:
        parser.error("--timeout must be positive.")
    try:
        return run(args)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(json.dumps({"status": "unavailable", "reason": str(exc), "run_created": False}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
