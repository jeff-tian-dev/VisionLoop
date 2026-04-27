import ctypes
from ctypes import wintypes
import numpy as np
import cv2
from PIL import Image
from typing import Optional, Tuple
from app.utils.logger import setup_logger

GA_ROOT = 2
SW_RESTORE = 9
SWP_NOMOVE = 0x0002
SWP_NOZORDER = 0x0004

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
            logger.warning(f"Window not found: {self.window_name}")
            return False

    def _get_hwnd_partial(self, name: str, child_class: str) -> int:
        """
        Returns the child HWND (e.g. CROSVM_1) under the top-level window whose title
        contains `name`. Falls back to the top-level HWND if the child isn't found.
        """
        result = {"hwnd": 0}
        EnumWindows = self.user32.EnumWindows
        EnumWindowsProc = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
        GetWindowTextLength = self.user32.GetWindowTextLengthW
        GetWindowText = self.user32.GetWindowTextW
        IsWindowVisible = self.user32.IsWindowVisible
        EnumChildWindows = self.user32.EnumChildWindows

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
                        child = find_descendant_by_class(hwnd, child_class)
                        result["hwnd"] = child if child else hwnd
                        return False
            return True

        EnumWindows(EnumWindowsProc(enum_top_cb), 0)
        return result["hwnd"]

    def _get_root_hwnd(self) -> int:
        """Returns the top-level ancestor of the current hwnd."""
        root = self.user32.GetAncestor(self.hwnd, GA_ROOT)
        return root if root else self.hwnd

    def fit_window(self, target_w: int = 2560, target_h: int = 1600) -> bool:
        """
        Resizes the top-level emulator window so the game render surface (CROSVM_1 child)
        is exactly target_w x target_h pixels.

        Measures the current margins between the outer window and the child at runtime, so
        it works regardless of emulator toolbars, title bar height, or DPI.
        Returns True on success, False if the window handle is missing.
        """
        if not self.hwnd:
            logger.warning("fit_window: no window handle, skipping resize")
            return False

        root = self._get_root_hwnd()

        # Restore from minimized/maximized so SetWindowPos takes effect
        self.user32.ShowWindow(root, SW_RESTORE)

        # Measure current rects in screen coordinates
        child_rect = wintypes.RECT()
        self.user32.GetWindowRect(self.hwnd, ctypes.byref(child_rect))

        root_rect = wintypes.RECT()
        self.user32.GetWindowRect(root, ctypes.byref(root_rect))

        # Margins = space the emulator adds around the game surface (title bar, borders, toolbars)
        margin_l = child_rect.left  - root_rect.left
        margin_t = child_rect.top   - root_rect.top
        margin_r = root_rect.right  - child_rect.right
        margin_b = root_rect.bottom - child_rect.bottom

        new_w = target_w + margin_l + margin_r
        new_h = target_h + margin_t + margin_b

        self.user32.SetWindowPos(root, 0, 0, 0, new_w, new_h, SWP_NOMOVE | SWP_NOZORDER)
        logger.info(
            f"fit_window: game surface → {target_w}x{target_h}, "
            f"margins (l={margin_l} t={margin_t} r={margin_r} b={margin_b}), "
            f"outer window → {new_w}x{new_h}"
        )
        return True

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
