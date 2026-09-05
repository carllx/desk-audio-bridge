"""Process runner and ownership supervisor for Windows.

Enforces strict process ownership using Windows Job Objects:
- Any spawned pipeline child is assigned to a dedicated Job Object configured with
  JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE.
- Only project-owned children are tracked and terminated.
- Does NOT perform global/broad process kills by name.
"""

import ctypes
from ctypes import wintypes
import logging
import subprocess
from typing import List, Optional

logger = logging.getLogger(__name__)

JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
JobObjectExtendedLimitInformation = 9


class IO_COUNTERS(ctypes.Structure):
    _fields_ = [
        ("ReadOperationCount", ctypes.c_uint64),
        ("WriteOperationCount", ctypes.c_uint64),
        ("OtherOperationCount", ctypes.c_uint64),
        ("ReadTransferCount", ctypes.c_uint64),
        ("WriteTransferCount", ctypes.c_uint64),
        ("OtherTransferCount", ctypes.c_uint64),
    ]


class JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("PerProcessUserTimeLimit", ctypes.c_int64),
        ("PerJobUserTimeLimit", ctypes.c_int64),
        ("LimitFlags", wintypes.DWORD),
        ("MinimumWorkingSetSize", ctypes.c_size_t),
        ("MaximumWorkingSetSize", ctypes.c_size_t),
        ("ActiveProcessLimit", wintypes.DWORD),
        ("Affinity", ctypes.c_size_t),
        ("PriorityClass", wintypes.DWORD),
        ("SchedulingClass", wintypes.DWORD),
    ]


class JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("BasicLimitInformation", JOBOBJECT_BASIC_LIMIT_INFORMATION),
        ("IoInfo", IO_COUNTERS),
        ("ProcessMemoryLimit", ctypes.c_size_t),
        ("JobMemoryLimit", ctypes.c_size_t),
        ("PeakProcessMemoryLimit", ctypes.c_size_t),
        ("PeakJobMemoryLimit", ctypes.c_size_t),
    ]


from bridge_core.process_runner import ProcessRunner


class WindowsOwnedProcessRunner(ProcessRunner):
    """Windows-specific owned process supervisor backed by a Job Object."""

    def __init__(self):
        self._kernel32 = ctypes.windll.kernel32
        self._job = self._create_kill_on_close_job()
        self._owned_processes: dict[int, subprocess.Popen] = {}

    def _create_kill_on_close_job(self) -> wintypes.HANDLE:
        h_job = self._kernel32.CreateJobObjectW(None, None)
        if not h_job:
            logger.warning("Could not create Windows Job Object")
            return None

        info = JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
        info.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        res = self._kernel32.SetInformationJobObject(
            h_job,
            JobObjectExtendedLimitInformation,
            ctypes.byref(info),
            ctypes.sizeof(info),
        )
        if not res:
            logger.warning("Failed to SetInformationJobObject on Job Object")
        return h_job

    def start_process(self, cmd: List[str]) -> int:
        """Starts a child process and assigns it to the owned Job Object."""
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        pid = proc.pid
        self._owned_processes[pid] = proc

        if self._job:
            # Assign process to job
            h_proc = self._kernel32.OpenProcess(0x1F0FFF, False, pid)
            if h_proc:
                self._kernel32.AssignProcessToJobObject(self._job, h_proc)
                self._kernel32.CloseHandle(h_proc)

        logger.info("Started owned child process [PID %d]: %s", pid, cmd[0])
        return pid

    def stop_process(self, pid: int) -> None:
        """Stops ONLY the specific owned process by PID."""
        proc = self._owned_processes.pop(pid, None)
        if proc:
            try:
                proc.terminate()
                proc.wait(timeout=2.0)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass
            logger.info("Stopped owned child process [PID %d]", pid)
        else:
            logger.debug("PID %d is not in owned processes map", pid)

    def is_running(self, pid: int) -> bool:
        """Checks whether the owned process is still running."""
        proc = self._owned_processes.get(pid)
        if not proc:
            return False
        return proc.poll() is None

    def stop_all_owned(self) -> None:
        """Stops all processes owned by this controller instance."""
        pids = list(self._owned_processes.keys())
        for pid in pids:
            self.stop_process(pid)

    def __del__(self):
        self.stop_all_owned()
        if self._job:
            try:
                self._kernel32.CloseHandle(self._job)
            except Exception:
                pass
