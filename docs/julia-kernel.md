# The Julia kernel

`src/jutul_agent/juliakernel/` supervises one Julia process per session and
gives the agent a persistent REPL: state, loaded packages, and compiled
methods survive across turns. It is a standalone package: the Python side
imports nothing from the rest of jutul-agent, and the Julia server
(`server.jl`) uses only the standard library, so the simulator envs need no
agent-specific dependency.

## Why a custom kernel

The agent needs four things together: live streaming of output while a
solve runs, cooperative interrupts that do not kill the session, a
structured result per evaluation (ok, error, or interrupted, separate from
whatever was printed), and a process the supervisor can cheaply restart.
General-purpose kernels (Jupyter/IJulia) bring a protocol and dependency
footprint into every simulator env, while subprocess-per-eval loses all
state and pays a full compile each time. The kernel is the small middle:
one process, one socket, one protocol.

## Protocol

Python launches `julia server.jl <port>` with a token in the environment and
accepts one loopback TCP connection. Everything on it is a length-prefixed
frame, an ASCII header line followed by exactly that many payload bytes:

```
Julia -> Python   RDY <token> 0           handshake
                  OUT <stream> <n>        live stdout/stderr bytes
                  RES <id> <status> <n>   one result per eval (ok | err | int)
Python -> Julia   EXE <id> <n>            code to evaluate
```

No payload travels as a bare line, so frames are binary-safe and
unbounded: a multi-megabyte error message needs no special casing.

Output capture is at the file-descriptor level: the server redirects fd 1
and 2 into in-process pipes, so prints from C and Fortran libraries inside
the solvers are captured, not just Julia's own. Pump tasks forward the
bytes as `OUT` frames as they appear, which is what makes progress bars
stream live into the TUI.

Ordering comes from TCP itself. After each eval the server flushes both
streams (including C stdio buffers), writes an in-process marker, and sends
`RES` only after the pumps have forwarded everything before the marker. The
parent therefore never stitches streams back together: by the time it sees
a result, all of that eval's output has already arrived. The Python side
stays small: one reader task and one pending future per eval
(`connection.py`).

## Interrupts and threading

`interrupt()` sends SIGINT, which Julia delivers to the running eval as an
`InterruptException`, so a stuck simulation cancels while the session and
its loaded state survive. Two details make this reliable:

- The kernel always launches with an interactive thread (`--threads N,1`).
  That pins the eval loop to one thread while the output pumps run on the
  default pool. Julia delivers the interrupt on the root task's thread, and
  a pump sharing that thread could swallow it inside one of its own
  uninterruptible windows.
- The result handoff runs with interrupts deferred, so a late Ctrl+C cannot
  tear an eval's output apart from its result frame.

A pure no-allocation spin (`while true; end`) is uninterruptible on any
Julia configuration. If an interrupt cannot recover the eval within a
timeout, the supervisor restarts the process and reports whether session
state was preserved.

## Lifecycle and limits

- Reset is restart by design: Julia cannot unload code, so `reset_julia`
  always starts a fresh process. The precompile caches and warm packages
  make that cheap (see [adding a simulator](adding-a-simulator.md)).
- A user's `include("file.jl")` is rewritten to resolve from the workspace
  (the process working directory) rather than from the server script's own
  directory, which is where Julia would otherwise look.
- Result payloads are capped (64 KiB) so a pathological error message
  cannot balloon a frame. Streamed output has no cap.
- If the process dies, every waiter fails fast with the reason the
  connection saw, and the startup log (`julia-startup.log` in the session
  directory) keeps Julia's own boot errors.
- GLMakie needs a display even headless, so the session starts a private
  Xvfb and passes it through `DISPLAY` (never `xvfb-run`, which would merge
  the process's stdout and stderr).
