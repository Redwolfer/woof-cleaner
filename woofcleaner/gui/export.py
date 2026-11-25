from tkinter import filedialog, messagebox
from ..reports import write_csv


def save_csv(parent, name, rows):
    path = filedialog.asksaveasfilename(parent=parent, title="Export results", initialfile=name + ".csv",
                                        defaultextension=".csv", filetypes=[("CSV files", "*.csv")])
    if path:
        try:
            write_csv(path, rows)
        except OSError as exc:
            messagebox.showerror("Export failed", str(exc), parent=parent)
        else:
            parent.app.set_status(f"Saved {path}")
