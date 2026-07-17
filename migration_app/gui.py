"""Desktop GUI (PRD §11 Phase 8): file picker -> mapping preview -> dry-run
-> review report -> actual run, with a progress bar/log view and an "open
reports folder" button. Built on tkinter (stdlib, no extra install).

Runs the (blocking, network-bound) pipeline functions from migrate.py on a
background thread so the UI stays responsive, and pipes their stdout into
the on-screen log via a queue (thread -> main-thread poll, the only
tkinter-safe way to cross threads).
"""
from __future__ import annotations

import contextlib
import io
import json
import os
import queue
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from checkpoint import DEFAULT_CHECKPOINT_FILE, clear_checkpoint
from mapping import KEYDATA_TO_COLUMN
from migrate import DEFAULT_CSV, run_dry_run, run_upsert
from report import REPORTS_DIR


class QueueWriter(io.TextIOBase):
    """Redirect target for print() inside the worker thread: pushes each
    write into a queue the main thread polls, instead of writing to a
    stream tkinter widgets can't safely touch from a background thread."""

    def __init__(self, q: queue.Queue):
        self.q = q

    def write(self, text: str) -> int:
        if text:
            self.q.put(("log", text))
        return len(text)

    def flush(self) -> None:
        pass


class MigrationApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("dmp_financesummary.csv -> Supabase financials 마이그레이션")
        self.root.geometry("880x640")

        self.queue: queue.Queue = queue.Queue()
        self.worker: threading.Thread | None = None

        self.csv_path = tk.StringVar(value=DEFAULT_CSV)
        self.only_codeid = tk.StringVar(value="")
        self.status = tk.StringVar(value="대기 중")

        self._build_layout()
        self.root.after(100, self._poll_queue)

    # ---------- layout ----------
    def _build_layout(self) -> None:
        pad = {"padx": 8, "pady": 6}

        file_frame = ttk.Frame(self.root)
        file_frame.pack(fill="x", **pad)
        ttk.Label(file_frame, text="CSV 파일:").pack(side="left")
        ttk.Entry(file_frame, textvariable=self.csv_path, width=70).pack(side="left", padx=6)
        ttk.Button(file_frame, text="찾아보기", command=self._browse_csv).pack(side="left")

        scope_frame = ttk.Frame(self.root)
        scope_frame.pack(fill="x", **pad)
        ttk.Label(scope_frame, text="CODEID 범위 제한 (쉼표로 구분, 비우면 전체):").pack(side="left")
        ttk.Entry(scope_frame, textvariable=self.only_codeid, width=40).pack(side="left", padx=6)

        mapping_frame = ttk.LabelFrame(self.root, text="§3.1 KEYDATA → 컬럼 매핑")
        mapping_frame.pack(fill="x", **pad)
        self._build_mapping_table(mapping_frame)

        button_frame = ttk.Frame(self.root)
        button_frame.pack(fill="x", **pad)
        self.dry_run_btn = ttk.Button(button_frame, text="Dry-run 실행 (DB 쓰기 없음)", command=self._on_dry_run)
        self.dry_run_btn.pack(side="left", padx=4)
        self.run_btn = ttk.Button(button_frame, text="실제 마이그레이션 실행", command=self._on_run)
        self.run_btn.pack(side="left", padx=4)
        self.reset_ckpt_btn = ttk.Button(button_frame, text="체크포인트 초기화", command=self._on_reset_checkpoint)
        self.reset_ckpt_btn.pack(side="left", padx=4)
        ttk.Button(button_frame, text="리포트 폴더 열기", command=self._open_reports_folder).pack(side="left", padx=4)

        self.progress = ttk.Progressbar(self.root, mode="determinate")
        self.progress.pack(fill="x", **pad)

        ttk.Label(self.root, textvariable=self.status).pack(anchor="w", padx=8)

        log_frame = ttk.LabelFrame(self.root, text="로그")
        log_frame.pack(fill="both", expand=True, **pad)
        self.log_text = tk.Text(log_frame, wrap="word", state="disabled")
        scrollbar = ttk.Scrollbar(log_frame, command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=scrollbar.set)
        self.log_text.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

    def _build_mapping_table(self, parent: ttk.LabelFrame) -> None:
        columns = ("keydata", "column")
        tree = ttk.Treeview(parent, columns=columns, show="headings", height=6)
        tree.heading("keydata", text="KEYDATA (CSV)")
        tree.heading("column", text="Supabase 컬럼")
        tree.column("keydata", width=200)
        tree.column("column", width=200)
        for keydata, column in KEYDATA_TO_COLUMN.items():
            tree.insert("", "end", values=(keydata, column))
        tree.pack(fill="x", padx=4, pady=4)

    # ---------- helpers ----------
    def _browse_csv(self) -> None:
        path = filedialog.askopenfilename(filetypes=[("CSV files", "*.csv"), ("All files", "*.*")])
        if path:
            self.csv_path.set(path)

    def _open_reports_folder(self) -> None:
        REPORTS_DIR.mkdir(exist_ok=True)
        os.startfile(REPORTS_DIR)  # Windows-only, matches PRD §7 platform target

    def _parse_only_codeids(self) -> set[str] | None:
        raw = self.only_codeid.get().strip()
        if not raw:
            return None
        return {c.strip() for c in raw.split(",") if c.strip()}

    def _append_log(self, text: str) -> None:
        self.log_text.configure(state="normal")
        self.log_text.insert("end", text)
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def _set_running(self, running: bool) -> None:
        state = "disabled" if running else "normal"
        self.dry_run_btn.configure(state=state)
        self.run_btn.configure(state=state)
        self.reset_ckpt_btn.configure(state=state)
        self.status.set("실행 중 ..." if running else "대기 중")

    def _poll_queue(self) -> None:
        try:
            while True:
                kind, payload = self.queue.get_nowait()
                if kind == "log":
                    self._append_log(payload)
                elif kind == "progress":
                    done, total = payload
                    self.progress.configure(maximum=max(total, 1), value=done)
                elif kind == "done":
                    self._append_log("\n=== 완료 ===\n" + json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
                    self._set_running(False)
                elif kind == "error":
                    self._append_log(f"\n[오류] {payload}\n")
                    self._set_running(False)
                    messagebox.showerror("오류", payload)
        except queue.Empty:
            pass
        self.root.after(100, self._poll_queue)

    def _run_in_background(self, target) -> None:
        self._set_running(True)
        self.progress.configure(value=0)
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.configure(state="disabled")

        def wrapper():
            with contextlib.redirect_stdout(QueueWriter(self.queue)):
                try:
                    summary = target()
                    self.queue.put(("done", summary))
                except Exception as exc:  # noqa: BLE001 - surface any failure to the GUI
                    self.queue.put(("error", str(exc)))

        self.worker = threading.Thread(target=wrapper, daemon=True)
        self.worker.start()

    # ---------- button handlers ----------
    def _on_dry_run(self) -> None:
        csv_path = self.csv_path.get()
        only_codeids = self._parse_only_codeids()
        self._run_in_background(lambda: run_dry_run(csv_path, only_codeids))

    def _on_run(self) -> None:
        if not messagebox.askyesno(
            "실제 마이그레이션 실행 확인",
            "이 작업은 Supabase의 financials 테이블에 실제로 데이터를 쓰거나 갱신합니다.\n"
            "Dry-run 리포트를 먼저 확인하셨나요?\n\n계속 진행하시겠습니까?",
        ):
            return
        csv_path = self.csv_path.get()
        only_codeids = self._parse_only_codeids()

        def progress_cb(done: int, total: int, _totals: dict) -> None:
            self.queue.put(("progress", (done, total)))

        self._run_in_background(lambda: run_upsert(csv_path, only_codeids, progress_callback=progress_cb))

    def _on_reset_checkpoint(self) -> None:
        if messagebox.askyesno(
            "체크포인트 초기화",
            f"{DEFAULT_CHECKPOINT_FILE} 를 삭제하고 다음 실행 시 전체 CODEID를 다시 처리합니다.\n"
            "(자연키 기반 upsert라 안전하지만 시간이 더 걸립니다.) 계속할까요?",
        ):
            clear_checkpoint(DEFAULT_CHECKPOINT_FILE)
            self._append_log("[gui] checkpoint cleared\n")


def main() -> None:
    root = tk.Tk()
    MigrationApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
