(module
  (import "wasi_snapshot_preview1" "fd_write" (func $write (param i32 i32 i32 i32) (result i32)))
  (import "wasi_snapshot_preview1" "proc_exit" (func $exit (param i32)))
  (memory (export "memory") 1)
  (data (i32.const 64) "DENIED: memory.grow exceeded the configured limit.\n")
  (data (i32.const 128) "Memory growth succeeded.\n")
  (func (export "_start")
    (if (i32.eq (memory.grow (i32.const 1024)) (i32.const -1))
      (then
        (i32.store (i32.const 0) (i32.const 64))
        (i32.store (i32.const 4) (i32.const 51))
        (drop (call $write (i32.const 1) (i32.const 0) (i32.const 1) (i32.const 24)))
        (call $exit (i32.const 78)))
      (else
        (i32.store (i32.const 0) (i32.const 128))
        (i32.store (i32.const 4) (i32.const 25))
        (drop (call $write (i32.const 1) (i32.const 0) (i32.const 1) (i32.const 24)))))))
