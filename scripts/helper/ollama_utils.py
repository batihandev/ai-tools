#!/usr/bin/env python3
"""
Shared helpers for talking to a local Ollama instance.

- resolve_ollama_url: respects OLLAMA_URL, and in WSL can rewrite localhost
  to the Windows host IP (unless disabled via env var).
"""

from __future__ import annotations

import os
import subprocess
from typing import Optional


def detect_windows_host_ip() -> Optional[str]:
    """
    Best-effort detection of the Windows host IP when running inside WSL2.

    Strategy:
      1. Use `ip route show default` and take the 'via' address (default gateway).
      2. Fallback to nameserver from /etc/resolv.conf, but avoid obvious bogus ones.
    """
    # 1) Try default route: `default via X dev eth0`
    try:
        out = subprocess.check_output(
            ["ip", "route", "show", "default"],
            text=True,
            stderr=subprocess.DEVNULL,
        )
        parts = out.split()
        if "via" in parts:
            idx = parts.index("via")
            if idx + 1 < len(parts):
                gw = parts[idx + 1]
                if gw and gw != "0.0.0.0":
                    return gw
    except Exception:
        pass

    # 2) Fallback: first nameserver in /etc/resolv.conf, but skip known-bad ones
    try:
        with open("/etc/resolv.conf", "r") as f:
            for line in f:
                if line.startswith("nameserver"):
                    parts = line.split()
                    if len(parts) == 2:
                        ip = parts[1]
                        if ip.startswith("127.") or ip == "10.255.255.254":
                            continue
                        return ip
    except Exception:
        pass

    return None


def _running_in_wsl() -> bool:
    try:
        with open("/proc/version") as f:
            return "microsoft" in f.read().lower()
    except Exception:
        return False


def resolve_ollama_url(default_url: str) -> str:
    """
    Resolve Ollama URL.

    Priority:
      1. Respect OLLAMA_URL if set.
      2. If inside WSL and default is localhost, rewrite to Windows host IP
         (unless disabled via OLLAMA_SKIP_WSL_IP_DETECT=1).
      3. Otherwise, use default_url unchanged.
    """
    env_url = os.getenv("OLLAMA_URL")
    if env_url:
        return env_url

    url = default_url

    # Only auto-adjust when we would otherwise talk to localhost
    if not url.startswith("http://localhost"):
        return url

    # Allow disabling the WSL host-IP hack if it ever causes trouble
    if os.getenv("OLLAMA_SKIP_WSL_IP_DETECT") == "1":
        return url

    if not _running_in_wsl():
        return url

    host_ip = detect_windows_host_ip()
    if host_ip:
        return f"http://{host_ip}:11434"

    return url
