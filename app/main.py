from __future__ import annotations

import json
import os
import platform
import queue
import sys
import threading
import time
import traceback
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable, Optional

import tkinter as tk
from tkinter import filedialog, messagebox, ttk

try:
    import psutil
except ImportError:  # pragma: no cover - setup error is shown in the UI
    psutil = None

try:
    import pyperclip
except ImportError:  # pragma: no cover
    pyperclip = None

if getattr(sys, "frozen", False):
    # In a PyInstaller one-folder build, keep user files beside the EXE.
    APP_DIR = Path(sys.executable).resolve().parent
else:
    APP_DIR = Path(__file__).resolve().parent.parent
MODELS_DIR = APP_DIR / "models"
CONFIG_PATH = APP_DIR / "config.json"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765


def clean_model_output(text: str) -> str:
    """Return only usable output, removing wrapper fences and common filler."""
    lines = str(text or "").strip().splitlines()
    while lines and lines[0].strip().startswith("```"):
        lines.pop(0)
    while lines and lines[-1].strip() == "```":
        lines.pop()
    filler = {
        "here is the code:",
        "here's the code:",
        "here is the corrected code:",
        "here is the continuation:",
        "corrected code:",
        "continuation:",
    }
    while lines and lines[0].strip().lower() in filler:
        lines.pop(0)
    return "\n".join(lines).strip()


@dataclass
class HardwareProfile:
    system: str
    release: str
    machine: str
    processor: str
    ram_gb: float
    cpu_logical: int
    cpu_physical: int
    screen_width: int
    screen_height: int
    scaling: float
    selected_threads: int
    context_size: int
    batch_size: int


def detect_hardware(root: Optional[tk.Tk] = None) -> HardwareProfile:
    """Detect the host and choose conservative settings that fit low-RAM devices."""
    ram_bytes = psutil.virtual_memory().total if psutil else 8 * 1024**3
    ram_gb = round(ram_bytes / 1024**3, 2)
    logical = psutil.cpu_count(logical=True) if psutil else (os.cpu_count() or 4)
    physical = psutil.cpu_count(logical=False) if psutil else max(1, logical // 2)
    logical = max(1, logical or 1)
    physical = max(1, physical or 1)

    # Leave resources for Windows, the GUI, and the target app receiving output.
    threads = max(1, min(8, logical - 1 if logical > 2 else logical))
    if ram_gb <= 6:
        context, batch = 1536, 64
    elif ram_gb <= 10:
        context, batch = 2048, 96
    elif ram_gb <= 16:
        context, batch = 3072, 128
    else:
        context, batch = 4096, 192

    width = height = 0
    scaling = 1.0
    if root is not None:
        try:
            width, height = root.winfo_screenwidth(), root.winfo_screenheight()
            scaling = float(root.tk.call("tk", "scaling"))
        except Exception:
            pass

    return HardwareProfile(
        system=platform.system(),
        release=platform.release(),
        machine=platform.machine(),
        processor=platform.processor(),
        ram_gb=ram_gb,
        cpu_logical=logical,
        cpu_physical=physical,
        screen_width=width,
        screen_height=height,
        scaling=round(scaling, 2),
        selected_threads=threads,
        context_size=context,
        batch_size=batch,
    )


def load_config() -> dict[str, Any]:
    defaults = {
        "model_path": "",
        "host": DEFAULT_HOST,
        "port": DEFAULT_PORT,
        "opacity": 0.94,
        "always_on_top": True,
        "capture_dot": True,
        "output_mode": "paste",
        "strict_mode": True,
        "ask_mode": False,
        "start_minimized": False,
        "capture_u_key": True,
        "selection_key": "u",
        "selection_action": "fix",
    }
    if CONFIG_PATH.exists():
        try:
            loaded = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            defaults.update(loaded)
        except Exception:
            pass
    return defaults


def save_config(config: dict[str, Any]) -> None:
    CONFIG_PATH.write_text(json.dumps(config, indent=2), encoding="utf-8")


def discover_models() -> list[Path]:
    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    return sorted(MODELS_DIR.glob("*.gguf"), key=lambda p: p.stat().st_size)


def choose_model(config: dict[str, Any], profile: HardwareProfile) -> Optional[Path]:
    explicit = str(config.get("model_path", "")).strip()
    if explicit:
        path = Path(explicit).expanduser()
        if path.exists() and path.suffix.lower() == ".gguf":
            return path
    candidates = discover_models()
    if not candidates:
        return None
    # Prefer models whose file size is under a conservative RAM budget.
    budget = max(1.0, profile.ram_gb * 0.52) * 1024**3
    safe = [p for p in candidates if p.stat().st_size <= budget]
    return (safe or candidates[:1])[-1]


STRICT_SYSTEM = (
    "You are a local desktop coding and productivity assistant. "
    "Return only the requested result. Do not add greetings, introductions, "
    "explanations, filler, apologies, or phrases like 'here is the code'. "
    "If code is requested, output code only without Markdown fences unless the user asks for them. "
    "If a short answer is requested, output only that answer. Preserve the user's language."
)
ASK_SYSTEM = (
    "You are a concise local desktop assistant. Answer directly and accurately. "
    "Avoid unnecessary preambles and filler. Preserve the user's language."
)


class LocalModel:
    def __init__(self, profile: HardwareProfile, config: dict[str, Any]):
        self.profile = profile
        self.config = config
        self.model = None
        self.model_path: Optional[Path] = None
        self.lock = threading.RLock()
        self.loading = False
        self.last_error = ""

    def load(self) -> tuple[bool, str]:
        with self.lock:
            if self.model is not None:
                return True, f"Loaded {self.model_path.name}"
            if self.loading:
                return False, "Model is still loading"
            self.loading = True
        try:
            from llama_cpp import Llama
            path = choose_model(self.config, self.profile)
            if path is None:
                raise FileNotFoundError(
                    f"No .gguf model found. Copy a GGUF file into: {MODELS_DIR}"
                )
            # Model-aware safety tuning: reserve memory for Windows and the GUI.
            # Larger GGUF files get a smaller context/batch on low-RAM machines.
            model_gb = path.stat().st_size / 1024**3
            context = self.profile.context_size
            batch = self.profile.batch_size
            if self.profile.ram_gb <= 8 and model_gb >= 3.5:
                context, batch = min(context, 1536), min(batch, 64)
            elif self.profile.ram_gb <= 12 and model_gb >= 6.0:
                context, batch = min(context, 2048), min(batch, 96)
            model = Llama(
                model_path=str(path),
                n_ctx=context,
                n_threads=self.profile.selected_threads,
                n_batch=batch,
                n_gpu_layers=0,
                verbose=False,
            )
            with self.lock:
                self.model = model
                self.model_path = path
                self.last_error = ""
            return True, f"Loaded {path.name}"
        except Exception as exc:
            with self.lock:
                self.last_error = f"{type(exc).__name__}: {exc}"
            return False, self.last_error
        finally:
            with self.lock:
                self.loading = False

    def complete(self, prompt: str, strict: bool, ask_mode: bool) -> str:
        ok, status = self.load()
        if not ok:
            raise RuntimeError(status)
        system = ASK_SYSTEM if ask_mode else (STRICT_SYSTEM if strict else ASK_SYSTEM)
        with self.lock:
            result = self.model.create_chat_completion(
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.15 if strict else 0.35,
                top_p=0.9,
                max_tokens=max(256, self.profile.context_size // 2),
            )
        choices = result.get("choices", [])
        if not choices:
            return ""
        message = choices[0].get("message", {})
        return str(message.get("content", "")).strip()

    def set_model_path(self, path: Path) -> None:
        with self.lock:
            self.model = None
            self.model_path = path
            self.config["model_path"] = str(path)
            save_config(self.config)

    def model_id(self) -> str:
        return self.model_path.name if self.model_path else "local-gguf"


class TargetWindow:
    """Tracks the most recent non-LocalFloatAI Windows window."""

    def __init__(self, own_pid: int):
        self.own_pid = own_pid
        self._hwnd = None
        self._running = platform.system() == "Windows"
        self._thread: Optional[threading.Thread] = None
        if self._running:
            self._thread = threading.Thread(target=self._track, daemon=True)
            self._thread.start()

    def _track(self) -> None:
        import ctypes
        user32 = ctypes.windll.user32
        get_pid = user32.GetWindowThreadProcessId
        get_pid.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulong)]
        while self._running:
            hwnd = user32.GetForegroundWindow()
            if hwnd:
                pid = ctypes.c_ulong()
                get_pid(hwnd, ctypes.byref(pid))
                if pid.value != self.own_pid:
                    self._hwnd = hwnd
            time.sleep(0.15)

    def activate(self) -> None:
        if platform.system() != "Windows" or not self._hwnd:
            return
        import ctypes
        user32 = ctypes.windll.user32
        user32.ShowWindow(self._hwnd, 5)
        user32.SetForegroundWindow(self._hwnd)
        time.sleep(0.12)

    def stop(self) -> None:
        self._running = False


class OutputController:
    @staticmethod
    def paste(text: str, target: Optional[TargetWindow] = None) -> None:
        if target:
            target.activate()
        if pyperclip is None:
            raise RuntimeError("pyperclip is not installed")
        pyperclip.copy(text)
        time.sleep(0.08)
        if platform.system() == "Windows":
            import ctypes
            VK_CONTROL, VK_V = 0x11, 0x56
            KEYEVENTF_KEYUP = 0x0002
            ctypes.windll.user32.keybd_event(VK_CONTROL, 0, 0, 0)
            ctypes.windll.user32.keybd_event(VK_V, 0, 0, 0)
            ctypes.windll.user32.keybd_event(VK_V, 0, KEYEVENTF_KEYUP, 0)
            ctypes.windll.user32.keybd_event(VK_CONTROL, 0, KEYEVENTF_KEYUP, 0)
        else:
            import subprocess
            subprocess.run(["xdotool", "key", "ctrl+v"], check=False)

    @staticmethod
    def type_text(text: str, interval: float = 0.004, target: Optional[TargetWindow] = None) -> None:
        if target:
            target.activate()
        # pyautogui uses the OS keyboard events on Windows and is more reliable
        # than manually synthesizing scan codes for punctuation and shifted keys.
        try:
            import pyautogui
            if any(ord(char) > 0x7F for char in text):
                OutputController.paste(text)
                return
            pyautogui.write(text, interval=interval)
        except Exception as exc:
            raise RuntimeError("Keyboard typing requires pyautogui; use paste mode if it is unavailable") from exc


class GlobalDotKey:
    def __init__(self, callback: Callable[[], None], status: Callable[[str], None]):
        self.callback = callback
        self.status = status
        self.backend = "none"
        self.listener = None

    def start(self) -> None:
        if platform.system() != "Windows":
            self.status("Global dot key is available in the Windows build")
            return
        try:
            import keyboard
            keyboard.add_hotkey(".", self.callback, suppress=True, trigger_on_release=True)
            self.backend = "keyboard"
            self.status("Global dot key: ON")
            return
        except Exception as exc:
            self.status(f"Global hotkey unavailable: {exc}")
        try:
            from pynput import keyboard as pynput_keyboard
            self.listener = pynput_keyboard.Listener(on_release=self._pynput_release)
            self.listener.daemon = True
            self.listener.start()
            self.backend = "pynput"
            self.status("Global dot key: ON (fallback; period may also appear)")
        except Exception as exc:
            self.status(f"Global hotkey unavailable: {exc}")

    def _pynput_release(self, key: Any) -> None:
        try:
            if getattr(key, "char", None) == ".":
                self.callback()
        except Exception:
            pass

    def stop(self) -> None:
        if self.backend == "keyboard":
            try:
                import keyboard
                keyboard.remove_hotkey(".")
            except Exception:
                pass
        if self.listener is not None:
            self.listener.stop()


class GlobalSelectionKey:
    def __init__(self, callback: Callable[[], None], status: Callable[[str], None], key_name: str = "u"):
        self.callback = callback
        self.status = status
        self.key_name = self.normalize(key_name)
        self.backend = "none"
        self.listener = None

    @staticmethod
    def normalize(key_name: str) -> str:
        key = str(key_name or "u").strip().lower()
        aliases = {"arrowup": "up", "uparrow": "up", "return": "enter", "esc": "escape", "spacebar": "space"}
        return aliases.get(key, key)

    def start(self) -> None:
        if platform.system() != "Windows":
            self.status(f"{self.key_name} selected-text capture is available in the Windows build")
            return
        try:
            import keyboard
            keyboard.add_hotkey(self.key_name, self.callback, suppress=True, trigger_on_release=True)
            self.backend = "keyboard"
            self.status(f"{self.key_name.upper()} key: ON")
        except Exception as exc:
            self.status(f"Custom hotkey unavailable: {exc}")

    def set_key(self, key_name: str) -> None:
        was_active = self.backend == "keyboard"
        self.stop()
        self.key_name = self.normalize(key_name)
        if was_active:
            self.start()

    def stop(self) -> None:
        if self.backend == "keyboard":
            try:
                import keyboard
                keyboard.remove_hotkey(self.key_name)
            except Exception:
                pass
        self.backend = "none"
        if self.listener is not None:
            self.listener.stop()
            self.listener = None


class LocalApiServer:
    def __init__(self, app: "FloatingAI"):
        self.app = app
        self.server = None
        self.thread: Optional[threading.Thread] = None

    def start(self) -> None:
        try:
            from fastapi import FastAPI, HTTPException
            from fastapi.middleware.cors import CORSMiddleware
            from pydantic import BaseModel
            import uvicorn
        except Exception as exc:
            self.app.set_status(f"API unavailable: {exc}")
            return

        api = FastAPI(title="LocalFloatAI API", version="1.0.0")
        api.add_middleware(
            CORSMiddleware,
            allow_origins=["http://127.0.0.1", "http://localhost"],
            allow_methods=["GET", "POST"],
            allow_headers=["*"],
        )

        class ChatRequest(BaseModel):
            model: Optional[str] = None
            messages: list[dict[str, Any]]
            temperature: Optional[float] = None
            max_tokens: Optional[int] = None
            stream: Optional[bool] = False

        @api.get("/health")
        def health() -> dict[str, Any]:
            return {"ok": True, "model_loaded": self.app.engine.model is not None}

        @api.get("/v1/models")
        def models() -> dict[str, Any]:
            now = int(time.time())
            return {"object": "list", "data": [{"id": self.app.engine.model_id(), "object": "model", "created": now, "owned_by": "local"}]}

        @api.post("/v1/chat/completions")
        def chat(req: ChatRequest) -> dict[str, Any]:
            user_messages = [m for m in req.messages if m.get("role") == "user"]
            if not user_messages:
                raise HTTPException(status_code=400, detail="At least one user message is required")
            prompt = str(user_messages[-1].get("content", ""))
            strict = self.app.config.get("strict_mode", True)
            ask_mode = self.app.config.get("ask_mode", False)
            try:
                content = self.app.engine.complete(prompt, strict=strict, ask_mode=ask_mode)
            except Exception as exc:
                raise HTTPException(status_code=503, detail=str(exc)) from exc
            return {
                "id": f"chatcmpl-local-{int(time.time() * 1000)}",
                "object": "chat.completion",
                "created": int(time.time()),
                "model": req.model or self.app.engine.model_id(),
                "choices": [{"index": 0, "message": {"role": "assistant", "content": content}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
            }

        def run() -> None:
            config = uvicorn.Config(api, host=self.app.config.get("host", DEFAULT_HOST), port=int(self.app.config.get("port", DEFAULT_PORT)), log_level="warning")
            self.server = uvicorn.Server(config)
            self.server.run()

        self.thread = threading.Thread(target=run, name="LocalApiServer", daemon=True)
        self.thread.start()
        self.app.set_status(f"API: http://{self.app.config.get('host', DEFAULT_HOST)}:{self.app.config.get('port', DEFAULT_PORT)}")

    def stop(self) -> None:
        if self.server:
            self.server.should_exit = True


class FloatingAI:
    def __init__(self) -> None:
        self.config = load_config()
        self.root = tk.Tk()
        self.root.title("LocalFloatAI")
        self.root.resizable(False, False)
        self.root.attributes("-topmost", bool(self.config.get("always_on_top", True)))
        self.root.attributes("-alpha", float(self.config.get("opacity", 0.94)))
        self.root.protocol("WM_DELETE_WINDOW", self.hide)
        self.profile = detect_hardware(self.root)
        self.engine = LocalModel(self.profile, self.config)
        self.api = LocalApiServer(self)
        self.hotkey = GlobalDotKey(self.capture_new_request, self.set_status)
        self.selection_hotkey = GlobalSelectionKey(self.capture_selected_text, self.set_status, self.config.get("selection_key", "u"))
        self.target_window = TargetWindow(os.getpid())
        self.screen_context = ""
        self.jobs: queue.Queue[tuple[str, Callable[[], Any]]] = queue.Queue()
        self._drag = (0, 0)
        self._build_ui()
        self.api.start()
        if self.config.get("capture_dot", True):
            self.hotkey.start()
        if self.config.get("capture_u_key", True):
            self.selection_hotkey.start()
        self.root.after(100, self._poll_jobs)
        self.root.after(400, self._load_model_background)
        self._position_window()
        if self.config.get("start_minimized", False):
            self.hide()

    def _build_ui(self) -> None:
        self.root.configure(bg="#10131a")
        outer = tk.Frame(self.root, bg="#10131a", padx=8, pady=6)
        outer.pack(fill="both", expand=True)

        bar = tk.Frame(outer, bg="#10131a", cursor="fleur")
        bar.pack(fill="x")
        title = tk.Label(bar, text="LocalFloatAI", bg="#10131a", fg="#8ed1fc", font=("Segoe UI", 9, "bold"))
        title.pack(side="left")
        self.status_var = tk.StringVar(value="Detecting hardware…")
        tk.Label(bar, textvariable=self.status_var, bg="#10131a", fg="#9aa4b2", font=("Segoe UI", 8)).pack(side="left", padx=10)
        ttk.Button(bar, text="Screen OCR", command=self.capture_screen_text).pack(side="right", padx=(4, 0))
        ttk.Button(bar, text="Import GGUF", command=self.import_model).pack(side="right", padx=(4, 0))
        ttk.Button(bar, text="⚙", width=3, command=self.show_settings).pack(side="right")
        ttk.Button(bar, text="×", width=3, command=self.hide).pack(side="right", padx=(4, 0))
        for widget in (bar, title):
            widget.bind("<ButtonPress-1>", self._drag_start)
            widget.bind("<B1-Motion>", self._drag_move)

        row = tk.Frame(outer, bg="#10131a")
        row.pack(fill="x", pady=(5, 0))
        self.prompt = tk.Entry(row, bg="#1d2430", fg="#f4f7fb", insertbackground="#f4f7fb", relief="flat", font=("Segoe UI", 11), width=70)
        self.prompt.pack(side="left", fill="x", expand=True, ipady=7)
        self.prompt.bind("<Return>", lambda _event: self.send_request())
        ttk.Button(row, text="Send .", command=self.send_request).pack(side="left", padx=(6, 0), ipady=2)
        self.mode_var = tk.StringVar(value=self.config.get("output_mode", "paste"))
        self.selection_action_var = tk.StringVar(value=self.config.get("selection_action", "fix"))
        mode_box = ttk.Combobox(row, textvariable=self.mode_var, values=("paste", "type"), state="readonly", width=8)
        mode_box.pack(side="left", padx=(6, 0))
        mode_box.bind("<<ComboboxSelected>>", lambda _event: self._save_flags())

        selection_row = tk.Frame(outer, bg="#10131a")
        selection_row.pack(fill="x", pady=(5, 0))
        tk.Label(selection_row, text="Selection action:", bg="#10131a", fg="#9aa4b2", font=("Segoe UI", 8)).pack(side="left")
        selection_box = ttk.Combobox(selection_row, textvariable=self.selection_action_var, values=("fix", "continue"), state="readonly", width=10)
        selection_box.pack(side="left", padx=(6, 0))
        selection_box.bind("<<ComboboxSelected>>", lambda _event: self._save_flags())
        tk.Label(selection_row, text="Select code/text, then press your custom key", bg="#10131a", fg="#7f8b9b", font=("Segoe UI", 8)).pack(side="left", padx=8)

        options = tk.Frame(outer, bg="#10131a")
        options.pack(fill="x", pady=(5, 0))
        self.strict_var = tk.BooleanVar(value=bool(self.config.get("strict_mode", True)))
        self.ask_var = tk.BooleanVar(value=bool(self.config.get("ask_mode", False)))
        self.capture_var = tk.BooleanVar(value=bool(self.config.get("capture_dot", True)))
        tk.Checkbutton(options, text="Strict output", variable=self.strict_var, command=self._save_flags, bg="#10131a", fg="#c8d2df", selectcolor="#263042", activebackground="#10131a", activeforeground="#ffffff").pack(side="left")
        tk.Checkbutton(options, text="Ask mode", variable=self.ask_var, command=self._save_flags, bg="#10131a", fg="#c8d2df", selectcolor="#263042", activebackground="#10131a", activeforeground="#ffffff").pack(side="left", padx=8)
        tk.Checkbutton(options, text="Global dot", variable=self.capture_var, command=self.toggle_hotkey, bg="#10131a", fg="#c8d2df", selectcolor="#263042", activebackground="#10131a", activeforeground="#ffffff").pack(side="left")
        self.root.bind("<Escape>", lambda _event: self.hide())

    def _copy_active_selection(self) -> str:
        """Copy selected content without inserting the trigger key into the target."""
        if platform.system() != "Windows":
            raise RuntimeError("Selection capture is available in the Windows build")
        if pyperclip is None:
            raise RuntimeError("Clipboard support is unavailable")
        import pyautogui
        if self.target_window:
            self.target_window.activate()
        pyautogui.hotkey("ctrl", "c")
        time.sleep(0.18)
        return str(pyperclip.paste() or "")

    def capture_new_request(self) -> None:
        """Period key: copy a selected user request and generate its answer."""
        try:
            prompt = self._copy_active_selection().strip()
        except Exception as exc:
            self.set_status(f"Request copy error: {exc}")
            return
        if not prompt:
            self.set_status("Select a new request first")
            return
        self.screen_context = ""
        self.set_status("New request…")
        mode = self.mode_var.get()
        strict, ask = self.strict_var.get(), self.ask_var.get()
        threading.Thread(target=self._run_and_callback, args=(
            lambda: self.engine.complete(prompt, strict=strict, ask_mode=ask),
            lambda result: self._finish_output(result, mode),
        ), daemon=True).start()

    def capture_selected_text(self) -> None:
        """Custom selection key: copy selected text, then Fix or Continue it."""
        try:
            selected = self._copy_active_selection().strip()
        except Exception as exc:
            self.set_status(f"Selection copy error: {exc}")
            return
        if not selected:
            self.set_status("No text selected")
            return
        action = self.selection_action_var.get()
        if action == "continue":
            instruction = (
                "Continue the selected text or code from exactly where it ends. "
                "Return only the continuation. Do not repeat the selected content, "
                "do not explain, and do not use Markdown fences.\n\nSELECTED CONTENT:\n"
            )
        else:
            instruction = (
                "Fix the selected code. Return only the complete corrected code, "
                "without explanation, comments about the changes, or Markdown fences. "
                "Preserve the intended language and behavior.\n\nCODE TO FIX:\n"
            )
        prompt = instruction + selected
        self.set_status(f"{action.title()} selected text…")
        mode = self.mode_var.get()
        threading.Thread(target=self._run_and_callback, args=(
            lambda: self.engine.complete(prompt, strict=True, ask_mode=False),
            lambda result: self._finish_output(result, mode),
        ), daemon=True).start()

    def _finish_output(self, result: Any, mode: str) -> None:
        if isinstance(result, Exception):
            self.set_status(f"Error: {result}")
            self.show()
            return
        result_text = clean_model_output(str(result))
        was_capturing = self.capture_var.get()
        try:
            self.hide()
            if mode == "type":
                if was_capturing:
                    self.hotkey.stop()
                try:
                    OutputController.type_text(result_text, target=self.target_window)
                finally:
                    if was_capturing:
                        self.hotkey.start()
            else:
                OutputController.paste(result_text, target=self.target_window)
            self.set_status("Selected text processed")
            self.root.after(180, self.show)
        except Exception as exc:
            if mode == "type" and was_capturing:
                self.hotkey.start()
            self.set_status(f"Output error: {exc}")
            self._show_result(str(result))

    def capture_screen_text(self) -> None:
        """Capture the desktop without this GUI and OCR text only."""
        if platform.system() != "Windows":
            self.set_status("Screen OCR is available in the Windows build")
            return
        self.set_status("Reading screen text…")
        threading.Thread(target=self._ocr_worker, daemon=True).start()

    def _ocr_worker(self) -> None:
        was_visible = True
        try:
            from PIL import Image
            import mss
            import pytesseract
            import tempfile
            import shutil

            # Hide the overlay first so the compositor does not place its text
            # into the screenshot. The underlying target app becomes visible.
            self.root.after(0, self.hide)
            time.sleep(0.22)
            with mss.mss() as shot:
                monitor = shot.monitors[0]
                raw = shot.grab(monitor)
                image = Image.frombytes("RGB", raw.size, raw.rgb)
            # Use the bundled OCR runtime when present, then fall back to PATH.
            bundled = APP_DIR / "ocr" / "tesseract.exe"
            if bundled.exists():
                pytesseract.pytesseract.tesseract_cmd = str(bundled)
            else:
                pytesseract.pytesseract.tesseract_cmd = shutil.which("tesseract") or "tesseract"
            text = pytesseract.image_to_string(image, config="--psm 6").strip()
            self.root.after(0, lambda: self._ocr_done(text))
        except Exception as exc:
            self.root.after(0, lambda: self._ocr_failed(exc))

    def _ocr_done(self, text: str) -> None:
        self.show()
        if not text:
            self.set_status("No screen text detected")
            return
        self.screen_context = text
        if pyperclip:
            pyperclip.copy(text)
        self.set_status("Screen text captured; type a request")
        self.prompt.delete(0, "end")
        self.prompt.insert(0, "Use the captured screen text for my next request")

    def _ocr_failed(self, exc: Exception) -> None:
        self.show()
        self.set_status(f"OCR error: {exc}")

    def import_model(self) -> None:
        path = filedialog.askopenfilename(
            title="Import local GGUF model",
            filetypes=[("GGUF model", "*.gguf"), ("All files", "*.*")],
        )
        if not path:
            return
        selected = Path(path).expanduser().resolve()
        if selected.suffix.lower() != ".gguf":
            messagebox.showerror("Invalid model", "Please select a .gguf model file.")
            return
        self.engine.set_model_path(selected)
        self.set_status(f"Imported: {selected.name}; loading…")
        self.jobs.put((f"Loading {selected.name}…", self.engine.load))

    def _position_window(self) -> None:
        self.root.update_idletasks()
        w, h = self.root.winfo_width(), self.root.winfo_height()
        x = max(0, (self.profile.screen_width - w) // 2) if self.profile.screen_width else 100
        y = max(0, self.profile.screen_height - h - 90) if self.profile.screen_height else 100
        self.root.geometry(f"{w}x{h}+{x}+{y}")

    def _drag_start(self, event: tk.Event) -> None:
        self._drag = (event.x_root - self.root.winfo_x(), event.y_root - self.root.winfo_y())

    def _drag_move(self, event: tk.Event) -> None:
        dx, dy = self._drag
        self.root.geometry(f"+{event.x_root - dx}+{event.y_root - dy}")

    def _save_flags(self) -> None:
        self.config.update({"strict_mode": self.strict_var.get(), "ask_mode": self.ask_var.get(), "output_mode": self.mode_var.get(), "selection_action": self.selection_action_var.get()})
        save_config(self.config)

    def toggle_hotkey(self) -> None:
        self._save_flags()
        self.hotkey.stop()
        if self.capture_var.get():
            self.hotkey.start()
        else:
            self.set_status("Global dot: OFF")

    def _load_model_background(self) -> None:
        self.jobs.put(("Loading model…", self.engine.load))

    def _poll_jobs(self) -> None:
        try:
            label, fn = self.jobs.get_nowait()
        except queue.Empty:
            self.root.after(100, self._poll_jobs)
            return
        self.set_status(label)

        def worker() -> None:
            try:
                result = fn()
                self.root.after(0, lambda: self._job_done(result))
            except Exception as exc:
                self.root.after(0, lambda: self._job_done(exc))

        threading.Thread(target=worker, daemon=True).start()
        self.root.after(100, self._poll_jobs)

    def _job_done(self, result: Any) -> None:
        if isinstance(result, Exception):
            self.set_status(f"Error: {result}")
        elif isinstance(result, tuple):
            self.set_status(str(result[1]))
        else:
            self.set_status(str(result))

    def send_request(self) -> None:
        prompt = self.prompt.get().strip()
        if not prompt:
            return
        self.prompt.delete(0, "end")
        self.set_status("Thinking…")
        strict, ask = self.strict_var.get(), self.ask_var.get()
        mode = self.mode_var.get()

        def work() -> str:
            effective_prompt = prompt
            if self.screen_context:
                effective_prompt += "\n\nSCREEN TEXT CONTEXT (text-only OCR):\n" + self.screen_context
            return self.engine.complete(effective_prompt, strict=strict, ask_mode=ask)

        def done(result: Any) -> None:
            if isinstance(result, Exception):
                self.set_status(f"Error: {result}")
                self.show()
                return

            result_text = clean_model_output(str(result))
            was_capturing = self.capture_var.get()
            try:
                # Temporarily hide only while output is delivered to the previous
                # foreground app. The process and API remain alive.
                self.hide()
                if mode == "type":
                    # Generated periods must not re-trigger the global send key.
                    if was_capturing:
                        self.hotkey.stop()
                    try:
                        OutputController.type_text(result_text, target=self.target_window)
                    finally:
                        if was_capturing:
                            self.hotkey.start()
                else:
                    OutputController.paste(result_text, target=self.target_window)
                self.set_status("Done")
                # Keep the assistant visibly available after paste/type completes.
                self.root.after(180, self.show)
            except Exception as exc:
                if mode == "type" and was_capturing:
                    self.hotkey.start()
                self.set_status(f"Output error: {exc}")
                self._show_result(result_text)

        threading.Thread(target=self._run_and_callback, args=(work, done), daemon=True).start()

    def _run_and_callback(self, work: Callable[[], Any], done: Callable[[Any], None]) -> None:
        try:
            result = work()
        except Exception as exc:
            traceback.print_exc()
            result = exc
        self.root.after(0, lambda: done(result))

    def _show_result(self, text: str) -> None:
        self.root.deiconify()
        win = tk.Toplevel(self.root)
        win.title("LocalFloatAI result")
        win.attributes("-topmost", True)
        win.geometry("700x420")
        box = tk.Text(win, bg="#10131a", fg="#f4f7fb", insertbackground="#f4f7fb", wrap="word", font=("Consolas", 10))
        box.pack(fill="both", expand=True, padx=8, pady=8)
        box.insert("1.0", text)
        box.configure(state="disabled")
        ttk.Button(win, text="Copy", command=lambda: pyperclip.copy(text) if pyperclip else None).pack(pady=(0, 8))

    def show_settings(self) -> None:
        win = tk.Toplevel(self.root)
        win.title("LocalFloatAI settings")
        win.attributes("-topmost", True)
        win.configure(bg="#10131a")
        win.resizable(False, False)
        pad = {"padx": 10, "pady": 6}
        tk.Label(win, text="GGUF model path (blank = auto-select from models/)", bg="#10131a", fg="#d7dee8").grid(row=0, column=0, columnspan=2, sticky="w", **pad)
        path_var = tk.StringVar(value=str(self.config.get("model_path", "")))
        tk.Entry(win, textvariable=path_var, width=65, bg="#1d2430", fg="#ffffff", insertbackground="#ffffff", relief="flat").grid(row=1, column=0, columnspan=2, **pad)
        tk.Label(win, text="Opacity", bg="#10131a", fg="#d7dee8").grid(row=2, column=0, sticky="w", **pad)
        opacity = tk.DoubleVar(value=float(self.config.get("opacity", 0.94)))
        tk.Scale(win, from_=0.45, to=1.0, resolution=0.01, orient="horizontal", variable=opacity, bg="#10131a", fg="#ffffff", highlightthickness=0, length=280).grid(row=2, column=1, **pad)
        top_var = tk.BooleanVar(value=bool(self.config.get("always_on_top", True)))
        tk.Checkbutton(win, text="Always on top", variable=top_var, bg="#10131a", fg="#d7dee8", selectcolor="#263042", activebackground="#10131a", activeforeground="#ffffff").grid(row=3, column=0, columnspan=2, sticky="w", **pad)

        tk.Label(win, text="Selected-text custom key", bg="#10131a", fg="#d7dee8").grid(row=4, column=0, sticky="w", **pad)
        key_var = tk.StringVar(value=self.selection_hotkey.key_name)
        key_entry = tk.Entry(win, textvariable=key_var, width=22, bg="#1d2430", fg="#ffffff", insertbackground="#ffffff", relief="flat", justify="center")
        key_entry.grid(row=4, column=1, **pad)
        tk.Label(win, text="Click the field, then press one key (U, F8, Home, Up, etc.)", bg="#10131a", fg="#8e99a8", font=("Segoe UI", 8)).grid(row=5, column=0, columnspan=2, sticky="w", **pad)

        def capture_custom_key(event: tk.Event) -> str:
            ignored = {"Shift_L", "Shift_R", "Control_L", "Control_R", "Alt_L", "Alt_R", "Win_L", "Win_R"}
            if event.keysym in ignored:
                return "break"
            key_var.set(GlobalSelectionKey.normalize(event.keysym))
            return "break"

        key_entry.bind("<KeyPress>", capture_custom_key)

        def save_and_close() -> None:
            new_key = GlobalSelectionKey.normalize(key_var.get())
            self.config.update({"model_path": path_var.get().strip(), "opacity": float(opacity.get()), "always_on_top": top_var.get(), "selection_key": new_key})
            save_config(self.config)
            self.selection_hotkey.set_key(new_key)
            self.root.attributes("-alpha", self.config["opacity"])
            self.root.attributes("-topmost", self.config["always_on_top"])
            win.destroy()

        ttk.Button(win, text="Save", command=save_and_close).grid(row=6, column=0, columnspan=2, pady=10)

    def set_status(self, text: str) -> None:
        try:
            self.root.after(0, lambda: self.status_var.set(text[:120]))
        except Exception:
            pass

    def hide(self) -> None:
        self.root.withdraw()

    def show(self) -> None:
        self.root.deiconify()
        self.root.lift()
        self.prompt.focus_force()

    def run(self) -> None:
        self.root.mainloop()
        self.hotkey.stop()
        self.selection_hotkey.stop()
        self.target_window.stop()
        self.api.stop()


def main() -> None:
    app = FloatingAI()
    app.run()


if __name__ == "__main__":
    main()
