import ctypes
import ctypes.wintypes as wt
import os
import threading
import time

MIN_TERM_W = 360
MIN_SIDEBAR_W = 280
MIN_HEIGHT = 240
EPS = 2


class RECT(ctypes.Structure):
    _fields_ = [('left', wt.LONG), ('top', wt.LONG), ('right', wt.LONG), ('bottom', wt.LONG)]


class MONITORINFO(ctypes.Structure):
    _fields_ = [
        ('cbSize', wt.DWORD),
        ('rcMonitor', RECT),
        ('rcWork', RECT),
        ('dwFlags', wt.DWORD),
    ]


def _setup_win32():
    user32 = ctypes.windll.user32
    dwmapi = ctypes.windll.dwmapi
    try:
        user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
    except Exception:
        try:
            user32.SetProcessDPIAware()
        except Exception:
            pass
    user32.IsWindow.argtypes = [wt.HWND]
    user32.IsWindow.restype = wt.BOOL
    user32.IsWindowVisible.argtypes = [wt.HWND]
    user32.IsWindowVisible.restype = wt.BOOL
    user32.IsZoomed.argtypes = [wt.HWND]
    user32.IsZoomed.restype = wt.BOOL
    user32.IsIconic.argtypes = [wt.HWND]
    user32.IsIconic.restype = wt.BOOL
    user32.ShowWindow.argtypes = [wt.HWND, ctypes.c_int]
    user32.ShowWindow.restype = wt.BOOL
    user32.GetWindowRect.argtypes = [wt.HWND, ctypes.POINTER(RECT)]
    user32.GetWindowRect.restype = wt.BOOL
    user32.SetWindowPos.argtypes = [wt.HWND, wt.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wt.UINT]
    user32.SetWindowPos.restype = wt.BOOL
    user32.GetForegroundWindow.argtypes = []
    user32.GetForegroundWindow.restype = wt.HWND
    user32.SetForegroundWindow.argtypes = [wt.HWND]
    user32.SetForegroundWindow.restype = wt.BOOL
    user32.GetWindowTextW.argtypes = [wt.HWND, wt.LPWSTR, ctypes.c_int]
    user32.GetWindowTextW.restype = ctypes.c_int
    user32.GetAsyncKeyState.argtypes = [ctypes.c_int]
    user32.GetAsyncKeyState.restype = ctypes.c_short
    user32.MonitorFromWindow.argtypes = [wt.HWND, wt.DWORD]
    user32.MonitorFromWindow.restype = wt.HMONITOR
    user32.GetMonitorInfoW.argtypes = [wt.HMONITOR, ctypes.POINTER(MONITORINFO)]
    user32.GetMonitorInfoW.restype = wt.BOOL
    dwmapi.DwmGetWindowAttribute.argtypes = [wt.HWND, wt.DWORD, ctypes.c_void_p, wt.DWORD]
    dwmapi.DwmGetWindowAttribute.restype = ctypes.c_long
    return user32, dwmapi


def compute_initial_rects(term_vis, work_area, is_zoomed, ratio=0.38):
    """Compute initial visible rects (term_rect, sidebar_rect) without enlarging a floating terminal."""
    wl, wt_, wr, wb = work_area
    ww, wh = wr - wl, wb - wt_
    ratio = max(0.25, min(0.55, float(ratio)))

    if is_zoomed:
        sw = max(MIN_SIDEBAR_W, int(round(ww * ratio)))
        tw = max(MIN_TERM_W, ww - sw)
        return (wl, wt_, wl + tw, wb), (wl + tw, wt_, wr, wb)

    tl, tt, tr, tb = term_vis
    tw = max(MIN_TERM_W, tr - tl)
    th = max(MIN_HEIGHT, tb - tt)

    # Sidebar adapts to terminal height and proportional width without enlarging terminal
    desired_sw = int(round(tw * (ratio / (1.0 - ratio))))
    sw = max(360, min(desired_sw, int(round(ww * 0.45)), 760))

    if tr + sw <= wr:
        return (tl, tt, tr, tb), (tr, tt, tr + sw, tb)

    # If overflowing right edge, shift the unified pair left while preserving terminal size
    if tw + sw <= ww:
        new_tl = max(wl, wr - tw - sw)
        new_tr = new_tl + tw
        return (new_tl, tt, new_tr, tb), (new_tr, tt, new_tr + sw, tb)

    # Terminal itself is nearly full monitor width: keep its left/top/height and fit sidebar inside screen
    avail_sw = max(MIN_SIDEBAR_W, int(round(ww * ratio)))
    new_tw = max(MIN_TERM_W, ww - avail_sw)
    return (wl, tt, wl + new_tw, tb), (wl + new_tw, tt, wr, tb)


def solve_dock_step(prev_t, cur_t, prev_s, cur_s):
    """Given previous and current visible rects (L,T,R,B), return (new_t, new_s) or (None, None)."""
    t_changed = any(abs(cur_t[i] - prev_t[i]) > EPS for i in range(4))
    s_changed = any(abs(cur_s[i] - prev_s[i]) > EPS for i in range(4))
    if not t_changed and not s_changed:
        return None, None

    if t_changed:
        ptl, ptt, ptr, ptb = prev_t
        ctl, ctt, ctr, ctb = cur_t
        psl, pst, psr, psb = prev_s

        dL = ctl - ptl
        dT = ctt - ptt
        dR = ctr - ptr
        dB = ctb - ptb

        # Pure move of terminal -> move sidebar by exact same delta
        if abs(dL - dR) <= EPS and abs(dT - dB) <= EPS:
            return None, (psl + dL, pst + dT, psr + dL, psb + dT)

        # Resize of terminal: keep outer right edge (psr) FIXED when dragging the seam (dR != 0)
        new_sl = ctr
        new_sr = psr
        if new_sr - new_sl < MIN_SIDEBAR_W:
            new_sr = new_sl + MIN_SIDEBAR_W
        new_s = (new_sl, ctt, new_sr, ctb)
        if all(abs(new_s[i] - cur_s[i]) <= EPS for i in range(4)):
            return None, None
        return None, new_s

    # Sidebar changed
    ptl, ptt, ptr, ptb = prev_t
    psl, pst, psr, psb = prev_s
    csl, cst, csr, csb = cur_s

    dL = csl - psl
    dT = cst - pst
    dR = csr - psr
    dB = csb - psb

    # Pure move of sidebar -> move terminal by exact same delta
    if abs(dL - dR) <= EPS and abs(dT - dB) <= EPS:
        return (ptl + dL, ptt + dT, ptr + dL, ptb + dT), None

    # Resize of sidebar: keep outer left edge (ptl) FIXED when dragging the seam (dL != 0)
    new_tl = ptl
    new_tr = csl
    if new_tr - new_tl < MIN_TERM_W:
        new_tl = new_tr - MIN_TERM_W
    new_t = (new_tl, cst, new_tr, csb)
    if all(abs(new_t[i] - cur_t[i]) <= EPS for i in range(4)):
        return None, None
    return new_t, None


class WindowDocker:
    """Fuses Windows Terminal and the Edge sidebar into a single seamless window."""

    SWP_NOZORDER = 0x0004
    SWP_NOACTIVATE = 0x0010
    SWP_NOMOVE = 0x0002
    SWP_NOSIZE = 0x0001
    DWMWA_EXTENDED_FRAME_BOUNDS = 9

    def __init__(self, on_edge_closed=None, on_term_title_changed=None):
        self.enabled = (os.name == 'nt')
        self.on_edge_closed = on_edge_closed
        self.on_term_title_changed = on_term_title_changed
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread = None
        self.term_hwnd = 0
        self.edge_hwnd = 0
        self.prev_t = None
        self.prev_s = None
        self.last_fg = 0
        self.last_min_state = False
        self.last_term_title = ''
        if self.enabled:
            self.u32, self.dwm = _setup_win32()

    def _window_title(self, hwnd) -> str:
        if not self.enabled or not hwnd:
            return ''
        buf = ctypes.create_unicode_buffer(512)
        n = self.u32.GetWindowTextW(hwnd, buf, 512)
        return buf.value[:n] if n > 0 else ''

    def focus_terminal(self):
        with self._lock:
            th = self.term_hwnd
        if self.enabled and th and self.u32.IsWindow(th):
            if self.u32.IsIconic(th):
                self.u32.ShowWindow(th, 9)
            self.u32.SetForegroundWindow(th)
            return True
        return False

    def _raw_rect(self, hwnd):
        r = RECT()
        if not self.u32.GetWindowRect(hwnd, ctypes.byref(r)):
            return None
        return (r.left, r.top, r.right, r.bottom)

    def _vis_rect(self, hwnd):
        r = RECT()
        hr = self.dwm.DwmGetWindowAttribute(
            hwnd, self.DWMWA_EXTENDED_FRAME_BOUNDS, ctypes.byref(r), ctypes.sizeof(r)
        )
        if hr == 0:
            return (r.left, r.top, r.right, r.bottom)
        return self._raw_rect(hwnd)

    def _insets(self, hwnd):
        raw = self._raw_rect(hwnd)
        vis = self._vis_rect(hwnd)
        if not raw or not vis:
            return (0, 0, 0, 0)
        return (vis[0] - raw[0], vis[1] - raw[1], raw[2] - vis[2], raw[3] - vis[3])

    def _set_vis_rect(self, hwnd, vrect):
        inL, inT, inR, inB = self._insets(hwnd)
        rl = vrect[0] - inL
        rt = vrect[1] - inT
        rw = (vrect[2] - vrect[0]) + inL + inR
        rh = (vrect[3] - vrect[1]) + inT + inB
        self.u32.SetWindowPos(hwnd, 0, rl, rt, rw, rh, self.SWP_NOZORDER | self.SWP_NOACTIVATE)

    def _monitor_work(self, hwnd):
        mon = self.u32.MonitorFromWindow(hwnd, 2)
        mi = MONITORINFO()
        mi.cbSize = ctypes.sizeof(MONITORINFO)
        if self.u32.GetMonitorInfoW(mon, ctypes.byref(mi)):
            w = mi.rcWork
            return (w.left, w.top, w.right, w.bottom)
        return (0, 0, 1920, 1040)

    def attach(self, term_hwnd: int, edge_hwnd: int, ratio: float = 0.38):
        if not self.enabled or not term_hwnd or not edge_hwnd:
            return False
        if not self.u32.IsWindow(term_hwnd) or not self.u32.IsWindow(edge_hwnd):
            return False

        with self._lock:
            self.term_hwnd = int(term_hwnd)
            self.edge_hwnd = int(edge_hwnd)
            is_zoomed = bool(self.u32.IsZoomed(self.term_hwnd))
            work = self._monitor_work(self.term_hwnd)
            t_vis = self._vis_rect(self.term_hwnd) or work

            new_t, new_s = compute_initial_rects(t_vis, work, is_zoomed, ratio=ratio)
            if is_zoomed:
                self.u32.ShowWindow(self.term_hwnd, 9)
                self._set_vis_rect(self.term_hwnd, new_t)
            elif new_t != t_vis:
                self._set_vis_rect(self.term_hwnd, new_t)

            if self.u32.IsZoomed(self.edge_hwnd):
                self.u32.ShowWindow(self.edge_hwnd, 9)
            self._set_vis_rect(self.edge_hwnd, new_s)

            # Place sidebar right behind terminal in Z-order and keep terminal focused
            self.u32.SetWindowPos(
                self.edge_hwnd, self.term_hwnd, 0, 0, 0, 0,
                self.SWP_NOMOVE | self.SWP_NOSIZE | self.SWP_NOACTIVATE,
            )
            self.u32.SetForegroundWindow(self.term_hwnd)
            self.prev_t = self._vis_rect(self.term_hwnd)
            self.prev_s = self._vis_rect(self.edge_hwnd)
            self.last_term_title = self._window_title(self.term_hwnd)

        if not self._thread or not self._thread.is_alive():
            self._stop.clear()
            self._thread = threading.Thread(target=self._loop, daemon=True)
            self._thread.start()
        return True

    def stop(self):
        self._stop.set()

    def _loop(self):
        while not self._stop.is_set():
            with self._lock:
                th = self.term_hwnd
                eh = self.edge_hwnd
            if not th or not eh:
                time.sleep(0.1)
                continue
            if not self.u32.IsWindow(eh):
                if self.on_edge_closed:
                    self.on_edge_closed()
                break
            if not self.u32.IsWindow(th):
                time.sleep(0.2)
                continue

            if self.on_term_title_changed:
                cur_title = self._window_title(th)
                if cur_title and cur_title != self.last_term_title:
                    self.last_term_title = cur_title
                    try:
                        self.on_term_title_changed(cur_title)
                    except Exception:
                        pass

            t_min = bool(self.u32.IsIconic(th))
            e_min = bool(self.u32.IsIconic(eh))
            if t_min != self.last_min_state:
                self.last_min_state = t_min
                if t_min and not e_min:
                    self.u32.ShowWindow(eh, 6)
                elif not t_min and e_min:
                    self.u32.ShowWindow(eh, 4)
                    time.sleep(0.05)
                    self.prev_t = self._vis_rect(th)
                    self.prev_s = self._vis_rect(eh)
                time.sleep(0.05)
                continue
            if t_min or e_min:
                time.sleep(0.1)
                continue

            # Keep Z-order paired when switching focus to either window
            fg = self.u32.GetForegroundWindow()
            if fg != self.last_fg:
                self.last_fg = fg
                if fg == th:
                    self.u32.SetWindowPos(eh, th, 0, 0, 0, 0, self.SWP_NOMOVE | self.SWP_NOSIZE | self.SWP_NOACTIVATE)
                elif fg == eh:
                    self.u32.SetWindowPos(th, eh, 0, 0, 0, 0, self.SWP_NOMOVE | self.SWP_NOSIZE | self.SWP_NOACTIVATE)

            cur_t = self._vis_rect(th)
            cur_s = self._vis_rect(eh)
            if cur_t and cur_s and self.prev_t and self.prev_s:
                new_t, new_s = solve_dock_step(self.prev_t, cur_t, self.prev_s, cur_s)
                if new_s is not None:
                    self._set_vis_rect(eh, new_s)
                    self.prev_t = cur_t
                    self.prev_s = self._vis_rect(eh) or new_s
                elif new_t is not None:
                    self._set_vis_rect(th, new_t)
                    self.prev_t = self._vis_rect(th) or new_t
                    self.prev_s = cur_s
                else:
                    self.prev_t = cur_t
                    self.prev_s = cur_s

            dragging = bool(self.u32.GetAsyncKeyState(0x01) & 0x8000)
            time.sleep(0.016 if dragging else 0.05)
