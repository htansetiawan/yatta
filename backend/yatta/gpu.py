"""GPU gate: Yatta never competes with Henry's other GPU jobs.

    python -m yatta.gpu foreign    # other projects' GPU processes busy enough to wait for (used by train_avatar.sh)
"""

import os
import subprocess
import sys
import time
from pathlib import Path

from yatta import core
from yatta.config import PACKAGE, settings

# GPU processes started from these trees are Yatta's own (its engines live in the research repository).
OWN_ROOTS = (str(settings.gaussian_talker), str(PACKAGE.parents[1]), str(settings.narrate.parent))
LAST_FOREIGN = 0.0  # time.time() when another project was last seen actually working on the GPU
BUSY_UTILIZATION = 20  # percent; below this, other projects' processes are idle residents (e.g. a model server)
RENDER_MIN_FREE_MIB = 12000
TRAIN_MIN_FREE_MIB = 24000


def status():
    """Utilization, memory and compute processes, each marked as this project's or another one's."""
    result = {"available": False, "utilization": None, "memory_used": None, "memory_total": None, "processes": []}
    try:
        out = subprocess.run(["nvidia-smi", "--query-gpu=name,utilization.gpu,memory.used,memory.total",
                              "--format=csv,noheader,nounits"], capture_output=True, text=True, timeout=20)
        name, util, used, total = [x.strip() for x in out.stdout.strip().splitlines()[0].split(",")]
        result.update(available=True, name=name, utilization=int(util), memory_used=int(used), memory_total=int(total))
        out = subprocess.run(["nvidia-smi", "--query-compute-apps=pid,used_memory", "--format=csv,noheader,nounits"],
                             capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.SubprocessError, ValueError, IndexError):
        return result
    rows = []
    for line in out.stdout.strip().splitlines():
        pid, memory = [x.strip() for x in line.split(",")]
        try:
            cmdline = Path(f"/proc/{pid}/cmdline").read_bytes().replace(b"\0", b" ").decode(errors="replace").strip()
            cwd = os.readlink(f"/proc/{pid}/cwd")
        except OSError:
            cmdline, cwd = "", ""
        rows.append((int(pid), cmdline, cwd, int(memory)))
    foreign = {p[0] for p in core.foreign_processes([(p[0], p[1], p[2]) for p in rows], OWN_ROOTS)}
    result["processes"] = [{"pid": pid, "memory": memory, "own": pid not in foreign, "label": describe(cmdline)}
                           for pid, cmdline, cwd, memory in rows]
    result["foreign_busy"] = bool(foreign) and result["utilization"] >= BUSY_UTILIZATION
    if result["foreign_busy"]:
        global LAST_FOREIGN
        LAST_FOREIGN = time.time()
    return result


def describe(cmdline):
    """Short human label for a GPU process, e.g. 'maestro · train.py'."""
    parts = cmdline.split()
    script = next((p for p in parts if p.endswith(".py")), parts[0] if parts else "process")
    project = next((seg for seg in Path(script).parts if seg not in ("/", "home", "git") and not seg.startswith(".")
                    and seg != Path(script).name and seg != os.environ.get("USER", "")), "")
    return f"{project} · {Path(script).name}" if project else Path(script).name


def foreign_busy(min_free_mib=RENDER_MIN_FREE_MIB, samples=3):
    """Other projects' GPU processes that should make Yatta wait, or [] if it may start.

    Henry does not want Yatta competing with his other GPU jobs, but a resident process that holds a
    little memory at 0 % utilization (an idle model server) is not a job: Yatta starts when
    utilization stays under BUSY_UTILIZATION over a few samples and enough memory is free.
    """
    current = status()
    foreign = [p for p in current["processes"] if not p["own"]]
    if not foreign or not current["available"]:
        return foreign
    utilization = [current["utilization"]]
    for _ in range(samples - 1):
        time.sleep(1)
        utilization.append(status()["utilization"])
    free = current["memory_total"] - current["memory_used"]
    if max(utilization) < BUSY_UTILIZATION and free >= min_free_mib:
        return []
    global LAST_FOREIGN
    LAST_FOREIGN = time.time()
    return foreign


if __name__ == "__main__":
    if sys.argv[1:] == ["foreign"]:
        for process in foreign_busy(TRAIN_MIN_FREE_MIB, samples=5):
            print(process["pid"], process["label"])
    else:
        sys.exit("usage: python -m yatta.gpu foreign")
