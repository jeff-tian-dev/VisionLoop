import ctypes
import time
import random
import math
from typing import Tuple

from app.services.window import WindowService, WM_LBUTTONDOWN, WM_LBUTTONUP, WM_MOUSEMOVE, MK_LBUTTON, WM_MOUSEWHEEL, WHEEL_DELTA
from app.utils.logger import setup_logger

logger = setup_logger("InputService")

class InputService:
    """Handles mouse and keyboard injection."""

    def __init__(self, window_service: WindowService, stop_event=None):
        self.window_service = window_service
        self.stop_event = stop_event
        self.user32 = ctypes.windll.user32

    def _clamp_to_capture(self, x: int, y: int) -> Tuple[int, int]:
        """
        Clamp client-style coordinates into the current captured window rectangle
        (:meth:`WindowService.get_outer_pixel_size`, same outer size as screenshots).
        """
        sz = self.window_service.get_outer_pixel_size()
        if not sz:
            return int(x), int(y)
        w, h = sz
        if w <= 1 or h <= 1:
            return int(x), int(y)
        cx = max(0, min(w - 1, int(x)))
        cy = max(0, min(h - 1, int(y)))
        return cx, cy

    def _make_lparam(self, x: int, y: int) -> int:
        xc, yc = self._clamp_to_capture(x, y)
        return (yc << 16) | (xc & 0xFFFF)

    def click(self, x: int, y: int, pause: float = 1.0, rand: bool = True):
        """Performs a click with optional randomization and delay."""
        if rand:
            x += random.randint(-15, 15)
            y += random.randint(-15, 15)
        
        self._inject_click(x, y)
        
        # Randomized sleep
        sleep_time = random.uniform(pause - (pause * 0.2), pause + (pause * 0.2))
        time.sleep(max(0.1, sleep_time))

    def _inject_click(self, x: int, y: int):
        hwnd = self.window_service.hwnd
        if not hwnd:
            return
            
        lparam = self._make_lparam(int(x), int(y))
        self.user32.SendMessageW(hwnd, WM_LBUTTONDOWN, MK_LBUTTON, lparam)
        self.user32.SendMessageW(hwnd, WM_LBUTTONUP, 0, lparam)

    def click_at(self, x: int, y: int, rand: bool = False):
        """Single mouse down/up at (x, y) with no delay (for chained clicks with custom timing)."""
        if rand:
            x += random.randint(-15, 15)
            y += random.randint(-15, 15)
        self._inject_click(int(x), int(y))

    def mouse_down(self, x: int, y: int):
        hwnd = self.window_service.hwnd
        if not hwnd: return
        self.user32.SendMessageW(hwnd, WM_LBUTTONDOWN, MK_LBUTTON, self._make_lparam(x, y))

    def mouse_up(self, x: int, y: int):
        hwnd = self.window_service.hwnd
        if not hwnd: return
        self.user32.SendMessageW(hwnd, WM_LBUTTONUP, 0, self._make_lparam(x, y))

    def move(self, x: int, y: int, wparam: int = 0):
        """WM_MOUSEMOVE. Use ``wparam=MK_LBUTTON`` only while simulating a held drag (see ``human_move``)."""
        hwnd = self.window_service.hwnd
        if not hwnd: return
        self.user32.SendMessageW(hwnd, WM_MOUSEMOVE, wparam, self._make_lparam(x, y))

    def human_move(self, x1: int, y1: int, x2: int, y2: int, duration: float = 0.5):
        """Simulates human-like mouse movement using a Bezier curve and easing."""
        hwnd = self.window_service.hwnd
        if not hwnd: return

        # Randomize control point for curve
        mx = (x1 + x2) / 2
        my = (y1 + y2) / 2
        dist = ((x2 - x1)**2 + (y2 - y1)**2)**0.5
        offset = dist * random.uniform(0.05, 0.2)
        cx = mx + random.uniform(-offset, offset)
        cy = my + random.uniform(-offset, offset)

        start_time = time.perf_counter()

        while True:
            if self.stop_event and self.stop_event.is_set():
                break

            current_time = time.perf_counter()
            elapsed = current_time - start_time

            if elapsed >= duration:
                break

            t = elapsed / duration
            ease = -(math.cos(math.pi * t) - 1) / 2
            u = 1 - ease
            x = (u ** 2) * x1 + 2 * u * ease * cx + (ease ** 2) * x2
            y = (u ** 2) * y1 + 2 * u * ease * cy + (ease ** 2) * y2

            self.move(int(x), int(y), MK_LBUTTON)

            if self.stop_event:
                self.stop_event.wait(0.005)
            else:
                time.sleep(0.005)

        self.move(x2, y2, MK_LBUTTON)

    def scroll(self, x: int, y: int, amount: int):
        hwnd = self.window_service.hwnd
        if not hwnd: return
        
        delta = int(-1 * WHEEL_DELTA)
        wparam = delta << 16
        lparam = self._make_lparam(x, y)
        
        for _ in range(amount):
            self.user32.SendMessageW(hwnd, WM_MOUSEWHEEL, wparam, lparam)
            time.sleep(random.uniform(0.05, 0.2))
