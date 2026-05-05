"""
List visible top-level windows (EnumWindows + IsWindowVisible + non-empty title), plus HWND
and window class. Annotations show which titles overlap the bot's substring match and whether
the top-level class matches Google Play Games (HwndWrapper).

Usage (from repo root): python scripts/list_visible_window_titles.py
"""
from __future__ import annotations

import ctypes
from ctypes import wintypes

user32 = ctypes.windll.user32


def main() -> None:
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        user32.SetProcessDPIAware()

    rows: list[tuple[int, str, str]] = []

    def get_class(hwnd: int) -> str:
        buf = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(hwnd, buf, 256)
        return buf.value

    EnumWindowsProc = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)

    def enum_cb(hwnd: int, _lParam: int) -> bool:
        if not user32.IsWindowVisible(hwnd):
            return True
        length = user32.GetWindowTextLengthW(hwnd)
        if length <= 0:
            return True
        buff = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buff, length + 1)
        title = buff.value.strip()
        if not title:
            return True
        rows.append((int(hwnd), title, get_class(hwnd)))
        return True

    user32.EnumWindows(EnumWindowsProc(enum_cb), 0)

    rows.sort(key=lambda r: r[1].lower())

    clash = "Clash of Clans"
    child_cls = "CROSVM_1"

    print(f"Visible top-level windows with a title ({len(rows)} total)")
    print("Format: HWND | class | title")
    print("-" * 80)
    for hwnd, title, cls in rows:
        mark = ""
        if clash.lower() in title.lower():
            if cls.startswith("HwndWrapper"):
                mark = (
                    f"  <<< title + HwndWrapper (bot needs child {child_cls!r} under this top-level)"
                )
            else:
                mark = "  <<< title only (skipped: top-level is not HwndWrapper)"
        print(f"{hwnd:8} | {cls[:32]:32} | {title}{mark}")
    print("-" * 80)
    print(
        "Bot picks: visible top-level title contains 'Clash of Clans' (case-insensitive), "
        "class name starts with 'HwndWrapper', then descendant HWND with class 'CROSVM_1' "
        "(Google Play Games for PC). Chromium windows (Chrome, Discord, …) are skipped."
    )


if __name__ == "__main__":
    main()
