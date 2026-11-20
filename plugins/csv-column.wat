(module
  (import "wasi_snapshot_preview1" "fd_read" (func $read (param i32 i32 i32 i32) (result i32)))
  (import "wasi_snapshot_preview1" "fd_write" (func $write (param i32 i32 i32 i32) (result i32)))
  (memory (export "memory") 1)
  (func (export "_start") (local $i i32) (local $n i32) (local $out i32) (local $copy i32) (local $c i32)
    (i32.store (i32.const 0) (i32.const 1024))
    (i32.store (i32.const 4) (i32.const 16384))
    (drop (call $read (i32.const 0) (i32.const 0) (i32.const 1) (i32.const 20)))
    (local.set $n (i32.load (i32.const 20)))
    (local.set $copy (i32.const 1))
    (block $end
      (loop $next
        (br_if $end (i32.ge_u (local.get $i) (local.get $n)))
        (local.set $c (i32.load8_u (i32.add (i32.const 1024) (local.get $i))))
        (if (i32.eq (local.get $c) (i32.const 44))
          (then (local.set $copy (i32.const 0)))
          (else
            (if (i32.eq (local.get $c) (i32.const 10))
              (then
                (i32.store8 (i32.add (i32.const 32768) (local.get $out)) (i32.const 10))
                (local.set $out (i32.add (local.get $out) (i32.const 1)))
                (local.set $copy (i32.const 1)))
              (else
                (if (i32.and (local.get $copy) (i32.ne (local.get $c) (i32.const 13)))
                  (then
                    (i32.store8 (i32.add (i32.const 32768) (local.get $out)) (local.get $c))
                    (local.set $out (i32.add (local.get $out) (i32.const 1)))))))))
        (local.set $i (i32.add (local.get $i) (i32.const 1)))
        (br $next)))
    (i32.store (i32.const 0) (i32.const 32768))
    (i32.store (i32.const 4) (local.get $out))
    (drop (call $write (i32.const 1) (i32.const 0) (i32.const 1) (i32.const 24)))))
