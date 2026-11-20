"""Shared input contract; all budgets are validated before queuing."""
import base64
from pydantic import BaseModel, ConfigDict, Field, model_validator


class JobSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")
    sample_id: str | None = Field(default=None, max_length=40)
    wat: str | None = Field(default=None, max_length=65_536)
    wasm_base64: str | None = Field(default=None, max_length=90_000)
    stdin: str = Field(default="", max_length=16_384)
    fuel: int = Field(default=1_000_000, ge=1_000, le=50_000_000)
    memory_mb: int = Field(default=16, ge=1, le=64)
    timeout_ms: int = Field(default=2_000, ge=100, le=5_000)
    output_limit: int = Field(default=16_384, ge=128, le=65_536)
    workspace: bool = False

    @model_validator(mode="after")
    def validate_payload(self):
        if sum(value is not None for value in (self.sample_id, self.wat, self.wasm_base64)) != 1:
            raise ValueError("Choose exactly one of sample_id, wat or wasm_base64.")
        if len(self.stdin.encode("utf-8")) > 16_384:
            raise ValueError("stdin exceeds the 16 KiB byte limit.")
        if self.wat is not None and (not self.wat.strip() or len(self.wat.encode("utf-8")) > 65_536):
            raise ValueError("WAT must contain 1–65,536 UTF-8 bytes.")
        if self.wasm_base64 is not None:
            try:
                binary = base64.b64decode(self.wasm_base64, validate=True)
            except (ValueError, TypeError) as exc:
                raise ValueError("wasm_base64 must be valid base64.") from exc
            if not binary.startswith(b"\0asm") or len(binary) > 65_536:
                raise ValueError("Supply a WebAssembly binary of at most 64 KiB.")
        return self
