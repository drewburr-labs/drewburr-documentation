# minecraft-crucible — Kernel OOM Kills Causing Server Restarts and Inconsistent World Rollbacks

## 2026-08-14 — 8G Java Heap + JVM Overhead Exceeded the 9Gi Pod Limit

### Summary

Players on the Crucible server ("HardCore", Fabric, Minecraft 26.1) reported the server "kicking everyone and restarting" roughly every hour or two during play sessions, with **inconsistent rollbacks**: broken blocks stayed broken while players were teleported back, and a dead player's items appeared duplicated in both a chest and his restored inventory.

Root cause: the kernel OOM killer was SIGKILLing the Minecraft Java process inside the pod. Crafty launches Java with `-Xmx8192M -XX:+AlwaysPreTouch`, which commits the full 8G heap at startup. Adding ~1G of JVM off-heap overhead (GC structures, threads, classes, buffers) plus Crafty Controller itself (~200MB) exceeds the pod's 9Gi memory limit. Under player load the container hit the limit and the kernel killed Java mid-write.

The heap itself was never exhausted — JVM metrics showed heap usage peaking at ~6.9GiB of 8G. This was a container-limit problem, not an undersized heap.

### Why it was invisible in Kubernetes

`kubectl get pods` showed `2/2 Running`, `RESTARTS 0`, no `OOMKilled` status. The container's PID 1 is Crafty Controller (Python), which launches Java as a child. The OOM killer selected only the largest process in the cgroup (Java) — `memory.events` showed `oom_kill 2`, `oom_group_kill 0`. PID 1 survived, so the kubelet saw nothing. Crafty's crash detection then silently relaunched the server, producing the kick-and-restart cycle players saw.

### Why the rollback was inconsistent

Minecraft autosaves chunks, player data, and entity data on independent cadences. SIGKILL cannot be caught, so whatever had flushed most recently survived and everything else reverted to its own last save — blocks and player state rolled back to *different* points in time, and items saved in two places (chest chunk + player NBT) were duplicated.

### Diagnostic signatures

Kernel OOM kill (what we saw):

- `latest.log` truncated mid-chat-message — no "Stopping server", no save messages, no exception
- Empty `crash-reports/` directory
- `oom_kill` counter incremented in the container's `/sys/fs/cgroup/memory.events`
- `container_memory_working_set_bytes` pinned at the 9Gi limit (~8.94–8.98GiB) for the whole session, with dips at each kill
- Only ~30s of "Can't keep up!" lag before death

A JVM heap OOM would instead have shown `java.lang.OutOfMemoryError` with a stack trace in the log, a crash report file, and minutes of ZGC `Allocation Stall` warnings / escalating lag beforehand. None were present.

### Timeline (2026-08-14, server local time)

| Time | Event |
|---|---|
| ~16:5x | Play session starts; working set climbs to ~8.9GiB and pins at the 9Gi limit |
| 17:48 | First kernel OOM kill — log truncated mid-chat; Crafty relaunches server |
| 18:02 | Second OOM kill, ~30s after "Running 72 ticks behind" warning |
| 19:47 | Session ends with a clean stop (full chunk save logged) |
| ~21:30 | Diagnosis: `oom_kill 2` in cgroup, heap metrics confirm heap never exhausted |
| ~22:00 | `k8s/minecraft-crucible/values.yaml` memory request/limit raised 9Gi → 10Gi (commit `1f65606`), synced via ArgoCD; pod recreated with 10Gi while server was stopped |

### Remediation

Raised the pod memory request/limit from **9Gi to 10Gi**, giving the committed 8G heap + off-heap overhead + Crafty ~2Gi of headroom. Heap (`-Xmx8192M`, set in Crafty's DB, not in the repo) was left unchanged since observed peak heap usage (~6.9GiB) fits comfortably.

### Verification / follow-up

After the next play session:

- `kubectl -n minecraft-crucible exec minecraft-crucible-craftycontroller-0 -c craftycontroller -- grep oom_kill /sys/fs/cgroup/memory.events` should remain `oom_kill 0`
- Working set should plateau around ~9.3GiB, below the 10Gi limit
- If heap usage grows toward 8G (more players/mods), raise the pod limit before raising `Xmx` — keep ~2Gi between `Xmx` and the pod limit

### Lessons

- Supervisor-style containers (Crafty as PID 1) hide child-process OOM kills from Kubernetes entirely — check `memory.events` in the cgroup, not just pod restarts.
- `-XX:+AlwaysPreTouch` makes working-set metrics useless for judging real heap need; use the JVM exporter's `jvm_memory_bytes_used{area="heap"}` instead.
- Size pod limits as `Xmx` + ~1.5–2Gi for JVM overhead and the supervisor, not `Xmx` + 1Gi.
- Inconsistent world rollback (blocks vs players desynced, item dupes) is the signature of an uncaught SIGKILL, not world corruption.
