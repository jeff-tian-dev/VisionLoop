"""Interactive GUI to mint complimentary license keys into Supabase (no Stripe).

Double-click or run::

    python -m server.scripts.issue_comp_licenses

You will be prompted for email, how many keys, access duration (lifetime, days, or months),
optional notes, and (if needed) an ``.env`` file path so ``SUPABASE_URL`` and
``SUPABASE_ANON_KEY`` are loaded.

Uses the same PostgREST ``POST /licenses`` flow as :mod:`server.admin_cli`.

Headless servers should keep using::

    python -m server.admin_cli issue --email you@example.com
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tkinter import filedialog, messagebox, scrolledtext
from tkinter import ttk
import tkinter as tk

from dateutil.relativedelta import relativedelta

from server.admin_cli import _post
from server.keys import generate_license_key

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover
    load_dotenv = None

_MAX_KEYS = 99
_MAX_DAYS = 999
_MAX_MONTHS = 36
_REPO_ROOT = Path(__file__).resolve().parents[2]


def compute_issue_expires_at(*, unit: str, amount: int) -> str | None:
    """Return ISO ``expires_at`` for a new key, or ``None`` for lifetime."""
    if unit == "lifetime":
        return None
    now = datetime.now(timezone.utc)
    if unit == "days":
        if amount < 1 or amount > _MAX_DAYS:
            raise ValueError(f"days must be between 1 and {_MAX_DAYS}")
        expires = now + timedelta(days=amount)
    elif unit == "months":
        if amount < 1 or amount > _MAX_MONTHS:
            raise ValueError(f"months must be between 1 and {_MAX_MONTHS}")
        expires = now + relativedelta(months=amount)
    else:
        raise ValueError(f"unknown duration unit: {unit!r}")
    return expires.isoformat()


def _try_load_dotenv_files() -> None:
    if load_dotenv is None:
        return
    for name in ".env", ".env.license":
        p = _REPO_ROOT / name
        if p.is_file():
            load_dotenv(p)
            return


def _credentials_configured() -> bool:
    u = os.environ.get("SUPABASE_URL", "").strip()
    k = os.environ.get("SUPABASE_ANON_KEY", "").strip()
    return bool(u and k)


def _load_env_path(path: str) -> tuple[bool, str]:
    p = Path(path).expanduser().resolve()
    if not p.is_file():
        return False, f"Not a file: {p}"
    if load_dotenv is None:
        return False, "python-dotenv is not installed (pip install python-dotenv)."
    load_dotenv(p)
    if _credentials_configured():
        return True, f"Loaded: {p}"
    return False, f"Loaded {p} but SUPABASE_URL / SUPABASE_ANON_KEY still missing."


def issue_batch(
    email: str,
    count: int,
    notes: str,
    *,
    expires_at: str | None = None,
) -> tuple[list[dict[str, object]], list[str]]:
    """Mint keys via REST; returns ``(issued_rows, error_messages)``."""
    issued: list[dict[str, object]] = []
    errors: list[str] = []

    for _ in range(count):
        key = generate_license_key()
        body: dict[str, object] = {
            "license_key": key,
            "status": "active",
            "email": email.strip(),
            "notes": notes.strip() if notes.strip() else None,
        }
        if expires_at is not None:
            body["expires_at"] = expires_at
        if body["notes"] is None:
            del body["notes"]

        r = _post("/licenses", body, prefer="return=representation")
        if r.status_code not in (200, 201):
            errors.append(f"{key}: HTTP {r.status_code} {r.text}")
            continue

        rows = r.json()
        row = rows[0] if isinstance(rows, list) and rows else rows
        if isinstance(row, dict):
            issued.append(row)
        else:
            issued.append({"license_key": key})

    return issued, errors


class IssueLicensesApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("Issue complimentary license keys")
        self.minsize(520, 500)
        self.geometry("620x560")

        _try_load_dotenv_files()

        pad = {"padx": 12, "pady": 6}

        self._cred_var = tk.StringVar()

        frm = ttk.Frame(self)
        frm.pack(fill=tk.BOTH, expand=True)

        intro = (
            "Enter details below, then click Issue keys. "
            "Secrets must be available (environment or .env next to the repo, or browse to a file)."
        )
        ttk.Label(frm, text=intro, wraplength=560, justify=tk.LEFT).pack(anchor=tk.W, **pad)

        env_row = ttk.Frame(frm)
        env_row.pack(fill=tk.X, **pad)
        ttk.Label(env_row, text="Env file (optional):", width=18).pack(side=tk.LEFT)
        self._env_path = tk.StringVar()
        ttk.Entry(env_row, textvariable=self._env_path, width=52).pack(side=tk.LEFT, fill=tk.X, expand=True)
        ttk.Button(env_row, text="Browse…", command=self._browse_env).pack(side=tk.LEFT, padx=(8, 0))
        ttk.Button(env_row, text="Load", command=self._load_env_clicked).pack(side=tk.LEFT, padx=(6, 0))

        self._cred_label = ttk.Label(frm, textvariable=self._cred_var)
        self._cred_label.pack(anchor=tk.W, padx=12)

        ttk.Label(frm, text="Email (stored on each license row):").pack(anchor=tk.W, **pad)
        self._email = tk.StringVar()
        ttk.Entry(frm, textvariable=self._email, width=60).pack(fill=tk.X, **pad)

        count_row = ttk.Frame(frm)
        count_row.pack(fill=tk.X, **pad)
        ttk.Label(count_row, text="How many keys?", width=18).pack(side=tk.LEFT)
        self._count = tk.IntVar(value=1)
        sp = ttk.Spinbox(
            count_row,
            from_=1,
            to=_MAX_KEYS,
            width=8,
            textvariable=self._count,
        )
        sp.pack(side=tk.LEFT)

        dur_row = ttk.Frame(frm)
        dur_row.pack(fill=tk.X, **pad)
        ttk.Label(dur_row, text="Access duration:", width=18).pack(side=tk.LEFT)

        self._duration_unit = tk.StringVar(value="lifetime")
        ttk.Radiobutton(
            dur_row,
            text="Lifetime",
            variable=self._duration_unit,
            value="lifetime",
            command=self._on_duration_unit_changed,
        ).pack(side=tk.LEFT)
        ttk.Radiobutton(
            dur_row,
            text="Days",
            variable=self._duration_unit,
            value="days",
            command=self._on_duration_unit_changed,
        ).pack(side=tk.LEFT, padx=(8, 0))
        ttk.Radiobutton(
            dur_row,
            text="Months",
            variable=self._duration_unit,
            value="months",
            command=self._on_duration_unit_changed,
        ).pack(side=tk.LEFT, padx=(8, 0))

        self._duration_amount = tk.IntVar(value=30)
        self._duration_spin = ttk.Spinbox(
            dur_row,
            from_=1,
            to=_MAX_DAYS,
            width=8,
            textvariable=self._duration_amount,
            state=tk.DISABLED,
        )
        self._duration_spin.pack(side=tk.LEFT, padx=(16, 0))

        ttk.Label(frm, text="Notes (optional, e.g. friend name):").pack(anchor=tk.W, **pad)
        self._notes = tk.StringVar(value="complimentary")
        ttk.Entry(frm, textvariable=self._notes, width=60).pack(fill=tk.X, **pad)

        self._issue_btn = ttk.Button(frm, text="Issue keys", command=self._issue_clicked)
        self._issue_btn.pack(anchor=tk.W, **pad)

        ttk.Label(
            frm,
            text="License key(s) — use “Copy all” or select text and Ctrl+C. Close this window when finished.",
            wraplength=560,
            justify=tk.LEFT,
        ).pack(anchor=tk.W, **pad)

        self._keys_box = scrolledtext.ScrolledText(frm, height=12, wrap=tk.WORD, font=("Consolas", 11))
        self._keys_box.pack(fill=tk.BOTH, expand=True, **pad)

        copy_row = ttk.Frame(frm)
        copy_row.pack(fill=tk.X, padx=12, pady=(0, 8))
        ttk.Button(copy_row, text="Copy all keys", command=self._copy_all).pack(side=tk.LEFT)
        ttk.Button(copy_row, text="Clear output", command=self._clear_keys).pack(side=tk.LEFT, padx=(8, 0))

        self._refresh_cred_status()
        self.protocol("WM_DELETE_WINDOW", self.destroy)

    def _on_duration_unit_changed(self) -> None:
        unit = self._duration_unit.get()
        if unit == "lifetime":
            self._duration_spin.configure(state=tk.DISABLED)
            return
        self._duration_spin.configure(state=tk.NORMAL)
        max_val = _MAX_DAYS if unit == "days" else _MAX_MONTHS
        self._duration_spin.configure(to=max_val)
        try:
            amount = int(self._duration_amount.get())
        except (tk.TclError, ValueError):
            amount = 30
        if amount < 1:
            amount = 1
        elif amount > max_val:
            amount = max_val
        self._duration_amount.set(amount)

    def _refresh_cred_status(self) -> None:
        if _credentials_configured():
            self._cred_var.set("Supabase credentials: OK (SUPABASE_URL + SUPABASE_ANON_KEY)")
            self._cred_label.configure(foreground="green")
        else:
            self._cred_var.set(
                "Supabase credentials: missing — set env vars or load an .env file with SUPABASE_URL and SUPABASE_ANON_KEY."
            )
            self._cred_label.configure(foreground="darkred")

    def _browse_env(self) -> None:
        path = filedialog.askopenfilename(
            title="Select .env file",
            filetypes=[("Env file", "*.env"), ("All files", "*.*")],
        )
        if path:
            self._env_path.set(path)

    def _load_env_clicked(self) -> None:
        path = self._env_path.get().strip()
        if not path:
            messagebox.showinfo("Env file", "Choose a file first, or leave blank to use existing environment.")
            return
        ok, msg = _load_env_path(path)
        self._refresh_cred_status()
        if ok:
            messagebox.showinfo("Env file", msg)
        else:
            messagebox.showerror("Env file", msg)

    def _clear_keys(self) -> None:
        self._keys_box.delete("1.0", tk.END)

    def _copy_all(self) -> None:
        text = self._keys_box.get("1.0", tk.END).strip()
        if not text:
            messagebox.showinfo("Copy", "No keys to copy yet.")
            return
        self.clipboard_clear()
        self.clipboard_append(text)
        self.update()
        messagebox.showinfo("Copy", "All text in the box was copied to the clipboard.")

    def _issue_clicked(self) -> None:
        if not _credentials_configured():
            messagebox.showerror(
                "Credentials",
                "SUPABASE_URL and SUPABASE_ANON_KEY are not set.\n\n"
                "Load an .env file or set them in your environment, then try again.",
            )
            return

        email = self._email.get().strip()
        if not email:
            messagebox.showerror("Email", "Please enter an email (stored with each license row).")
            return

        try:
            count = int(self._count.get())
        except (tk.TclError, ValueError):
            messagebox.showerror("Count", "Enter a valid number of keys.")
            return

        if count < 1 or count > _MAX_KEYS:
            messagebox.showerror("Count", f"Choose between 1 and {_MAX_KEYS} keys.")
            return

        unit = self._duration_unit.get()
        try:
            amount = int(self._duration_amount.get()) if unit != "lifetime" else 0
        except (tk.TclError, ValueError):
            messagebox.showerror("Duration", "Enter a valid duration amount.")
            return

        try:
            expires_at = compute_issue_expires_at(unit=unit, amount=amount)
        except ValueError as exc:
            messagebox.showerror("Duration", str(exc))
            return

        notes = self._notes.get()
        self._issue_btn.configure(state=tk.DISABLED)
        self.update_idletasks()

        try:
            issued, errors = issue_batch(email, count, notes, expires_at=expires_at)
        finally:
            self._issue_btn.configure(state=tk.NORMAL)

        self._clear_keys()
        lines = []
        if issued:
            duration_label = "lifetime" if expires_at is None else expires_at
            lines.append(f"Issued {len(issued)} key(s) for {email!r} ({duration_label}):")
            lines.append("")
            for row in issued:
                lk = row.get("license_key", "?")
                lines.append(str(lk))
            lines.append("")
            lines.append("— Copy keys above, then close this window when done.")

        if errors:
            lines.append("Errors:")
            for e in errors:
                lines.append(e)

        self._keys_box.insert(tk.END, "\n".join(lines))
        self._keys_box.see(tk.END)

        if errors and not issued:
            messagebox.showerror("Issue keys", "No keys were issued. See the output box for errors.")
        elif errors:
            messagebox.showwarning("Issue keys", "Some keys failed; check the output box.")


def main() -> None:
    app = IssueLicensesApp()
    app.mainloop()


if __name__ == "__main__":
    main()
