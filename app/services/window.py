import ctypes
from ctypes import wintypes
import numpy as np
import cv2
from PIL import Image
from typing import Optional, Tuple
from app.utils.logger import setup_logger

logger = setup_logger("WindowService")

# Windows API Constants
WM_LBUTTONDOWN = 0x0201
WM_LBUTTONUP   = 0x0202
WM_MOUSEMOVE   = 0x0200
MK_LBUTTON     = 0x0001
WM_MOUSEWHEEL  = 0x020A
WHEEL_DELTA    = 120

class WindowService:
    """Handles window finding and screenshot capture using Windows API."""

    # Google Play Games for PC: outer window is typically WPF / HwndWrapper; game surface is CROSVM_1.
    _TOP_LEVEL_CLASS_PREFIX = "HwndWrapper"
    
    def __init__(self, window_name: str = "Clash of Clans", child_class: str = "CROSVM_1"):
        self.window_name = window_name
        self.child_class = child_class
        self.hwnd = 0
        self.user32 = ctypes.windll.user32
        self.gdi32 = ctypes.windll.gdi32
        
        # Setup DPI Awareness
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(2)  # PROCESS_PER_MONITOR_DPI_AWARE
        except Exception:
            self.user32.SetProcessDPIAware()

        self.find_window()

    def find_window(self) -> bool:
        """Finds the game window HWND."""
        self.hwnd = self._get_hwnd_partial(self.window_name, self.child_class)
        if self.hwnd:
            logger.info(f"Window found: {self.window_name} (HWND: {self.hwnd})")
            return True
        else:
            logger.warning(
                f"Window not found: {self.window_name} "
                f"(expect title substring, {self._TOP_LEVEL_CLASS_PREFIX!r} top-level, "
                f"and {self.child_class!r} child — Google Play Games)"
            )
            return False

    def _get_hwnd_partial(self, name: str, child_class: str) -> int:
        """
        Returns the child HWND (``CROSVM_1``) under a **Google Play Games–style** top-level window:
        title contains ``name`` (case-insensitive), top-level class name starts with
        :attr:`_TOP_LEVEL_CLASS_PREFIX`, and a descendant with window class ``child_class`` exists.

        Skips Chromium hosts (Discord, Chrome, etc.) and does **not** fall back to the top-level
        HWND when ``child_class`` is missing, so the first bogus title match is not used.
        """
        result = {"hwnd": 0}
        EnumWindows = self.user32.EnumWindows
        EnumWindowsProc = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
        GetWindowTextLength = self.user32.GetWindowTextLengthW
        GetWindowText = self.user32.GetWindowTextW
        IsWindowVisible = self.user32.IsWindowVisible
        EnumChildWindows = self.user32.EnumChildWindows
        top_prefix = self._TOP_LEVEL_CLASS_PREFIX

        def get_class(hwnd) -> str:
            buf = ctypes.create_unicode_buffer(256)
            self.user32.GetClassNameW(hwnd, buf, 256)
            return buf.value

        def find_descendant_by_class(root_hwnd, target_class) -> int:
            found = {"hwnd": 0}

            def enum_child_cb(child_hwnd, lParam):
                if get_class(child_hwnd) == target_class:
                    found["hwnd"] = child_hwnd
                    return False
                EnumChildWindows(child_hwnd, EnumWindowsProc(enum_child_cb), 0)
                return True

            EnumChildWindows(root_hwnd, EnumWindowsProc(enum_child_cb), 0)
            return found["hwnd"]

        def enum_top_cb(hwnd, lParam):
            if IsWindowVisible(hwnd):
                length = GetWindowTextLength(hwnd)
                if length > 0:
                    buff = ctypes.create_unicode_buffer(length + 1)
                    GetWindowText(hwnd, buff, length + 1)
                    title = buff.value

                    if name.lower() in title.lower():
                        if not get_class(hwnd).startswith(top_prefix):
                            return True
                        child = find_descendant_by_class(hwnd, child_class)
                        if child:
                            result["hwnd"] = child
                            return False
            return True

        EnumWindows(EnumWindowsProc(enum_top_cb), 0)
        return result["hwnd"]

    def get_outer_pixel_size(self) -> Optional[Tuple[int, int]]:
        """
        Outer window size in pixels (``GetWindowRect``), same basis as :meth:`screenshot`.
        """
        if not self.hwnd:
            if not self.find_window():
                return None
        try:
            rect = wintypes.RECT()
            self.user32.GetWindowRect(self.hwnd, ctypes.byref(rect))
            w = rect.right - rect.left
            h = rect.bottom - rect.top
            if w <= 0 or h <= 0:
                return None
            return int(w), int(h)
        except Exception:
            return None

    def screenshot(self) -> Optional[np.ndarray]:
        """Captures a screenshot of the window."""
        if not self.hwnd:
            if not self.find_window():
                return None

        try:
            # Get window rect
            rect = wintypes.RECT()
            self.user32.GetWindowRect(self.hwnd, ctypes.byref(rect))
            width = rect.right - rect.left
            height = rect.bottom - rect.top
            
            if width <= 0 or height <= 0:
                # logger.warning("Window has invalid dimensions.") # Suppress spam
                return None

            # Get DC
            hwndDC = self.user32.GetWindowDC(self.hwnd)
            mfcDC = self.gdi32.CreateCompatibleDC(hwndDC)
            hbitmap = self.gdi32.CreateCompatibleBitmap(hwndDC, width, height)
            self.gdi32.SelectObject(mfcDC, hbitmap)

            # PrintWindow
            PW_RENDERFULLCONTENT = 0x00000002
            self.user32.PrintWindow(self.hwnd, mfcDC, PW_RENDERFULLCONTENT)

            # Bitmap Info
            class BITMAPINFOHEADER(ctypes.Structure):
                _fields_ = [
                    ("biSize", wintypes.DWORD),
                    ("biWidth", ctypes.c_long),
                    ("biHeight", ctypes.c_long),
                    ("biPlanes", wintypes.WORD),
                    ("biBitCount", wintypes.WORD),
                    ("biCompression", wintypes.DWORD),
                    ("biSizeImage", wintypes.DWORD),
                    ("biXPelsPerMeter", ctypes.c_long),
                    ("biYPelsPerMeter", ctypes.c_long),
                    ("biClrUsed", wintypes.DWORD),
                    ("biClrImportant", wintypes.DWORD)
                ]

            bmi = BITMAPINFOHEADER()
            bmi.biSize = ctypes.sizeof(BITMAPINFOHEADER)
            bmi.biWidth = width
            bmi.biHeight = -height  # Top-down
            bmi.biPlanes = 1
            bmi.biBitCount = 32
            bmi.biCompression = 0

            buf_size = width * height * 4
            buffer = (ctypes.c_byte * buf_size)()

            self.gdi32.GetDIBits(hwndDC, hbitmap, 0, height, ctypes.byref(buffer), ctypes.byref(bmi), 0)

            img = Image.frombuffer("RGBA", (width, height), bytes(buffer), "raw", "BGRA", 0, 1)
            frame = np.array(img)

            # Convert to BGR for OpenCV
            if frame.shape[2] == 4:
                frame = cv2.cvtColor(frame, cv2.COLOR_RGBA2BGR)
            else:
                frame = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)

            # Cleanup
            self.gdi32.DeleteObject(hbitmap)
            self.gdi32.DeleteDC(mfcDC)
            self.user32.ReleaseDC(self.hwnd, hwndDC)

            return frame
            
        except Exception as e:
            logger.error(f"Screenshot failed: {e}")
            return None
