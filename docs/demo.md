# Interview walkthrough

Start with the product: users want to run a small transformation without granting it the entire host environment. Show the source editor and point out that every supplied example is genuine WAT, compiled and executed by Wasmtime.

1. **Useful workload:** run CSV first-column extraction. Change the input and demonstrate that the guest computes a new result.
2. **Bounded computation:** run the infinite loop with 50,000 fuel. Show the trap and explain why fuel differs from elapsed time.
3. **Explicit authority:** run the file capability sample with the workspace disabled. Its real WASI `path_open` fails. Enable the read-only synthetic workspace and rerun. Show the different output and recorded grant.
4. **Memory refusal:** run memory growth with 1 MiB. The guest’s attempted 64 MiB growth fails; the guest reports that result and exits 78.
5. **Output backpressure:** run output flood with a256byte output budget. Capture stops growing and the job is marked `output_limit`.
6. **Tenant scheduling:** queue alpha work, switch to beta and submit a healthy job. Discuss one-running-job-per-tenant policy and why throughput can be lower when only one tenant is active.
7. **Recovery semantics:** restart the server. Completed metadata persists; interrupted jobs are explicitly failed. Explain why this avoids falsely claiming durable job execution.

## Discussion prompts

- Why does guest linear memory differ from process RSS?
- Which failures can fuel stop, and which require a hard process deadline?
- What host functions could accidentally weaken the WASI capability model?
- How would authentication and OS process limits change a public deployment?
- How would you compare fresh-process isolation with a warm-worker pool?
- What additional work is needed for durable queuing and horizontal scaling?
