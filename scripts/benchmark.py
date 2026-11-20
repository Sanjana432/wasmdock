"""Measure real Wasmtime and process dispatch; never substitute synthetic timings."""
import argparse
from datetime import datetime, timezone
import importlib.metadata
import json
from pathlib import Path
import platform
import statistics
import sys
import tempfile
from time import perf_counter

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from wasmdock.models import JobSpec
from wasmdock.runtime import execute
from wasmdock.scheduler import Scheduler


def summarize(values):
    values = sorted(values)
    return {"min_ms":round(values[0],3), "median_ms":round(statistics.median(values),3),
            "p95_ms":round(values[min(len(values)-1, int(.95*len(values)))],3), "max_ms":round(values[-1],3)}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs", type=int, default=12)
    parser.add_argument("--output", default="docs/benchmark.json")
    args = parser.parse_args()
    if not 3 <= args.runs <= 100:
        parser.error("Use 3–100 measured runs.")
    spec = JobSpec(sample_id="uppercase", stdin="hello wasm\n"*100)
    timings = []
    for _ in range(args.runs):
        result = execute(spec)
        assert result["output"] == spec.stdin.upper()
        timings.append(result["metrics"]["run_ms"])
    with tempfile.TemporaryDirectory() as temp:
        scheduler = Scheduler(Path(temp)/"benchmark.db")
        started = perf_counter()
        jobs = [(tenant,scheduler.submit(tenant,spec)) for i in range(args.runs) for tenant in (["alpha"] if i%2 == 0 else ["beta"])]
        results = [scheduler.wait(tenant,job["id"],timeout=60) for tenant,job in jobs]
        elapsed = perf_counter()-started
        scheduler.close()
    failures = [{"status": r["status"], "reason": r["reason"], "error": r.get("error", ""),
                 "metrics": r.get("metrics", {})} for r in results if r["status"] != "succeeded"]
    if failures:
        path = Path(args.output)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"platform": platform.platform(), "runs": args.runs,
                                    "failures": failures}, indent=2)+"\n", encoding="utf-8", newline="\n")
        raise RuntimeError("Benchmark child execution failed: "+json.dumps(failures))
    checks = {}
    for sample in ("infinite-loop", "memory-grow", "workspace-read", "output-flood"):
        result = execute(JobSpec(sample_id=sample, fuel=50_000, output_limit=256))
        checks[sample] = {"status":result["status"], "reason":result["reason"], "exit_code":result["exit_code"],
                          "run_ms":result["metrics"]["run_ms"], "output_bytes":result["metrics"]["output_bytes"]}
    payload = {"measured_at":datetime.now(timezone.utc).isoformat(), "platform":platform.platform(), "python":platform.python_version(),
               "wasmtime":importlib.metadata.version("wasmtime"), "runs":args.runs,
               "method":"Fresh Engine/Store per execution; all timings include module compilation. Process measurements additionally include Python startup and queue waiting. Small samples are descriptive, not capacity claims.",
               "direct_execution":summarize(timings),
               "child_process":summarize([r["metrics"]["process_ms"] for r in results]),
               "queue_wait":summarize([r["metrics"]["queue_ms"] for r in results]),
               "batch_elapsed_seconds":round(elapsed,3), "batch_jobs_per_second":round(len(results)/elapsed,3),
               "boundary_checks":checks}
    path = Path(args.output)
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(payload,indent=2)+"\n",encoding="utf-8",newline="\n")
    print(json.dumps(payload,indent=2))


if __name__ == "__main__":
    main()
