"""Stable names for the host a tool runs on ("windows-x86_64", "macos-aarch64").

Bundled binaries (rlcore, the kit's assemblers) are kept per host under these
names.
"""
from __future__ import annotations

import platform


def normalize_host(system: str | None = None, machine: str | None = None) -> str:
    """Map Python host names to stable manifest host identifiers."""
    system_name = (system or platform.system()).lower()
    machine_name = (machine or platform.machine()).lower()
    architecture = {
        "amd64": "x86_64",
        "x86_64": "x86_64",
        "x64": "x86_64",
        "aarch64": "aarch64",
        "arm64": "aarch64",
        "i386": "x86",
        "i686": "x86",
        "x86": "x86",
    }.get(machine_name, machine_name)
    operating_system = {
        "windows": "windows",
        "linux": "linux",
        "darwin": "macos",
        "freebsd": "freebsd",
    }.get(system_name, system_name)
    return f"{operating_system}-{architecture}"
