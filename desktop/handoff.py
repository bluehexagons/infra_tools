"""Small human-facing control window; closing it never resumes agent input."""

from __future__ import annotations

from pathlib import Path
import queue
import sys
import threading

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from desktop import session_runtime as runtime


def describe(status: dict) -> str:
    if "error" in status:
        return "Desktop control unavailable: " + str(status["error"])
    if status.get("paused"):
        return "Agent input paused — you have control"
    if status.get("control_active"):
        return "Agent operation in progress"
    return "Agent input enabled"


def main() -> int:
    try:
        import tkinter as tk
        from tkinter import ttk
    except ImportError:
        print("Desktop handoff needs python3-tk; rerun desktop setup", file=sys.stderr)
        return 1
    runtime.configuration()
    root = tk.Tk()
    root.title("Shared desktop control")
    root.resizable(False, False)
    frame = ttk.Frame(root, padding=16)
    frame.pack()
    message = tk.StringVar(value="Checking desktop control…")
    ttk.Label(frame, textvariable=message, wraplength=380).pack(anchor="w", pady=(0, 12))
    ttk.Label(frame, text="Pause blocks agent input. Your mouse and keyboard keep working.", wraplength=380).pack(anchor="w")
    operations: queue.Queue[str] = queue.Queue(maxsize=1)
    responses: queue.Queue[dict] = queue.Queue()
    stopping = threading.Event()

    def submit(action: str) -> None:
        try:
            operations.put_nowait(action)
            message.set("Updating desktop control…")
        except queue.Full:
            message.set("A control request is pending…")

    buttons = ttk.Frame(frame)
    buttons.pack(anchor="w", pady=(12, 0))
    ttk.Button(buttons, text="Pause agents", command=lambda: submit("pause")).pack(side="left", padx=(0, 8))
    ttk.Button(buttons, text="Resume agents", command=lambda: submit("resume")).pack(side="left")

    def worker() -> None:
        while not stopping.is_set():
            try:
                action = operations.get(timeout=1)
            except queue.Empty:
                action = "status"
            try:
                responses.put(runtime.request({"action": action}))
            except (OSError, ValueError, RuntimeError) as exc:
                responses.put({"error": str(exc)})

    def refresh() -> None:
        try:
            while True:
                message.set(describe(responses.get_nowait()))
        except queue.Empty:
            pass
        root.after(100, refresh)

    def close() -> None:
        stopping.set()
        root.destroy()

    root.protocol("WM_DELETE_WINDOW", close)
    threading.Thread(target=worker, daemon=True).start()
    refresh()
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
