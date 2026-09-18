"""Work Journal desktop app for Windows.

The app runs quietly in the background and opens a check-in prompt at a
user-defined interval. Entries are stored locally in work_journal_log.csv.

Run with: python work_journal.py
Or double-click run_work_journal.bat to start without a console window.

Only the Python standard library is required.
"""

import os
import csv
import json
import ctypes
import datetime
import math
import random
import tkinter as tk
from tkinter import filedialog, messagebox
from ctypes import wintypes

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(BASE_DIR, "work_journal_config.json")
LOG_FILE = os.path.join(BASE_DIR, "work_journal_log.csv")
ICON_FILE = os.path.join(BASE_DIR, "work_journal_icon.ico")
ICON_PNG_FILE = os.path.join(BASE_DIR, "work_journal_icon.png")
SINGLE_INSTANCE_MUTEX = "Local\\WorkJournalSingleInstance"
ERROR_ALREADY_EXISTS = 183


def load_config():
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            pass
    return {"interval": 15}


def save_config(cfg):
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(cfg, f)
    except OSError:
        pass


def load_entries():
    entries = []
    if os.path.exists(LOG_FILE):
        try:
            with open(LOG_FILE, "r", encoding="utf-8-sig", newline="") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    entries.append({
                        "date": row.get("date", row.get("datum", "")),
                        "time": row.get("time", row.get("vrijeme", "")),
                        "activity": row.get("activity", row.get("tekst", "")),
                        "timestamp": row.get("timestamp", row.get("ts", "")),
                    })
        except OSError:
            pass
    return entries


def append_entry_to_file(entry):
    is_new = not os.path.exists(LOG_FILE)
    try:
        with open(LOG_FILE, "a", encoding="utf-8-sig", newline="") as f:
            writer = csv.DictWriter(
                f,
                fieldnames=["date", "time", "activity", "timestamp"],
            )
            if is_new:
                writer.writeheader()
            writer.writerow(entry)
    except OSError as e:
        messagebox.showerror("Error", f"Could not save the entry:\n{e}")


class TrayPOINT(ctypes.Structure):
    _fields_ = [("x", wintypes.LONG), ("y", wintypes.LONG)]


class TrayGUID(ctypes.Structure):
    _fields_ = [
        ("Data1", wintypes.DWORD),
        ("Data2", wintypes.WORD),
        ("Data3", wintypes.WORD),
        ("Data4", ctypes.c_ubyte * 8),
    ]


class TrayWNDCLASS(ctypes.Structure):
    _fields_ = [
        ("style", wintypes.UINT),
        ("lpfnWndProc", ctypes.c_void_p),
        ("cbClsExtra", ctypes.c_int),
        ("cbWndExtra", ctypes.c_int),
        ("hInstance", wintypes.HINSTANCE),
        ("hIcon", wintypes.HICON),
        ("hCursor", wintypes.HCURSOR),
        ("hbrBackground", wintypes.HBRUSH),
        ("lpszMenuName", wintypes.LPCWSTR),
        ("lpszClassName", wintypes.LPCWSTR),
    ]


class TrayNOTIFYICONDATA(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("hWnd", wintypes.HWND),
        ("uID", wintypes.UINT),
        ("uFlags", wintypes.UINT),
        ("uCallbackMessage", wintypes.UINT),
        ("hIcon", wintypes.HICON),
        ("szTip", wintypes.WCHAR * 128),
        ("dwState", wintypes.DWORD),
        ("dwStateMask", wintypes.DWORD),
        ("szInfo", wintypes.WCHAR * 256),
        ("uVersion", wintypes.UINT),
        ("szInfoTitle", wintypes.WCHAR * 64),
        ("dwInfoFlags", wintypes.DWORD),
        ("guidItem", TrayGUID),
        ("hBalloonIcon", wintypes.HICON),
    ]


class WindowsTrayIcon:
    WM_TRAYICON = 0x0400 + 20
    RESTORE_ID = 1001
    EXIT_ID = 1002

    NIM_ADD = 0x00000000
    NIM_DELETE = 0x00000002
    NIM_SETVERSION = 0x00000004
    NIF_MESSAGE = 0x00000001
    NIF_ICON = 0x00000002
    NIF_TIP = 0x00000004
    NOTIFYICON_VERSION_4 = 4

    WM_COMMAND = 0x0111
    WM_HOTKEY = 0x0312
    WM_CONTEXTMENU = 0x007B
    WM_LBUTTONDBLCLK = 0x0203
    WM_LBUTTONUP = 0x0202
    WM_RBUTTONUP = 0x0205
    NIN_SELECT = 0x0400
    NIN_KEYSELECT = 0x0401
    ESCAPE_HOTKEY_ID = 1003
    MOD_NOREPEAT = 0x4000
    VK_ESCAPE = 0x1B

    IDI_APPLICATION = 32512
    IMAGE_ICON = 1
    LR_LOADFROMFILE = 0x00000010
    LR_DEFAULTSIZE = 0x00000040
    MF_STRING = 0x00000000
    MF_SEPARATOR = 0x00000800
    TPM_RIGHTBUTTON = 0x00000002
    TPM_RETURNCMD = 0x00000100

    def __init__(self, app):
        self.app = app
        self.user32 = ctypes.windll.user32
        self.shell32 = ctypes.windll.shell32
        self.kernel32 = ctypes.windll.kernel32
        self.hwnd = None
        self.hicon = None
        self._owns_icon = False
        self._wndproc = None
        self._class_name = "WorkJournalTrayWindow"
        self._created = False
        self._escape_registered = False

        if os.name == "nt":
            self._configure_winapi()
            self._create()

    def _configure_winapi(self):
        self.kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
        self.kernel32.GetModuleHandleW.restype = wintypes.HINSTANCE

        self.user32.DefWindowProcW.argtypes = [
            wintypes.HWND,
            wintypes.UINT,
            ctypes.c_size_t,
            ctypes.c_ssize_t,
        ]
        self.user32.DefWindowProcW.restype = ctypes.c_ssize_t
        self.user32.RegisterClassW.argtypes = [ctypes.POINTER(TrayWNDCLASS)]
        self.user32.RegisterClassW.restype = wintypes.ATOM
        self.user32.CreateWindowExW.argtypes = [
            wintypes.DWORD,
            wintypes.LPCWSTR,
            wintypes.LPCWSTR,
            wintypes.DWORD,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            wintypes.HWND,
            wintypes.HMENU,
            wintypes.HINSTANCE,
            wintypes.LPVOID,
        ]
        self.user32.CreateWindowExW.restype = wintypes.HWND
        self.user32.DestroyWindow.argtypes = [wintypes.HWND]
        self.user32.DestroyWindow.restype = wintypes.BOOL
        self.user32.LoadIconW.restype = wintypes.HICON
        self.user32.LoadImageW.argtypes = [
            wintypes.HINSTANCE,
            wintypes.LPCWSTR,
            wintypes.UINT,
            ctypes.c_int,
            ctypes.c_int,
            wintypes.UINT,
        ]
        self.user32.LoadImageW.restype = wintypes.HICON
        self.user32.DestroyIcon.argtypes = [wintypes.HICON]
        self.user32.DestroyIcon.restype = wintypes.BOOL
        self.user32.GetCursorPos.argtypes = [ctypes.POINTER(TrayPOINT)]
        self.user32.GetCursorPos.restype = wintypes.BOOL
        self.user32.CreatePopupMenu.restype = wintypes.HMENU
        self.user32.AppendMenuW.argtypes = [wintypes.HMENU, wintypes.UINT, ctypes.c_size_t, wintypes.LPCWSTR]
        self.user32.AppendMenuW.restype = wintypes.BOOL
        self.user32.TrackPopupMenu.argtypes = [
            wintypes.HMENU,
            wintypes.UINT,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            wintypes.HWND,
            wintypes.LPVOID,
        ]
        self.user32.TrackPopupMenu.restype = wintypes.UINT
        self.user32.DestroyMenu.argtypes = [wintypes.HMENU]
        self.user32.DestroyMenu.restype = wintypes.BOOL
        self.user32.SetForegroundWindow.argtypes = [wintypes.HWND]
        self.user32.SetForegroundWindow.restype = wintypes.BOOL
        self.user32.RegisterHotKey.argtypes = [
            wintypes.HWND,
            ctypes.c_int,
            wintypes.UINT,
            wintypes.UINT,
        ]
        self.user32.RegisterHotKey.restype = wintypes.BOOL
        self.user32.UnregisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int]
        self.user32.UnregisterHotKey.restype = wintypes.BOOL
        self.shell32.Shell_NotifyIconW.argtypes = [wintypes.DWORD, ctypes.POINTER(TrayNOTIFYICONDATA)]
        self.shell32.Shell_NotifyIconW.restype = wintypes.BOOL

    def _create(self):
        wndproc_type = ctypes.WINFUNCTYPE(
            ctypes.c_ssize_t,
            wintypes.HWND,
            wintypes.UINT,
            ctypes.c_size_t,
            ctypes.c_ssize_t,
        )
        self._wndproc = wndproc_type(self._handle_message)
        hinstance = self.kernel32.GetModuleHandleW(None)

        wndclass = TrayWNDCLASS()
        wndclass.lpfnWndProc = ctypes.cast(self._wndproc, ctypes.c_void_p).value
        wndclass.hInstance = hinstance
        wndclass.lpszClassName = self._class_name

        try:
            self.user32.RegisterClassW(ctypes.byref(wndclass))
        except OSError:
            pass

        self.hwnd = self.user32.CreateWindowExW(
            0, self._class_name, self._class_name, 0, 0, 0, 0, 0,
            None, None, hinstance, None
        )
        if not self.hwnd:
            return

        if os.path.exists(ICON_FILE):
            self.hicon = self.user32.LoadImageW(
                None,
                ICON_FILE,
                self.IMAGE_ICON,
                0,
                0,
                self.LR_LOADFROMFILE | self.LR_DEFAULTSIZE,
            )
            self._owns_icon = bool(self.hicon)
        if not self.hicon:
            self.hicon = self.user32.LoadIconW(None, self.IDI_APPLICATION)
        nid = self._notify_data()
        self.shell32.Shell_NotifyIconW(self.NIM_ADD, ctypes.byref(nid))
        nid.uVersion = self.NOTIFYICON_VERSION_4
        self.shell32.Shell_NotifyIconW(self.NIM_SETVERSION, ctypes.byref(nid))
        self._created = True

    def _notify_data(self):
        nid = TrayNOTIFYICONDATA()
        nid.cbSize = ctypes.sizeof(TrayNOTIFYICONDATA)
        nid.hWnd = self.hwnd
        nid.uID = 1
        nid.uFlags = self.NIF_MESSAGE | self.NIF_ICON | self.NIF_TIP
        nid.uCallbackMessage = self.WM_TRAYICON
        nid.hIcon = self.hicon
        nid.szTip = "Work Journal - running in the background"
        return nid

    def _handle_message(self, hwnd, msg, wparam, lparam):
        if msg == self.WM_TRAYICON:
            # NOTIFYICON_VERSION_4 stores the event in the low word of lParam.
            event = int(lparam) & 0xFFFF
            if event in (
                self.WM_LBUTTONUP,
                self.WM_LBUTTONDBLCLK,
                self.NIN_SELECT,
                self.NIN_KEYSELECT,
            ):
                self.app.show_main_window()
            elif event in (self.WM_RBUTTONUP, self.WM_CONTEXTMENU):
                self._show_menu()
            return 0

        if msg == self.WM_COMMAND:
            command = int(wparam) & 0xFFFF
            if command == self.RESTORE_ID:
                self.app.show_main_window()
            elif command == self.EXIT_ID:
                self.app.quit_app()
            return 0

        if msg == self.WM_HOTKEY and int(wparam) == self.ESCAPE_HOTKEY_ID:
            self.app.skip_popup()
            return 0

        return self.user32.DefWindowProcW(hwnd, msg, wparam, lparam)

    def register_escape_hotkey(self):
        if not self._created or self._escape_registered:
            return self._escape_registered
        self._escape_registered = bool(self.user32.RegisterHotKey(
            self.hwnd,
            self.ESCAPE_HOTKEY_ID,
            self.MOD_NOREPEAT,
            self.VK_ESCAPE,
        ))
        return self._escape_registered

    def unregister_escape_hotkey(self):
        if not self._escape_registered:
            return
        self.user32.UnregisterHotKey(self.hwnd, self.ESCAPE_HOTKEY_ID)
        self._escape_registered = False

    def _show_menu(self):
        point = TrayPOINT()
        self.user32.GetCursorPos(ctypes.byref(point))

        menu = self.user32.CreatePopupMenu()
        self.user32.AppendMenuW(menu, self.MF_STRING, self.RESTORE_ID, "Open")
        self.user32.AppendMenuW(menu, self.MF_SEPARATOR, 0, None)
        self.user32.AppendMenuW(menu, self.MF_STRING, self.EXIT_ID, "Exit")

        self.user32.SetForegroundWindow(self.hwnd)
        command = self.user32.TrackPopupMenu(
            menu,
            self.TPM_RETURNCMD | self.TPM_RIGHTBUTTON,
            point.x,
            point.y,
            0,
            self.hwnd,
            None,
        )
        self.user32.DestroyMenu(menu)

        if command == self.RESTORE_ID:
            self.app.show_main_window()
        elif command == self.EXIT_ID:
            self.app.quit_app()

    def destroy(self):
        if not self._created:
            return
        self.unregister_escape_hotkey()
        nid = self._notify_data()
        self.shell32.Shell_NotifyIconW(self.NIM_DELETE, ctypes.byref(nid))
        self._created = False
        if self.hwnd:
            self.user32.DestroyWindow(self.hwnd)
            self.hwnd = None
        if self._owns_icon and self.hicon:
            self.user32.DestroyIcon(self.hicon)
            self.hicon = None
            self._owns_icon = False


class WorkJournalApp:
    WINDOW_WIDTH = 480
    WINDOW_HEIGHT = 640
    BG = "#0d1117"
    PANEL = "#161b22"
    PANEL_HOVER = "#1f2630"
    BORDER = "#2a323d"
    TEXT = "#f0f3f6"
    MUTED = "#8b96a5"
    ACCENT = "#4fd1a1"
    ACCENT_HOVER = "#66ddb0"
    ACCENT_DARK = "#102a23"

    def __init__(self, root):
        self.root = root
        self.root.title("Work Journal")
        self.root.overrideredirect(True)
        self.root.resizable(False, False)
        self.root.minsize(self.WINDOW_WIDTH, self.WINDOW_HEIGHT)
        self.root.maxsize(self.WINDOW_WIDTH, self.WINDOW_HEIGHT)
        window_x = max(0, (self.root.winfo_screenwidth() - self.WINDOW_WIDTH) // 2)
        window_y = max(0, (self.root.winfo_screenheight() - self.WINDOW_HEIGHT) // 2)
        self.root.geometry(
            f"{self.WINDOW_WIDTH}x{self.WINDOW_HEIGHT}+{window_x}+{window_y}"
        )
        self.root.configure(bg=self.BG)
        self.app_icon_image = None
        self.title_icon_image = None
        if os.path.exists(ICON_PNG_FILE):
            try:
                self.app_icon_image = tk.PhotoImage(file=ICON_PNG_FILE)
                self.root.iconphoto(True, self.app_icon_image)
                self.title_icon_image = self.app_icon_image.subsample(12, 12)
            except tk.TclError:
                self.app_icon_image = None
                self.title_icon_image = None
        if os.path.exists(ICON_FILE):
            try:
                self.root.iconbitmap(default=ICON_FILE)
            except tk.TclError:
                pass

        cfg = load_config()
        self.interval_minutes = cfg.get("interval", 15)
        self.entries = load_entries()

        self.running = False
        self.next_time = None
        self.prompt_after_id = None
        self.tick_after_id = None
        self.popup = None
        self.popup_entry = None
        self.popup_canvas = None
        self.popup_particles = []
        self.popup_particle_after_id = None
        self.popup_placeholder_active = False
        self.popup_finish = None
        self.is_quitting = False
        self.tray_icon = None
        self._drag_offset_x = 0
        self._drag_offset_y = 0

        self._build_ui()
        self._render_log()
        self.tray_icon = WindowsTrayIcon(self)

    # ---------- UI ----------

    def _build_ui(self):
        self._build_title_bar()

        header = tk.Frame(self.root, bg=self.BG)
        header.pack(fill="x", padx=24, pady=(18, 14))

        tk.Label(
            header,
            text="OVERVIEW",
            bg=self.BG,
            fg=self.MUTED,
            font=("Segoe UI", 9, "bold"),
        ).pack(side="left")

        self.header_status = tk.Label(
            header,
            text="  PAUSED  ",
            bg=self.PANEL,
            fg=self.MUTED,
            font=("Segoe UI", 8, "bold"),
            padx=6,
            pady=4,
        )
        self.header_status.pack(side="right")

        status_frame = tk.Frame(
            self.root,
            bg=self.PANEL,
            highlightbackground=self.BORDER,
            highlightthickness=1,
        )
        status_frame.pack(fill="x", padx=24)

        self.status_label = tk.Label(
            status_frame,
            text="TIMER PAUSED",
            bg=self.PANEL,
            fg=self.MUTED,
            font=("Segoe UI", 9, "bold"),
        )
        self.status_label.pack(pady=(22, 2))

        self.clock_label = tk.Label(
            status_frame,
            text="--:--",
            bg=self.PANEL,
            fg=self.TEXT,
            font=("Consolas", 38, "bold"),
        )
        self.clock_label.pack(pady=(0, 18))

        btn_row = tk.Frame(status_frame, bg=self.PANEL)
        btn_row.pack(pady=(0, 22))

        self.start_btn = self._make_button(
            btn_row,
            "Start",
            self.toggle_running,
            primary=True,
            width=15,
        )
        self.start_btn.pack(side="left", padx=(0, 6))

        now_btn = self._make_button(
            btn_row,
            "Log now",
            self.log_now,
            width=15,
        )
        now_btn.pack(side="left", padx=(6, 0))

        interval_frame = tk.Frame(self.root, bg=self.BG)
        interval_frame.pack(fill="x", padx=24, pady=(18, 16))

        tk.Label(
            interval_frame,
            text="Reminder interval",
            bg=self.BG,
            fg=self.TEXT,
            font=("Segoe UI", 10, "bold"),
        ).pack(side="left")

        interval_controls = tk.Frame(interval_frame, bg=self.BG)
        interval_controls.pack(side="right")

        minus_btn = self._make_button(
            interval_controls,
            "-",
            lambda: self._adjust_interval(-1),
            width=3,
            compact=True,
        )
        minus_btn.pack(side="left")

        self.interval_var = tk.StringVar(value=str(self.interval_minutes))
        interval_entry = tk.Entry(
            interval_controls,
            width=4,
            textvariable=self.interval_var,
            justify="center",
            bg=self.PANEL,
            fg=self.TEXT,
            insertbackground=self.TEXT,
            selectbackground=self.ACCENT,
            selectforeground=self.BG,
            relief="flat",
            highlightbackground=self.BORDER,
            highlightcolor=self.ACCENT,
            highlightthickness=1,
            font=("Segoe UI", 10, "bold"),
        )
        self.interval_entry = interval_entry
        interval_entry.pack(side="left", ipady=7, padx=6)
        interval_entry.bind("<Return>", lambda _event: self._on_interval_change())
        interval_entry.bind("<FocusOut>", lambda _event: self._on_interval_change())

        plus_btn = self._make_button(
            interval_controls,
            "+",
            lambda: self._adjust_interval(1),
            width=3,
            compact=True,
        )
        plus_btn.pack(side="left")

        tk.Label(
            interval_controls,
            text="min",
            bg=self.BG,
            fg=self.MUTED,
            font=("Segoe UI", 9),
        ).pack(side="left", padx=(8, 0))

        divider = tk.Frame(self.root, bg=self.BORDER, height=1)
        divider.pack(fill="x", padx=24)

        log_head = tk.Frame(self.root, bg=self.BG)
        log_head.pack(fill="x", padx=24, pady=(16, 10))
        tk.Label(
            log_head,
            text="Activity log",
            bg=self.BG,
            fg=self.TEXT,
            font=("Segoe UI", 11, "bold"),
        ).pack(side="left")
        self.count_label = tk.Label(
            log_head,
            bg=self.BG,
            fg=self.MUTED,
            font=("Segoe UI", 9),
        )
        self.count_label.pack(side="right")

        log_frame = tk.Frame(
            self.root,
            bg=self.PANEL,
            highlightbackground=self.BORDER,
            highlightthickness=1,
        )
        log_frame.pack(fill="both", expand=True, padx=24, pady=(0, 14))

        scrollbar = tk.Scrollbar(
            log_frame,
            bg=self.PANEL,
            troughcolor=self.BG,
            activebackground=self.PANEL_HOVER,
            relief="flat",
            bd=0,
        )
        scrollbar.pack(side="right", fill="y")

        self.log_text = tk.Text(
            log_frame,
            wrap="word",
            yscrollcommand=scrollbar.set,
            font=("Segoe UI", 10),
            state="disabled",
            bg=self.PANEL,
            fg=self.TEXT,
            insertbackground=self.TEXT,
            selectbackground=self.ACCENT,
            selectforeground=self.BG,
            bd=0,
            relief="flat",
            padx=14,
            pady=12,
            spacing1=3,
            spacing3=8,
        )
        self.log_text.pack(side="left", fill="both", expand=True)
        scrollbar.config(command=self.log_text.yview)
        self.log_text.tag_configure("timestamp", foreground=self.MUTED, font=("Consolas", 9))
        self.log_text.tag_configure("empty", foreground=self.MUTED, justify="center")

        footer = tk.Frame(self.root, bg=self.BG)
        footer.pack(fill="x", padx=24, pady=(0, 18))
        export_btn = self._make_button(
            footer,
            "Export CSV",
            self.export_csv,
            width=12,
            compact=True,
        )
        export_btn.pack(side="right")
        tk.Label(
            footer,
            text="- hide to tray   × exit",
            bg=self.BG,
            fg=self.MUTED,
            font=("Segoe UI", 8),
        ).pack(side="left")

        self.root.protocol("WM_DELETE_WINDOW", self.quit_app)
        self.root.bind("<Map>", lambda _event: self.root.update_idletasks())
        self.root.bind("<Alt-F4>", lambda _event: self.quit_app())

    def _build_title_bar(self):
        title_bar = tk.Frame(
            self.root,
            bg="#11161d",
            height=42,
            highlightbackground=self.BORDER,
            highlightthickness=0,
        )
        title_bar.pack(fill="x")
        title_bar.pack_propagate(False)

        brand = tk.Frame(title_bar, bg="#11161d")
        brand.pack(side="left", fill="y", padx=(16, 0))

        if self.title_icon_image is not None:
            mark = tk.Label(
                brand,
                image=self.title_icon_image,
                bg="#11161d",
                bd=0,
            )
            mark.pack(side="left", padx=(0, 8))
        else:
            mark = tk.Frame(brand, bg=self.ACCENT, width=8, height=8)
            mark.pack(side="left", padx=(0, 9))
            mark.pack_propagate(False)

        title = tk.Label(
            brand,
            text="Work Journal",
            bg="#11161d",
            fg=self.TEXT,
            font=("Segoe UI", 9, "bold"),
        )
        title.pack(side="left")

        controls = tk.Frame(title_bar, bg="#11161d")
        controls.pack(side="right", fill="y")

        minimize_btn = self._make_title_button(
            controls,
            "-",
            self._on_close,
            hover=self.PANEL_HOVER,
        )
        minimize_btn.pack(side="left", fill="y")

        close_btn = self._make_title_button(
            controls,
            "×",
            self.quit_app,
            hover="#b94752",
        )
        close_btn.pack(side="left", fill="y")

        for widget in (title_bar, brand, mark, title):
            widget.bind("<ButtonPress-1>", self._start_main_drag)
            widget.bind("<B1-Motion>", self._move_main_window)

    def _make_title_button(self, parent, text, command, hover):
        normal = "#11161d"
        button = tk.Button(
            parent,
            text=text,
            command=command,
            width=5,
            bg=normal,
            fg=self.MUTED,
            activebackground=hover,
            activeforeground=self.TEXT,
            relief="flat",
            bd=0,
            takefocus=False,
            cursor="hand2",
            font=("Segoe UI", 11),
        )
        button.bind("<Enter>", lambda _event: button.config(bg=hover, fg=self.TEXT))
        button.bind("<Leave>", lambda _event: button.config(bg=normal, fg=self.MUTED))
        return button

    def _start_main_drag(self, event):
        self._drag_offset_x = event.x_root - self.root.winfo_x()
        self._drag_offset_y = event.y_root - self.root.winfo_y()

    def _move_main_window(self, event):
        x = event.x_root - self._drag_offset_x
        y = event.y_root - self._drag_offset_y
        self.root.geometry(f"+{x}+{y}")

    def _make_button(self, parent, text, command, primary=False, width=12, compact=False):
        bg = self.ACCENT if primary else self.PANEL
        hover = self.ACCENT_HOVER if primary else self.PANEL_HOVER
        fg = self.BG if primary else self.TEXT
        button = tk.Button(
            parent,
            text=text,
            command=command,
            width=width,
            bg=bg,
            fg=fg,
            activebackground=hover,
            activeforeground=fg,
            disabledforeground=self.MUTED,
            relief="flat",
            bd=0,
            cursor="hand2",
            font=("Segoe UI", 9, "bold"),
            padx=8,
            pady=6 if compact else 9,
        )
        button.bind("<Enter>", lambda _event: button.config(bg=hover))
        button.bind("<Leave>", lambda _event: button.config(bg=bg))
        return button

    def _adjust_interval(self, amount):
        try:
            current = int(self.interval_var.get())
        except ValueError:
            current = self.interval_minutes
        self.interval_var.set(str(min(240, max(1, current + amount))))
        self._on_interval_change()

    # ---------- log rendering ----------

    def _render_log(self):
        self.count_label.config(
            text="1 entry" if len(self.entries) == 1
            else f"{len(self.entries)} entries"
        )
        self.log_text.config(state="normal")
        self.log_text.delete("1.0", "end")
        if not self.entries:
            self.log_text.insert("end", "No entries yet.", "empty")
        else:
            for e in reversed(self.entries):
                timestamp = f"{e.get('date', '')}  {e.get('time', '')}\n"
                self.log_text.insert("end", timestamp, "timestamp")
                self.log_text.insert("end", f"{e.get('activity', '')}\n")
        self.log_text.config(state="disabled")

    # ---------- tracking control ----------

    def toggle_running(self):
        if not self.running:
            # Read a manually entered value before starting the timer.
            self._on_interval_change()
            self.running = True
            self.start_btn.config(text="Pause")
            self.header_status.config(
                text="  ACTIVE  ",
                bg=self.ACCENT_DARK,
                fg=self.ACCENT,
            )
            self._schedule_next()
        else:
            self.running = False
            self.start_btn.config(text="Start")
            self.header_status.config(
                text="  PAUSED  ",
                bg=self.PANEL,
                fg=self.MUTED,
            )
            self._cancel_timers()
            self.status_label.config(text="TIMER PAUSED", fg=self.MUTED)
            self.clock_label.config(text="--:--", fg=self.TEXT)

    def _cancel_timers(self):
        if self.prompt_after_id:
            self.root.after_cancel(self.prompt_after_id)
            self.prompt_after_id = None
        if self.tick_after_id:
            self.root.after_cancel(self.tick_after_id)
            self.tick_after_id = None

    def _schedule_next(self):
        self._cancel_timers()
        ms = max(1, self.interval_minutes) * 60 * 1000
        self.next_time = datetime.datetime.now() + datetime.timedelta(milliseconds=ms)
        self.prompt_after_id = self.root.after(ms, self._trigger_prompt)
        self._tick()

    def _tick(self):
        if not self.running or self.next_time is None:
            return
        remaining = (self.next_time - datetime.datetime.now()).total_seconds()
        remaining = max(0, math.ceil(remaining))
        mm, ss = divmod(remaining, 60)
        self.status_label.config(text="NEXT CHECK-IN IN", fg=self.ACCENT)
        self.clock_label.config(text=f"{mm:02d}:{ss:02d}", fg=self.TEXT)
        self.tick_after_id = self.root.after(1000, self._tick)

    def _on_interval_change(self):
        try:
            v = int(self.interval_var.get())
            v = min(240, max(1, v))
        except ValueError:
            v = 15
        self.interval_minutes = v
        self.interval_var.set(str(v))
        save_config({"interval": v})
        if self.running:
            self._schedule_next()

    # ---------- the popup ----------

    def log_now(self):
        # Open a manual check-in and restart the interval if tracking is active.
        self._trigger_prompt()

    def _trigger_prompt(self):
        if self.popup is not None:
            self.popup.lift()
            self.popup.focus_force()
            if self.popup_entry is not None:
                self.popup_entry.focus_force()
            return  # Keep a single check-in window open.

        popup_width = 460
        popup_height = 280
        transparent = "#010203"

        self.popup = tk.Toplevel(self.root)
        self.popup.overrideredirect(True)
        self.popup.configure(bg=transparent)
        self.popup.attributes("-topmost", True)
        self.popup.resizable(False, False)
        try:
            self.popup.attributes("-transparentcolor", transparent)
        except tk.TclError:
            pass

        if self.root.state() != "withdrawn":
            self.popup.transient(self.root)

        x = (self.popup.winfo_screenwidth() - popup_width) // 2
        y = (self.popup.winfo_screenheight() - popup_height) // 2
        self.popup.geometry(f"{popup_width}x{popup_height}+{x}+{y}")

        canvas = tk.Canvas(
            self.popup,
            width=popup_width,
            height=popup_height,
            bg=transparent,
            highlightthickness=0,
            bd=0,
        )
        canvas.pack(fill="both", expand=True)
        self.popup_canvas = canvas

        self._rounded_rectangle(
            canvas,
            2,
            2,
            popup_width - 2,
            popup_height - 2,
            radius=20,
            fill="#111820",
            outline="#34404d",
            width=1,
        )
        self._create_popup_particles(canvas, popup_width, popup_height)

        canvas.create_text(
            popup_width // 2,
            43,
            text="CHECK-IN",
            fill=self.ACCENT,
            font=("Segoe UI", 8, "bold"),
        )
        canvas.create_text(
            popup_width // 2,
            76,
            text="What are you working on?",
            fill=self.TEXT,
            font=("Segoe UI", 15, "bold"),
        )

        entry = tk.Entry(
            self.popup,
            font=("Segoe UI", 10),
            bg=self.PANEL,
            fg=self.MUTED,
            insertbackground=self.TEXT,
            selectbackground=self.ACCENT,
            selectforeground=self.BG,
            relief="flat",
            highlightbackground=self.BORDER,
            highlightcolor=self.ACCENT,
            highlightthickness=1,
        )
        canvas.create_window(
            popup_width // 2,
            124,
            window=entry,
            width=390,
            height=43,
        )
        self.popup_entry = entry
        placeholder = "coding, testing, break, etc..."
        entry.insert(0, placeholder)
        self.popup_placeholder_active = True

        canvas.create_text(
            138,
            160,
            text="Press Enter to log",
            fill=self.MUTED,
            font=("Segoe UI", 8),
        )
        canvas.create_line(230, 153, 230, 167, fill=self.BORDER)
        canvas.create_text(
            322,
            160,
            text="Esc to skip",
            fill=self.MUTED,
            font=("Segoe UI", 8),
        )

        button_shape = self._rounded_rectangle(
            canvas,
            35,
            190,
            popup_width - 35,
            236,
            radius=9,
            fill=self.ACCENT,
            outline=self.ACCENT,
            tags=("log_button",),
        )
        canvas.create_text(
            popup_width // 2,
            213,
            text="LOG IT ->",
            fill=self.BG,
            font=("Segoe UI", 10, "bold"),
            tags=("log_button",),
        )

        def prepare_input(event):
            ignored_keys = {
                "Return", "Escape", "Tab", "Shift_L", "Shift_R",
                "Control_L", "Control_R", "Alt_L", "Alt_R",
                "Left", "Right", "Up", "Down", "Home", "End",
            }
            if self.popup_placeholder_active and event.keysym not in ignored_keys:
                entry.delete(0, "end")
                entry.config(fg=self.TEXT)
                self.popup_placeholder_active = False

        def restore_placeholder(_event=None):
            if not entry.get():
                entry.insert(0, placeholder)
                entry.config(fg=self.MUTED)
                self.popup_placeholder_active = True

        def finish(logit):
            if self.popup is None:
                return

            text = "" if self.popup_placeholder_active else entry.get().strip()
            if logit and not text:
                entry.config(highlightbackground="#e06c75", highlightcolor="#e06c75")
                entry.focus_force()
                self.popup.after(
                    500,
                    lambda: entry.config(
                        highlightbackground=self.BORDER,
                        highlightcolor=self.ACCENT,
                    ) if self.popup is not None else None,
                )
                return

            popup = self.popup
            if self.tray_icon is not None:
                self.tray_icon.unregister_escape_hotkey()
            if self.popup_particle_after_id is not None:
                try:
                    popup.after_cancel(self.popup_particle_after_id)
                except tk.TclError:
                    pass
            popup.destroy()
            self.popup = None
            self.popup_entry = None
            self.popup_canvas = None
            self.popup_particles = []
            self.popup_particle_after_id = None
            self.popup_placeholder_active = False
            self.popup_finish = None
            if logit and text:
                self._add_entry(text)
            if self.running:
                self._schedule_next()

        entry.bind("<KeyPress>", prepare_input, add="+")
        entry.bind("<FocusOut>", restore_placeholder)
        entry.bind("<Return>", lambda _event: finish(True))
        entry.bind("<Escape>", lambda _event: finish(False))
        self.popup.bind("<Escape>", lambda _event: finish(False))
        self.popup.bind(
            "<ButtonPress-1>",
            lambda _event: self.popup.after_idle(self._focus_popup) if self.popup else None,
            add="+",
        )
        canvas.tag_bind("log_button", "<Button-1>", lambda _event: finish(True))
        canvas.tag_bind(
            "log_button",
            "<Enter>",
            lambda _event: (
                canvas.itemconfig(button_shape, fill=self.ACCENT_HOVER, outline=self.ACCENT_HOVER),
                canvas.config(cursor="hand2"),
            ),
        )
        canvas.tag_bind(
            "log_button",
            "<Leave>",
            lambda _event: (
                canvas.itemconfig(button_shape, fill=self.ACCENT, outline=self.ACCENT),
                canvas.config(cursor=""),
            ),
        )

        self.popup.protocol("WM_DELETE_WINDOW", lambda: finish(False))
        self.popup_finish = finish
        if self.tray_icon is not None:
            self.tray_icon.register_escape_hotkey()
        self.popup.update_idletasks()
        self.popup.focus_force()
        entry.focus_force()
        self._animate_popup_particles()
        self.popup.after(150, self._focus_popup)

    def _focus_popup(self):
        if self.popup is None:
            return
        self.popup.attributes("-topmost", True)
        self.popup.lift()
        self.popup.focus_force()
        if self.popup_entry is not None:
            self.popup_entry.focus_force()

    def skip_popup(self):
        if self.popup_finish is not None:
            self.popup_finish(False)

    @staticmethod
    def _rounded_rectangle(canvas, x1, y1, x2, y2, radius=12, **kwargs):
        points = [
            x1 + radius, y1,
            x2 - radius, y1,
            x2, y1,
            x2, y1 + radius,
            x2, y2 - radius,
            x2, y2,
            x2 - radius, y2,
            x1 + radius, y2,
            x1, y2,
            x1, y2 - radius,
            x1, y1 + radius,
            x1, y1,
        ]
        return canvas.create_polygon(
            points,
            smooth=True,
            splinesteps=24,
            **kwargs,
        )

    def _create_popup_particles(self, canvas, width, height):
        colors = ("#1b332f", "#21333a", "#284039", "#23313e")
        self.popup_particles = []
        for _ in range(26):
            size = random.choice((1, 1, 2))
            x = random.randint(22, width - 22)
            y = random.randint(18, height - 18)
            particle_id = canvas.create_oval(
                x,
                y,
                x + size,
                y + size,
                fill=random.choice(colors),
                outline="",
            )
            self.popup_particles.append({
                "id": particle_id,
                "dx": random.uniform(-0.10, 0.10),
                "dy": -random.uniform(0.18, 0.45),
                "size": size,
            })

    def _animate_popup_particles(self):
        if self.popup is None or self.popup_canvas is None:
            return

        canvas = self.popup_canvas
        width = int(canvas.cget("width"))
        height = int(canvas.cget("height"))
        for particle in self.popup_particles:
            canvas.move(particle["id"], particle["dx"], particle["dy"])
            coords = canvas.coords(particle["id"])
            if not coords:
                continue
            if coords[3] < 16 or coords[2] < 16 or coords[0] > width - 16:
                x = random.randint(22, width - 22)
                y = height - random.randint(14, 26)
                size = particle["size"]
                canvas.coords(particle["id"], x, y, x + size, y + size)

        self.popup_particle_after_id = self.popup.after(40, self._animate_popup_particles)

    def _add_entry(self, text):
        now = datetime.datetime.now()
        entry = {
            "date": now.strftime("%Y-%m-%d"),
            "time": now.strftime("%H:%M"),
            "activity": text,
            "timestamp": now.isoformat(timespec="seconds"),
        }
        self.entries.append(entry)
        append_entry_to_file(entry)
        self._render_log()

    # ---------- export ----------

    def export_csv(self):
        path = filedialog.asksaveasfilename(
            defaultextension=".csv",
            filetypes=[("CSV fajl", "*.csv")],
            initialfile="work_journal_export.csv",
        )
        if not path:
            return
        try:
            with open(path, "w", newline="", encoding="utf-8-sig") as f:
                writer = csv.writer(f)
                writer.writerow(["Date", "Time", "Activity"])
                for e in sorted(self.entries, key=lambda x: x.get("timestamp", "")):
                    writer.writerow([e.get("date", ""), e.get("time", ""), e.get("activity", "")])
            messagebox.showinfo("Export complete", f"Saved to:\n{path}")
        except OSError as e:
            messagebox.showerror("Error", f"Could not export the file:\n{e}")

    def _on_close(self):
        if self.is_quitting:
            self._cancel_timers()
            if self.tray_icon is not None:
                self.tray_icon.destroy()
            self.root.destroy()
            return

        self.root.withdraw()

    def show_main_window(self):
        self.root.deiconify()
        self.root.state("normal")
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        self.root.lift()
        self.root.focus_force()
        self.root.after(300, lambda: self.root.attributes("-topmost", False))

    def quit_app(self):
        self.is_quitting = True
        self._cancel_timers()
        if self.popup is not None:
            self.popup.destroy()
            self.popup = None
        if self.tray_icon is not None:
            self.tray_icon.destroy()
        self.root.destroy()


def main():
    kernel32 = ctypes.windll.kernel32
    user32 = ctypes.windll.user32
    kernel32.CreateMutexW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR]
    kernel32.CreateMutexW.restype = wintypes.HANDLE
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL
    user32.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
    user32.FindWindowW.restype = wintypes.HWND
    user32.PostMessageW.argtypes = [
        wintypes.HWND,
        wintypes.UINT,
        ctypes.c_size_t,
        ctypes.c_ssize_t,
    ]
    user32.PostMessageW.restype = wintypes.BOOL

    mutex = kernel32.CreateMutexW(None, False, SINGLE_INSTANCE_MUTEX)
    if mutex and kernel32.GetLastError() == ERROR_ALREADY_EXISTS:
        existing_window = user32.FindWindowW(
            "WorkJournalTrayWindow",
            None,
        )
        if existing_window:
            user32.PostMessageW(
                existing_window,
                WindowsTrayIcon.WM_COMMAND,
                WindowsTrayIcon.RESTORE_ID,
                0,
            )
        kernel32.CloseHandle(mutex)
        return

    root = tk.Tk()
    app = WorkJournalApp(root)
    try:
        root.mainloop()
    finally:
        if mutex:
            kernel32.CloseHandle(mutex)


if __name__ == "__main__":
    main()
