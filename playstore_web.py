#!/usr/bin/env python3
"""
Play Store — Codespaces / web variant.

GitHub Codespaces containers do not have a display, and in practice do not
expose /dev/kvm (the same underlying Azure VM infrastructure that GitHub's
own hosted Actions runners use, which GitHub and Google's own tooling docs
both confirm lacks nested virtualization). So this variant differs from the
Crostini desktop app in two ways:

  1. It renders the emulator into a virtual framebuffer (Xvfb) instead of a
     real window, and streams that framebuffer to your browser over noVNC
     so you can see and click on the Android screen through the forwarded
     port.
  2. It forces software rendering (-gpu swiftshader_indirect) and software
     CPU emulation (-accel off), since there is no GPU passthrough and no
     KVM available. This makes it noticeably slower than the same AVD would
     be on real hardware with acceleration — that's an inherent limit of
     the Codespaces environment, not something this script can work around.

Everything else — SDK install, AVD creation/reuse, boot detection, opening
Google Play — is the exact same code path as the Crostini desktop app,
imported from playstore.py so the two variants can't drift apart.
"""

import os
import sys
import time
import subprocess
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import playstore  # noqa: E402  (import after sys.path fix-up)

DISPLAY_NUM = ":99"
VNC_PORT = 5900
WEB_PORT = int(os.environ.get("PLAYSTORE_WEB_PORT", "8000"))
SCREEN_GEOMETRY = "1080x1920x24"  # tall/portrait, closer to a real phone


def sh(cmd, **kwargs):
    playstore.log(f"$ {cmd}")
    return subprocess.Popen(cmd, shell=True, **kwargs)


def start_virtual_display():
    """
    Start Xvfb (a display that renders to memory instead of real hardware)
    and x11vnc (which shares that display over the standard VNC protocol).
    This is the same well-documented pattern used for running any GUI app
    inside a headless container.
    """
    playstore.log("Starting virtual display (Xvfb)...")
    sh(f"Xvfb {DISPLAY_NUM} -screen 0 {SCREEN_GEOMETRY} -ac -nolisten tcp")
    time.sleep(2)

    playstore.log("Starting VNC server (x11vnc) on the virtual display...")
    sh(
        f"x11vnc -display {DISPLAY_NUM} -forever -shared -nopw "
        f"-rfbport {VNC_PORT} -noxdamage -quiet"
    )
    time.sleep(1)


def start_novnc_bridge():
    """
    websockify serves the noVNC web client (static HTML/JS) AND proxies
    the WebSocket connection the browser makes into the plain VNC socket
    x11vnc is listening on — both over the single port GitHub Codespaces
    forwards, so you only need to open one URL.
    """
    playstore.log(f"Starting noVNC web bridge on port {WEB_PORT}...")
    sh(
        f"websockify --web=/usr/share/novnc {WEB_PORT} "
        f"localhost:{VNC_PORT}"
    )
    time.sleep(1)


def main():
    playstore.log("Play Store (Codespaces/web) starting.")

    start_virtual_display()
    start_novnc_bridge()

    codespace_name = os.environ.get("CODESPACE_NAME")
    if codespace_name:
        domain = os.environ.get(
            "GITHUB_CODESPACES_PORT_FORWARDING_DOMAIN", "app.github.dev"
        )
        url = f"https://{codespace_name}-{WEB_PORT}.{domain}/"
    else:
        url = f"http://localhost:{WEB_PORT}/"

    print("=" * 70)
    print(f"Open this URL in your browser to see and use Android:\n  {url}")
    print("(If Codespaces prompts you about port visibility, set port")
    print(f" {WEB_PORT} to Public or Private-with-you so it will load.)")
    print("=" * 70)

    def progress_cb(text):
        playstore.log(f"==> {text}")

    env = {"DISPLAY": DISPLAY_NUM}

    try:
        playstore.run_launch_sequence(
            progress_cb,
            accel="off",  # Codespaces has no /dev/kvm; skip the probe entirely
            extra_emulator_args=[
                "-gpu", "swiftshader_indirect",  # software rendering, no host GPU needed
                "-no-audio",                     # no audio device in this container
                "-no-boot-anim",                 # saves time with no acceleration
            ],
            extra_env=env,
        )
    except Exception as exc:  # noqa: BLE001 - surfaced, not swallowed
        playstore.log(f"ERROR: {exc}")
        sys.exit(1)

    print(f"\nGoogle Play is open. View it at: {url}\n")

    # Keep the process alive so Xvfb/x11vnc/websockify (and the emulator)
    # keep running for the life of the Codespace.
    while True:
        time.sleep(3600)


if __name__ == "__main__":
    main()
