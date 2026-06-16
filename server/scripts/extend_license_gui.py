"""Interactive GUI to extend license access (timed keys or Stripe subscription-backed).

Double-click or run::

    python -m server.scripts.extend_license_gui

Load ``SUPABASE_URL``, ``SUPABASE_ANON_KEY``, and (for subscription keys) ``STRIPE_SECRET_KEY``
from the environment or an ``.env`` file.

Headless servers should keep using::

    python -m server.scripts.extend_license CLASH-XXXX --days 30
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext
from tkinter import ttk

from server.license_extend import (
    ExtendError,
    extend_license,
    fetch_license_by_key,
    plan_extend,
    result_to_dict,
)

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover
    load_dotenv = None

_REPO_ROOT = Path(__file__).resolve().parents[2]
_MAX_DAYS = 999
_MAX_MONTHS = 36


def _try_load_dotenv_files() -> None:
    if load_dotenv is None:
        return
    for name in ".env", ".env.license":
        p = _REPO_ROOT / name
        if p.is_file():
            load_dotenv(p)
            return


def _supabase_configured() -> bool:
    u = os.environ.get("SUPABASE_URL", "").strip()
    k = os.environ.get("SUPABASE_ANON_KEY", "").strip()
    return bool(u and k)


def _stripe_configured() -> bool:
    return bool(os.environ.get("STRIPE_SECRET_KEY", "").strip())


def _load_env_path(path: str) -> tuple[bool, str]:
    p = Path(path).expanduser().resolve()
    if not p.is_file():
        return False, f"Not a file: {p}"
    if load_dotenv is None:
        return False, "python-dotenv is not installed (pip install python-dotenv)."
    load_dotenv(p)
    if _supabase_configured():
        return True, f"Loaded: {p}"
    return False, f"Loaded {p} but SUPABASE_URL / SUPABASE_ANON_KEY still missing."


def _format_lookup(lic: dict[str, object]) -> str:
    lines = [
        f"License key: {lic.get('license_key', '?')}",
        f"Status:      {lic.get('status', '?')}",
        f"Email:       {lic.get('email') or '(none)'}",
        f"Expires at:  {lic.get('expires_at') or '(lifetime / none)'}",
        f"Stripe sub:  {lic.get('stripe_subscription_id') or '(none — DB-only extend)'}",
        f"Notes:       {lic.get('notes') or '(none)'}",
    ]
    sub_id = lic.get("stripe_subscription_id")
    if sub_id and not _stripe_configured():
        lines.append("")
        lines.append("⚠ STRIPE_SECRET_KEY missing — cannot extend subscription-backed keys.")
    return "\n".join(lines)


def _format_result(data: dict[str, object]) -> str:
    return json.dumps(data, indent=2, default=str)


class ExtendLicenseApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("Extend license access")
        self.minsize(520, 520)
        self.geometry("640x580")

        _try_load_dotenv_files()

        pad = {"padx": 12, "pady": 6}
        frm = ttk.Frame(self)
        frm.pack(fill=tk.BOTH, expand=True)

        intro = (
            "Extend a customer's paid access window. Timed keys update Postgres only; "
            "subscription-backed keys also update Stripe so webhooks stay in sync."
        )
        ttk.Label(frm, text=intro, wraplength=580, justify=tk.LEFT).pack(anchor=tk.W, **pad)

        env_row = ttk.Frame(frm)
        env_row.pack(fill=tk.X, **pad)
        ttk.Label(env_row, text="Env file (optional):", width=18).pack(side=tk.LEFT)
        self._env_path = tk.StringVar()
        ttk.Entry(env_row, textvariable=self._env_path, width=52).pack(
            side=tk.LEFT, fill=tk.X, expand=True
        )
        ttk.Button(env_row, text="Browse…", command=self._browse_env).pack(side=tk.LEFT, padx=(8, 0))
        ttk.Button(env_row, text="Load", command=self._load_env_clicked).pack(side=tk.LEFT, padx=(6, 0))

        self._cred_var = tk.StringVar()
        self._cred_label = ttk.Label(frm, textvariable=self._cred_var)
        self._cred_label.pack(anchor=tk.W, padx=12)

        ttk.Label(frm, text="License key:").pack(anchor=tk.W, **pad)
        self._key = tk.StringVar()
        ttk.Entry(frm, textvariable=self._key, width=60).pack(fill=tk.X, **pad)

        dur_row = ttk.Frame(frm)
        dur_row.pack(fill=tk.X, **pad)
        ttk.Label(dur_row, text="Extend by:", width=18).pack(side=tk.LEFT)

        self._unit = tk.StringVar(value="days")
        ttk.Radiobutton(dur_row, text="Days", variable=self._unit, value="days").pack(side=tk.LEFT)
        ttk.Radiobutton(dur_row, text="Months", variable=self._unit, value="months").pack(
            side=tk.LEFT, padx=(8, 0)
        )

        self._amount = tk.IntVar(value=30)
        ttk.Spinbox(
            dur_row,
            from_=1,
            to=_MAX_DAYS,
            width=8,
            textvariable=self._amount,
        ).pack(side=tk.LEFT, padx=(16, 0))

        ttk.Label(frm, text="Notes (optional, stored on license row):").pack(anchor=tk.W, **pad)
        self._notes = tk.StringVar(value="")
        ttk.Entry(frm, textvariable=self._notes, width=60).pack(fill=tk.X, **pad)

        btn_row = ttk.Frame(frm)
        btn_row.pack(fill=tk.X, **pad)
        ttk.Button(btn_row, text="Look up key", command=self._lookup_clicked).pack(side=tk.LEFT)
        ttk.Button(btn_row, text="Preview", command=self._preview_clicked).pack(side=tk.LEFT, padx=(8, 0))
        self._extend_btn = ttk.Button(btn_row, text="Extend license", command=self._extend_clicked)
        self._extend_btn.pack(side=tk.LEFT, padx=(8, 0))

        ttk.Label(
            frm,
            text="Output — Look up shows current row; Preview is a dry run; Extend applies changes.",
            wraplength=580,
            justify=tk.LEFT,
        ).pack(anchor=tk.W, **pad)

        self._out_box = scrolledtext.ScrolledText(frm, height=14, wrap=tk.WORD, font=("Consolas", 10))
        self._out_box.pack(fill=tk.BOTH, expand=True, **pad)

        out_btn_row = ttk.Frame(frm)
        out_btn_row.pack(fill=tk.X, padx=12, pady=(0, 8))
        ttk.Button(out_btn_row, text="Copy output", command=self._copy_output).pack(side=tk.LEFT)
        ttk.Button(out_btn_row, text="Clear output", command=self._clear_output).pack(side=tk.LEFT, padx=(8, 0))

        self._refresh_cred_status()
        self.protocol("WM_DELETE_WINDOW", self.destroy)

    def _refresh_cred_status(self) -> None:
        parts: list[str] = []
        if _supabase_configured():
            parts.append("Supabase: OK")
        else:
            parts.append("Supabase: missing")
        if _stripe_configured():
            parts.append("Stripe: OK")
        else:
            parts.append("Stripe: missing (needed for subscription keys)")
        text = " · ".join(parts)
        self._cred_var.set(text)
        if _supabase_configured():
            self._cred_label.configure(foreground="green" if _stripe_configured() else "darkorange")
        else:
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

    def _clear_output(self) -> None:
        self._out_box.delete("1.0", tk.END)

    def _copy_output(self) -> None:
        text = self._out_box.get("1.0", tk.END).strip()
        if not text:
            messagebox.showinfo("Copy", "No output to copy yet.")
            return
        self.clipboard_clear()
        self.clipboard_append(text)
        self.update()
        messagebox.showinfo("Copy", "Output copied to the clipboard.")

    def _read_inputs(self) -> tuple[str, int, str, str] | None:
        if not _supabase_configured():
            messagebox.showerror(
                "Credentials",
                "SUPABASE_URL and SUPABASE_ANON_KEY are not set.\n\n"
                "Load an .env file or set them in your environment, then try again.",
            )
            return None

        key = self._key.get().strip().upper()
        if not key:
            messagebox.showerror("License key", "Enter a license key.")
            return None

        try:
            amount = int(self._amount.get())
        except (tk.TclError, ValueError):
            messagebox.showerror("Amount", "Enter a valid positive number.")
            return None

        unit = self._unit.get()
        max_val = _MAX_DAYS if unit == "days" else _MAX_MONTHS
        if amount < 1 or amount > max_val:
            messagebox.showerror("Amount", f"Choose between 1 and {max_val} {unit}.")
            return None

        notes = self._notes.get().strip()
        return key, amount, unit, notes

    def _append_output(self, text: str) -> None:
        self._out_box.insert(tk.END, text + "\n\n")
        self._out_box.see(tk.END)

    def _lookup_clicked(self) -> None:
        parsed = self._read_inputs()
        if parsed is None:
            return
        key, _, _, _ = parsed

        self._clear_output()
        try:
            lic = fetch_license_by_key(key)
        except Exception as exc:
            self._append_output(f"Lookup failed: {exc}")
            messagebox.showerror("Look up", str(exc))
            return

        if lic is None:
            self._append_output(f"Key not found: {key}")
            messagebox.showerror("Look up", f"No license row for {key}")
            return

        self._append_output(_format_lookup(lic))

    def _run_extend(self, *, dry_run: bool) -> None:
        parsed = self._read_inputs()
        if parsed is None:
            return
        key, amount, unit, notes = parsed

        kwargs: dict[str, object] = {"key": key, "notes": notes or None, "dry_run": dry_run}
        if unit == "days":
            kwargs["days"] = amount
        else:
            kwargs["months"] = amount

        btn = self._extend_btn
        btn.configure(state=tk.DISABLED)
        self.update_idletasks()

        try:
            result = extend_license(**kwargs)  # type: ignore[arg-type]
            data = result_to_dict(result)
            if dry_run:
                data["preview"] = True
            self._clear_output()
            self._append_output(_format_result(data))
            if dry_run:
                messagebox.showinfo("Preview", "Dry run complete — no changes were applied.")
            else:
                messagebox.showinfo("Extended", f"License extended.\nNew expiry: {data.get('expires_at')}")
        except ExtendError as exc:
            payload = {"error": exc.code, "message": exc.message, **exc.details}
            self._clear_output()
            self._append_output(_format_result(payload))
            messagebox.showerror("Extend", exc.message)
        except Exception as exc:
            self._clear_output()
            self._append_output(f"Unexpected error: {exc}")
            messagebox.showerror("Extend", str(exc))
        finally:
            btn.configure(state=tk.NORMAL)

    def _preview_clicked(self) -> None:
        self._run_extend(dry_run=True)

    def _extend_clicked(self) -> None:
        parsed = self._read_inputs()
        if parsed is None:
            return
        key, amount, unit, _ = parsed

        try:
            plan = plan_extend(
                key=key,
                days=amount if unit == "days" else None,
                months=amount if unit == "months" else None,
                notes=self._notes.get().strip() or None,
            )
        except ExtendError as exc:
            messagebox.showerror("Extend", exc.message)
            return

        unit_label = f"{amount} {unit}"
        stripe_note = ""
        if plan.kind == "stripe_subscription":
            stripe_note = f"\n\nStripe subscription {plan.stripe_subscription_id} will be updated (trial_end)."
        elif plan.kind == "timed":
            stripe_note = "\n\nPostgres expires_at only (no Stripe subscription on this key)."

        if not messagebox.askyesno(
            "Confirm extend",
            f"Extend {key} by {unit_label}?\n\n"
            f"Current expiry anchor: {plan.anchor_expires_at}\n"
            f"New expiry:           {plan.new_expires_at}"
            f"{stripe_note}",
        ):
            return

        self._run_extend(dry_run=False)


def main() -> None:
    app = ExtendLicenseApp()
    app.mainloop()


if __name__ == "__main__":
    main()
