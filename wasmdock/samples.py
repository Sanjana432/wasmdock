from pathlib import Path

PLUGIN_DIR = Path(__file__).resolve().parents[1]/"plugins"
CATALOG = [
    ("uppercase", "Uppercase text", "A real WASI stdin → ASCII uppercase → stdout transformation.", "Hello WasmDock!\nworker isolation, real execution.\n"),
    ("csv-column", "CSV first column", "Extract the first column of simple, unquoted CSV rows inside WebAssembly.", "name,team,score\nMaya,platform,91\nRavi,systems,88\n"),
    ("infinite-loop", "Fuel exhaustion", "An endless guest loop is stopped by the configured fuel budget.", ""),
    ("memory-grow", "Memory growth limit", "The guest attempts to grow beyond its linear-memory allocation.", ""),
    ("workspace-read", "File capability check", "Read /workspace/note.txt only when the read-only workspace is granted.", ""),
    ("output-flood", "Output budget", "A guest writes repeatedly; captured output remains bounded.", ""),
]


def list_samples():
    return [{"id": key, "name": name, "description": description, "default_stdin": stdin,
             "wat": (PLUGIN_DIR/f"{key}.wat").read_text(encoding="utf-8")} for key, name, description, stdin in CATALOG]


def sample_wat(sample_id):
    if sample_id not in {row[0] for row in CATALOG}:
        raise ValueError("Unknown sample ID.")
    return (PLUGIN_DIR/f"{sample_id}.wat").read_text(encoding="utf-8")
