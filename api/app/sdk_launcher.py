"""Linux exec wrapper: kill SDK when its owning agent dies, including startup races."""
import ctypes
import os
import signal
import sys


def main():
    parent = int(sys.argv[1])
    # prctl(PR_SET_PDEATHSIG): no preexec_fn in the threaded agent.
    if ctypes.CDLL(None, use_errno=True).prctl(1, signal.SIGKILL, 0, 0, 0) != 0:
        raise SystemExit(1)
    if os.getppid() != parent:
        raise SystemExit(1)
    os.execv(sys.argv[2], [sys.argv[2]])


if __name__ == "__main__":
    main()
