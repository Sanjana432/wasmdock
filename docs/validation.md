# Validation record

Development environment: Windows 11, Python 3.12.14, Wasmtime 50.0.1, FastAPI 0.165.0. The committed benchmark JSON records the exact execution timestamp and platform.

**23 tests passed.** The controlled-shutdown regression verifies that pending jobs are marked interrupted, are not executed during shutdown, and cannot be submitted after closure. The active job is allowed to finish.

Browser verification exercised a successful text transformation, an infinite-loop fuel trap and a denied file capability. Desktop and 390-pixel mobile layouts were checked; captured previews are included in this directory.

The automated suite runs real Wasmtime guests, including stdin transformations, binary module loading, fuel exhaustion, epoch interruption, initial-memory rejection, refused memory growth, bounded stdout, no ungranted filesystem access and read-only directory grants. Scheduler tests start actual child processes and cover persisted results, cross-tenant lookup, queue admission and dispatch fairness. API tests use the application’s real lifespan and scheduler.

The benchmark captures 12 fresh-engine direct executions and 12 child-process jobs across two tenants. A process-per-job design deliberately pays interpreter and compilation costs. Queue timings include waiting behind other jobs. The measurements are small-sample observations on one development computer, with no claim about production throughput or multi-machine scalability.

Native OS memory limits and container execution were not validated locally. The optional Compose configuration includes container-wide resource limits, but these do not imply per-job OS limits. The guest Store cap, epoch/fuel behavior and API partitioning are directly tested.

GitHub Actions runs the suite on Windows and Linux and records a fresh three-run benchmark artifact. Its status is available on the repository’s Actions page.
