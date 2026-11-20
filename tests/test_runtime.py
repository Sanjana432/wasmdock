import base64
import unittest
import wasmtime
from pydantic import ValidationError
from wasmdock.models import JobSpec
from wasmdock.runtime import execute
from wasmdock.samples import list_samples, sample_wat


class RuntimeTests(unittest.TestCase):
    def test_text_transform_runs_actual_wasm(self):
        result = execute(JobSpec(sample_id="uppercase", stdin="Hello, Rust & Wasm!\n"))
        self.assertEqual(result["status"], "succeeded")
        self.assertEqual(result["output"], "HELLO, RUST & WASM!\n")
        self.assertGreater(result["metrics"]["fuel_consumed"], 0)

    def test_csv_transform(self):
        result = execute(JobSpec(sample_id="csv-column", stdin="name,team\r\nMaya,infra\nRavi,systems"))
        self.assertEqual(result["output"], "name\nMaya\nRavi")

    def test_loop_exhausts_fuel(self):
        result = execute(JobSpec(sample_id="infinite-loop", fuel=20_000))
        self.assertEqual(result["reason"], "fuel_exhausted")
        self.assertEqual(result["metrics"]["fuel_consumed"], 20_000)

    def test_file_access_requires_explicit_capability(self):
        denied = execute(JobSpec(sample_id="workspace-read"))
        granted = execute(JobSpec(sample_id="workspace-read", workspace=True), "beta")
        self.assertEqual(denied["exit_code"], 77)
        self.assertIn("DENIED", denied["output"])
        self.assertEqual(granted["status"], "succeeded")
        self.assertEqual(granted["output"], "Read-only workspace granted to tenant beta.\n")

    def test_memory_grow_is_refused(self):
        result = execute(JobSpec(sample_id="memory-grow", memory_mb=1))
        self.assertEqual(result["exit_code"], 78)
        self.assertIn("memory.grow exceeded", result["output"])
        self.assertEqual(result["metrics"]["memory_bytes"], 65_536)

    def test_granted_directory_remains_read_only(self):
        # WASI FD_WRITE is64. The same existing file can be opened for read but not write.
        wat = sample_wat("workspace-read").replace("(i64.const 2)", "(i64.const 64)")
        result = execute(JobSpec(wat=wat, workspace=True))
        self.assertEqual(result["exit_code"], 77)

    def test_epoch_interrupts_guest_host_call_loop(self):
        result = execute(JobSpec(sample_id="output-flood", fuel=50_000_000, timeout_ms=100, output_limit=128))
        self.assertTrue(any("timeout" in event for event in result["events"]))
        self.assertLess(result["metrics"]["fuel_consumed"], 50_000_000)

    def test_oversized_initial_memory_is_rejected(self):
        result = execute(JobSpec(wat='(module (memory (export "memory") 512) (func (export "_start")))', memory_mb=1))
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["reason"], "memory_limit")

    def test_output_is_bounded(self):
        result = execute(JobSpec(sample_id="output-flood", output_limit=128, fuel=20_000))
        self.assertEqual(result["reason"], "output_limit")
        self.assertLessEqual(result["metrics"]["output_bytes"], 128)

    def test_imports_cannot_create_host_network_functions(self):
        result = execute(JobSpec(wat='(module (import "env" "network" (func)) (func (export "_start")))'))
        self.assertEqual(result["reason"], "invalid_module")
        self.assertIn("Only WASI Preview 1", result["error"])

    def test_binary_plugin_is_supported(self):
        binary = bytes(wasmtime.wat2wasm(sample_wat("uppercase")))
        result = execute(JobSpec(wasm_base64=base64.b64encode(binary).decode(), stdin="binary"))
        self.assertEqual(result["output"], "BINARY")

    def test_invalid_module_is_inspectable(self):
        self.assertEqual(execute(JobSpec(wat="(module broken)"))["reason"], "invalid_module")
        self.assertEqual(execute(JobSpec(wat="(module)"))["reason"], "invalid_module")

    def test_budget_and_input_validation(self):
        for payload in ({}, {"wat":"(module)", "sample_id":"uppercase"}, {"sample_id":"uppercase", "fuel":0},
                        {"sample_id":"uppercase", "memory_mb":100}, {"sample_id":"uppercase", "stdin":"界"*16_384},
                        {"wasm_base64":"not-base64!"}, {"wat":"(module)","unexpected":1}):
            with self.subTest(payload=str(payload)[:100]), self.assertRaises(ValidationError):
                JobSpec(**payload)

    def test_all_sample_sources_compile(self):
        for sample in list_samples():
            with self.subTest(sample=sample["id"]):
                self.assertTrue(wasmtime.wat2wasm(sample["wat"]))


if __name__ == "__main__":
    unittest.main()
