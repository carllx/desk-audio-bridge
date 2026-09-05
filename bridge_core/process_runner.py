"""Abstract process runner interface for desk-audio-bridge."""

from typing import List


class ProcessRunner:
    """Abstract interface / base for spawning and supervising owned child processes."""

    def start_process(self, cmd: List[str]) -> int:
        raise NotImplementedError

    def stop_process(self, pid: int) -> None:
        raise NotImplementedError

    def is_running(self, pid: int) -> bool:
        raise NotImplementedError
