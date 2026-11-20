"""Child-process protocol. stdout contains exactly one bounded JSON response."""
import json
import sys
from .models import JobSpec
from .runtime import execute


def main():
    # The HTTP envelope is capped at 256 KiB; allow JSON escaping/wrapper overhead here.
    payload = json.loads(sys.stdin.buffer.read(524_289))
    result = execute(JobSpec.model_validate(payload["spec"]), payload["tenant"])
    sys.stdout.buffer.write(json.dumps(result, ensure_ascii=True).encode("utf-8"))
    sys.stdout.buffer.flush()


if __name__ == "__main__":
    main()
