"""Real Wasmtime execution. Called in a fresh child process for every queued job."""
import base64
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Timer
from time import perf_counter
import wasmtime
from .models import JobSpec
from .samples import sample_wat


def execute(spec: JobSpec, tenant="alpha") -> dict:
    started = perf_counter()
    config = wasmtime.Config()
    config.consume_fuel = True
    config.epoch_interruption = True
    config.wasm_threads = False
    # A bounded process-per-job lab should not start a compiler pool per guest.
    # The small plugin modules compile serially inside their existing job slot.
    config.parallel_compilation = False
    engine = wasmtime.Engine(config)
    captured, stderr = bytearray(), bytearray()
    output_exceeded = False
    events = ["Fresh Engine and Store created; no environment or host filesystem inherited."]
    result = {"status": "succeeded", "reason": "completed", "error": "", "exit_code": 0}
    store, instance, timer = None, None, None

    def collect(target, chunk):
        nonlocal output_exceeded
        remaining = spec.output_limit - len(captured) - len(stderr)
        if len(chunk) > remaining:
            target.extend(chunk[:max(0, remaining)])
            output_exceeded = True
            # The WASI operation receives an I/O failure; no unbounded sink is used.
            return -1
        target.extend(chunk)
        return len(chunk)

    with TemporaryDirectory(prefix="wasmdock-") as folder:
        work = Path(folder)
        stdin_file = work/"stdin.txt"
        stdin_file.write_bytes(spec.stdin.encode("utf-8"))
        workspace = work/"workspace"
        workspace.mkdir()
        (workspace/"note.txt").write_text(f"Read-only workspace granted to tenant {tenant}.\n", encoding="utf-8", newline="\n")
        try:
            binary = base64.b64decode(spec.wasm_base64) if spec.wasm_base64 is not None else wasmtime.wat2wasm(spec.wat if spec.wat is not None else sample_wat(spec.sample_id))
            module = wasmtime.Module(engine, binary)
            # Only WASI Preview 1 imports are available. No wasi:http or custom network host functions.
            if any(item.module != "wasi_snapshot_preview1" for item in module.imports):
                raise ValueError("Only WASI Preview 1 imports are permitted.")
            store = wasmtime.Store(engine)
            store.set_limits(memory_size=spec.memory_mb*1024*1024, memories=1, instances=1,
                             tables=2, table_elements=10_000)
            store.set_fuel(spec.fuel)
            store.set_epoch_deadline(1)
            wasi = wasmtime.WasiConfig()
            wasi.argv = ["plugin"]
            wasi.env = []
            wasi.stdin_file = str(stdin_file)
            wasi.stdout_custom = lambda chunk: collect(captured, chunk)
            wasi.stderr_custom = lambda chunk: collect(stderr, chunk)
            if spec.workspace:
                wasi.preopen_dir(str(workspace), "/workspace", fs_mutable=False)
                events.append("Granted one read-only directory: /workspace (synthetic per-job data).")
            else:
                events.append("No preopened directory capability granted.")
            store.set_wasi(wasi)
            linker = wasmtime.Linker(engine)
            linker.define_wasi()
            timer = Timer(spec.timeout_ms/1000, engine.increment_epoch)
            timer.daemon = True
            timer.start()
            instance = linker.instantiate(store, module)
            entry = instance.exports(store).get("_start")
            if not isinstance(entry, wasmtime.Func):
                raise ValueError("The module must export a WASI _start function.")
            if entry.type(store).params or entry.type(store).results:
                raise ValueError("_start must have no parameters or results.")
            entry(store)
            events.append("Guest _start returned normally.")
        except wasmtime.ExitTrap as exc:
            if exc.code != 0:
                result.update(status="failed", reason="guest_exit", error=f"Guest exited with code {exc.code}.", exit_code=exc.code)
            events.append(f"Guest called proc_exit({exc.code}).")
        except wasmtime.Trap as exc:
            message = str(exc)
            reason = "fuel_exhausted" if "fuel" in message.lower() else "timeout" if "interrupt" in message.lower() else "guest_trap"
            result.update(status="failed", reason=reason, error=message[:1500])
            events.append(f"Wasmtime trapped execution: {reason}.")
        except wasmtime.WasmtimeError as exc:
            message = str(exc)
            reason = "memory_limit" if "memory" in message.lower() and ("limit" in message.lower() or "minimum" in message.lower()) else "invalid_module"
            result.update(status="failed", reason=reason, error=message[:1500])
            events.append(f"Instantiation or validation failed: {reason}.")
        except (ValueError, TypeError, KeyError) as exc:
            result.update(status="failed", reason="invalid_module", error=str(exc)[:1500])
        finally:
            if timer:
                timer.cancel()
                timer.join()
            remaining = store.get_fuel() if store is not None else spec.fuel
            memory_bytes = 0
            if instance is not None:
                memory = instance.exports(store).get("memory")
                if isinstance(memory, wasmtime.Memory):
                    memory_bytes = memory.data_len(store)
            if output_exceeded:
                result.update(status="failed", reason="output_limit", error="Combined stdout/stderr exceeded the output budget.")
                events.append("Output budget reached; capture was truncated and writes were rejected.")
            result.update(output=captured.decode("utf-8", errors="replace"), stderr=stderr.decode("utf-8", errors="replace"),
                          metrics={"run_ms": round((perf_counter()-started)*1000, 3),
                                   "fuel_consumed": spec.fuel-remaining, "memory_bytes": memory_bytes,
                                   "output_bytes": len(captured)+len(stderr)}, events=events)
            if store is not None:
                store.close()
    return result
