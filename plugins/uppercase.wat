(module
  (import "wasi_snapshot_preview1" "fd_read" (func $read (param i32 i32 i32 i32) (result i32)))
  (import "wasi_snapshot_preview1" "fd_write" (func $write (param i32 i32 i32 i32) (result i32)))
  (memory (export "memory") 1)
  (func (export "_start") (local $i i32) (local $n i32) (local $c i32)
    (i32.store (i32.const 0) (i32.const 1024))
    (i32.store (i32.const 4) (i32.const 16384))
    (drop (call $read (i32.const 0) (i32.const 0) (i32.const 1) (i32.const 20)))
    (local.set $n (i32.load (i32.const 20)))
    (block $end
      (loop $next
        (br_if $end (i32.ge_u (local.get $i) (local.get $n)))
        (local.set $c (i32.load8_u (i32.add (i32.const 1024) (local.get $i))))
        (if (i32.and (i32.ge_u (local.get $c) (i32.const 97)) (i32.le_u (local.get $c) (i32.const 122)))
          (then (i32.store8 (i32.add (i32.const 1024) (local.get $i)) (i32.sub (local.get $c) (i32.const 32)))))
        (local.set $i (i32.add (local.get $i) (i32.const 1)))
        (br $next)))
    (i32.store (i32.const 4) (local.get $n))
    (drop (call $write (i32.const 1) (i32.const 0) (i32.const 1) (i32.const 24)))))
