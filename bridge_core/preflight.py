"""Preflight dependency verification for desk-audio-bridge."""

import sys
from typing import Tuple


def check_runtime_dependencies() -> Tuple[bool, str]:
    """Verifies all required runtime libraries are installed and importable."""
    try:
        import psutil
    except ImportError:
        return (
            False,
            "Missing required runtime dependency 'psutil'. Please install dependencies using: pip install -r requirements.txt",
        )

    return True, "All dependencies satisfied"
