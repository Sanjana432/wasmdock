import argparse
import json
from .models import JobSpec
from .runtime import execute
from .samples import list_samples


def main():
    parser = argparse.ArgumentParser(description="Run WasmDock locally or execute a sample.")
    parser.add_argument("command", choices=["serve", "demo"])
    parser.add_argument("--port", type=int, default=8020)
    args = parser.parse_args()
    if args.command == "serve":
        import uvicorn
        uvicorn.run("wasmdock.app:app", host="127.0.0.1", port=args.port)
    else:
        for sample in list_samples():
            result = execute(JobSpec(sample_id=sample["id"], stdin=sample["default_stdin"], output_limit=256))
            result["output"] = result["output"][:120]
            print(json.dumps({"sample":sample["id"], **result}, ensure_ascii=True))


if __name__ == "__main__":
    main()
