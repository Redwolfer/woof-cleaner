"""Shared GUI plumbing: background jobs, themed tables with checkboxes, page headers, stat cards."""
from __future__ import annotations

import re
import threading
import tkinter as tk
from tkinter import messagebox, ttk
from typing import Any, Callable

ON, OFF = "☑", "☐"     # used in plain-text output only; tables use the drawn checkbox images

_UNITS = {"B": 1, "KB": 1024, "MB": 1024 ** 2, "GB": 1024 ** 3, "TB": 1024 ** 4}


def sort_value(text: str):
    """Sort key that understands sizes ('1.2 MB'), versions/numbers and dates."""
    t = (text or "").strip()
    m = re.fullmatch(r"([\d.]+)\s*(B|KB|MB|GB|TB)", t)
    if m:
        return (0, float(m.group(1)) * _UNITS[m.group(2)], "")
    if re.fullmatch(r"\d+(\.\d+)*", t):
        return (0, 0, tuple(int(p) for p in t.split(".")))
    return (1, 0, t.lower())


# ---- checkbox images ---------------------------------------------------------------------

def _hex(c: str) -> tuple[int, int, int]:
    c = c.lstrip("#")
    return int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16)


def _mix(a, b, t: float) -> str:
    return "#%02x%02x%02x" % tuple(round(x + (y - x) * t) for x, y in zip(a, b))


def _seg_dist(px, py, ax, ay, bx, by) -> float:
    dx, dy = bx - ax, by - ay
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)))
    return ((px - ax - t * dx) ** 2 + (py - ay - t * dy) ** 2) ** 0.5


def draw_checkbox(img: tk.PhotoImage, kind: str, c: dict, size: int = 18) -> None:
    """Paint an anti-aliased rounded checkbox into `img` (on | off | mixed)."""
    bg = _hex(c["surface"])
    fill = _hex(c["accent"] if kind != "off" else c["surface"])
    border = _hex(c["accent"] if kind != "off" else c["faint"])
    mark = _hex(c["accent_text"])
    pad, rad, ss = 1.5, 4.0, 4
    lo, hi = pad, size - pad
    rows = []
    alpha_map = []
    for y in range(size):
        row = []
        for x in range(size):
            inside = edge = tick = 0
            for sy in range(ss):
                for sx in range(ss):
                    px, py = x + (sx + 0.5) / ss, y + (sy + 0.5) / ss
                    qx = min(max(px, lo + rad), hi - rad)
                    qy = min(max(py, lo + rad), hi - rad)
                    d = ((px - qx) ** 2 + (py - qy) ** 2) ** 0.5
                    if d <= rad:
                        inside += 1
                        if d > rad - 1.3:
                            edge += 1
                        if kind == "on" and min(_seg_dist(px, py, 5, 9.4, 8, 12.4), _seg_dist(px, py, 8, 12.4, 13.2, 6.2)) < 1.1:
                            tick += 1
                        elif kind == "mixed" and 5 <= px <= 13 and abs(py - 9) < 1.1:
                            tick += 1
            n = ss * ss
            if not inside:
                row.append("#%02x%02x%02x" % bg)
                alpha_map.append((x, y))
                continue
            col = fill
            if edge:
                col = _hex(_mix(col, border, edge / inside))
            if tick:
                col = _hex(_mix(col, mark, tick / inside))
            row.append(_mix(bg, col, inside / n))
        rows.append("{" + " ".join(row) + "}")
    img.put(" ".join(rows), to=(0, 0))
    for x, y in alpha_map:
        img.transparency_set(x, y, True)


def draw_radio(img: tk.PhotoImage, on: bool, c: dict, size: int = 18) -> None:
    bg = _hex(c["surface"])
    ring = _hex(c["accent"] if on else c["faint"])
    dot = _hex(c["accent"])
    face = _hex(c["surface"])
    ss, r_out, cx = 4, size / 2 - 1.5, size / 2
    rows, clear = [], []
    for y in range(size):
        row = []
        for x in range(size):
            cov = ring_n = dot_n = 0
            for sy in range(ss):
                for sx in range(ss):
                    d = ((x + (sx + 0.5) / ss - cx) ** 2 + (y + (sy + 0.5) / ss - cx) ** 2) ** 0.5
                    if d <= r_out:
                        cov += 1
                        if d > r_out - 1.4:
                            ring_n += 1
                        elif on and d <= 4.2:
                            dot_n += 1
            if not cov:
                row.append("#%02x%02x%02x" % bg)
                clear.append((x, y))
                continue
            col = _hex(_mix(face, ring, ring_n / cov))
            if dot_n:
                col = _hex(_mix(col, dot, dot_n / cov))
            row.append(_mix(bg, col, cov / (ss * ss)))
        rows.append("{" + " ".join(row) + "}")
    img.put(" ".join(rows), to=(0, 0))
    for x, y in clear:
        img.transparency_set(x, y, True)


class CheckImages:
    """Checkbox / radio PhotoImages redrawn in place on theme change, so every widget updates at once."""

    def __init__(self, theme):
        self.theme = theme
        self.img = {k: tk.PhotoImage(master=theme.root, width=18, height=18)
                    for k in ("on", "off", "mixed", "radio_on", "radio_off")}
        self.redraw()
        theme.on_change(self.redraw)
        self._install(theme.style)

    def redraw(self):
        for k in ("on", "off", "mixed"):
            draw_checkbox(self.img[k], k, self.theme.c)
        draw_radio(self.img["radio_on"], True, self.theme.c)
        draw_radio(self.img["radio_off"], False, self.theme.c)

    def _install(self, s):
        """Use the same drawn boxes for ttk Checkbutton / Radiobutton indicators."""
        i = self.img
        s.element_create("Woof.check", "image", i["off"], ("disabled", "selected", i["on"]), ("selected", i["on"]),
                         ("alternate", i["mixed"]), padding=(0, 0, 8, 0), sticky="w")
        s.element_create("Woof.radio", "image", i["radio_off"], ("selected", i["radio_on"]),
                         padding=(0, 0, 8, 0), sticky="w")
        for kind, el in (("Checkbutton", "Woof.check"), ("Radiobutton", "Woof.radio")):
            s.layout(f"T{kind}", [(f"{kind}.padding", {"sticky": "nswe", "children": [
                (el, {"side": "left", "sticky": ""}),
                (f"{kind}.focus", {"side": "left", "sticky": "w", "children": [(f"{kind}.label", {"sticky": "nswe"})]}),
            ]})])


# ---- table ----------------------------------------------------------------------------------

class Table(ttk.Frame):
    """Treeview in a bordered card, with scrollbars, click-to-sort headings and optional checkboxes.

    Checkable rows: add(..., check=True/False). A row with checkable children is a group: it shows a
    tri-state box and clicking it ticks/unticks every child. on_toggle() fires after a click.
    """

    def __init__(self, parent, columns: list[tuple[str, str, int, str]], tree_heading: str | None = None,
                 selectmode="extended", height=14, on_toggle: Callable[[], None] | None = None):
        super().__init__(parent, style="Table.TFrame", padding=1)
        ids = [c[0] for c in columns]
        show = "tree headings" if tree_heading else "headings"
        self.tree = ttk.Treeview(self, columns=ids, show=show, selectmode=selectmode, height=height)
        if tree_heading:
            self.tree.heading("#0", text=tree_heading, anchor="w", command=lambda: self.sort("#0"))
            self.tree.column("#0", width=300, stretch=True)
        for cid, title, width, anchor in columns:
            self.tree.heading(cid, text=title, anchor=anchor, command=lambda c=cid: self.sort(c))
            self.tree.column(cid, width=width, anchor=anchor, stretch=anchor == "w")
        ys = ttk.Scrollbar(self, orient="vertical", command=self.tree.yview)
        xs = ttk.Scrollbar(self, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=ys.set, xscrollcommand=lambda a, b: self._xset(xs, a, b))
        self.tree.grid(row=0, column=0, sticky="nsew")
        ys.grid(row=0, column=1, sticky="ns")
        self._xs = xs
        self.rowconfigure(0, weight=1)
        self.columnconfigure(0, weight=1)
        self._desc: dict[str, bool] = {}
        self.state: dict[str, bool] = {}
        self.on_toggle = on_toggle
        app = parent._root()   # the App, also for tables inside dialogs
        self.images = getattr(app, "check_images", None)
        theme = getattr(app, "theme", None)
        if theme:
            self._tags(theme)
            theme.on_change(lambda: self._tags(theme))
        self.tree.bind("<Button-1>", self._click, add="+")
        self.tree.bind("<space>", self._space, add="+")
        self.tree.bind("<Double-1>", self._double, add="+")

    def _tags(self, theme):
        c = theme.c
        self.tree.tag_configure("off", foreground=c["faint"])
        self.tree.tag_configure("muted", foreground=c["muted"])
        self.tree.tag_configure("group", font=theme.fonts["semibold"])
        self.tree.tag_configure("good", foreground=c["good"])
        self.tree.tag_configure("warn", foreground=c["warn"])
        self.tree.tag_configure("bad", foreground=c["bad"])

    def _xset(self, xs, a, b):
        xs.set(a, b)
        if float(a) <= 0 and float(b) >= 1:
            xs.grid_remove()
        else:
            xs.grid(row=1, column=0, sticky="ew")

    # ---- rows
    def clear(self):
        self.tree.delete(*self.tree.get_children())
        self.state.clear()

    def add(self, iid: str | None = None, text: str = "", values=(), parent: str = "", check: bool | None = None,
            open: bool = True, tags=()) -> str:
        kw = {}
        if iid is not None:
            kw["iid"] = iid
        if check is not None and self.images:
            kw["image"] = self.images.img["on" if check else "off"]
        node = self.tree.insert(parent, "end", text=text, values=values, open=open, tags=tags, **kw)
        if check is not None:
            self.state[node] = bool(check)
            if parent:
                self._refresh_group(parent)
        return node

    def group(self, iid: str | None = None, text: str = "", values=(), open: bool = True, check: bool = True) -> str:
        """A parent row; its checkbox reflects its children (check=False: no checkbox)."""
        kw = {"iid": iid} if iid else {}
        if check and self.images:
            kw["image"] = self.images.img["off"]
        node = self.tree.insert("", "end", text=text, values=values, open=open, tags=("group",), **kw)
        if check:
            self.state[node] = False
        return node

    def children_checkable(self, node: str) -> list[str]:
        return [ch for ch in self.tree.get_children(node) if ch in self.state]

    def _refresh_group(self, node: str):
        kids = self.children_checkable(node)
        if not kids or node not in self.state or not self.images:
            return
        on = sum(self.state[k] for k in kids)
        kind = "on" if on == len(kids) else "off" if on == 0 else "mixed"
        self.state[node] = on == len(kids)
        self.tree.item(node, image=self.images.img[kind])

    def set_checked(self, node: str, value: bool):
        kids = self.children_checkable(node)
        targets = kids or [node]
        for k in targets:
            self.state[k] = value
            if self.images:
                self.tree.item(k, image=self.images.img["on" if value else "off"])
        if kids:
            self._refresh_group(node)
        parent = self.tree.parent(node)
        if parent:
            self._refresh_group(parent)

    def set_all(self, value: bool):
        for node in list(self.state):
            if not self.children_checkable(node):
                self.set_checked(node, value)
        if self.on_toggle:
            self.on_toggle()

    def checked(self) -> list[str]:
        """Checked leaf rows."""
        return [k for k, v in self.state.items() if v and not self.children_checkable(k)]

    def _click(self, ev):
        node = self.tree.identify_row(ev.y)
        if not node or node not in self.state or self.tree.identify_region(ev.x, ev.y) != "tree":
            return None
        # the checkbox toggles; the text selects the row (double-click the text to toggle too)
        if not self.tree.identify_element(ev.x, ev.y).endswith("image"):
            return None
        self.set_checked(node, not self.state[node])
        if self.on_toggle:
            self.on_toggle()
        return "break"

    def _double(self, ev):
        node = self.tree.identify_row(ev.y)
        if not node or node not in self.state:
            return None
        if self.tree.identify_element(ev.x, ev.y).endswith("image"):
            return self._click(ev)      # a fast second click on a checkbox is still a toggle
        if self.children_checkable(node):
            return None
        self.set_checked(node, not self.state[node])
        if self.on_toggle:
            self.on_toggle()
        return "break"

    def _space(self, _ev):
        for node in self.tree.selection():
            if node in self.state:
                self.set_checked(node, not self.state[node])
        if self.on_toggle:
            self.on_toggle()
        return "break"

    def sort(self, col: str):
        desc = self._desc[col] = not self._desc.get(col, False)
        get = (lambda i: self.tree.item(i, "text")) if col == "#0" else (lambda i: self.tree.set(i, col))
        items = sorted(self.tree.get_children(""), key=lambda i: sort_value(get(i)), reverse=desc)
        for n, i in enumerate(items):
            self.tree.move(i, "", n)


# ---- page building blocks -----------------------------------------------------------------

class BaseTab(ttk.Frame):
    title = "Tab"
    icon = ""

    def __init__(self, parent, app, padding=(28, 22, 28, 14)):
        super().__init__(parent, padding=padding)
        self.app = app
        self.busy = False

    def status(self, msg: str):
        self.app.post(lambda: self.app.set_status(msg))

    def run_bg(self, work: Callable[[], Any], done: Callable[[Any], None], label: str = "Working ..."):
        """Run work() on a thread; done(result) on the UI thread. Errors become a message box."""
        if self.busy:
            return
        self.busy = True
        self.app.set_busy(True, label)

        def runner():
            try:
                result = work()
            except Exception as e:  # report every failure to the user
                err = e
                self.app.post(lambda: self._finish_err(err))
                return
            self.app.post(lambda: self._finish_ok(done, result))

        threading.Thread(target=runner, daemon=True).start()

    def _finish_ok(self, done, result):
        self.busy = False
        self.app.set_busy(False)
        done(result)

    def _finish_err(self, err):
        self.busy = False
        self.app.set_busy(False)
        self.app.set_status("Error")
        messagebox.showerror("Woof Cleaner", str(err), parent=self)

    def on_show(self):
        """Called the first time the page becomes visible (lazy loading)."""


class Header(ttk.Frame):
    """Page title + subtitle on the left, `actions` frame on the right for the page's main buttons."""

    def __init__(self, parent, title: str, sub: str = ""):
        super().__init__(parent)
        self.actions = ttk.Frame(self)        # packed first so the buttons never get squeezed
        self.actions.pack(side="right", anchor="ne", pady=(6, 0))
        left = ttk.Frame(self)
        left.pack(side="left", fill="x", expand=True)
        ttk.Label(left, text=title, style="H1.TLabel").pack(anchor="w")
        if sub:
            self.sub = ttk.Label(left, text=sub, style="Sub.TLabel", wraplength=600, justify="left")
            self.sub.pack(anchor="w", pady=(3, 0))
            # wrap to the room left of the buttons, whatever the window size
            left.bind("<Configure>", lambda e: self.sub.configure(wraplength=max(240, e.width - 8)))


def heading(parent, text: str, sub: str = "") -> Header:
    return Header(parent, text, sub)


def toolbar(parent, pady=(14, 10)) -> ttk.Frame:
    f = ttk.Frame(parent)
    f.pack(fill="x", pady=pady)
    return f


class StatCard(ttk.Frame):
    def __init__(self, parent, label: str, value: str = "–", accent: bool = False):
        super().__init__(parent, style="Card.TFrame", padding=(16, 12))
        ttk.Label(self, text=label.upper(), style="CardMuted.TLabel").pack(anchor="w")
        self.value = ttk.Label(self, text=value, style="StatAccent.TLabel" if accent else "Stat.TLabel")
        self.value.pack(anchor="w", pady=(2, 0))
        self.sub = ttk.Label(self, text="", style="CardMuted.TLabel")
        self.sub.pack(anchor="w")

    def set(self, value: str, sub: str = ""):
        self.value.config(text=value)
        self.sub.config(text=sub)


def stat_row(parent, specs: list[tuple[str, bool]]) -> list[StatCard]:
    row = ttk.Frame(parent)
    row.pack(fill="x", pady=(0, 12))
    cards = []
    for i, (label, accent) in enumerate(specs):
        c = StatCard(row, label, accent=accent)
        c.grid(row=0, column=i, sticky="nsew", padx=(0 if i == 0 else 10, 0))
        row.columnconfigure(i, weight=1, uniform="stat")
        cards.append(c)
    return cards


def text_box(parent, app, height=7, mono=True) -> tk.Text:
    t = tk.Text(parent, height=height, wrap="none", relief="flat", borderwidth=0, highlightthickness=1,
                padx=10, pady=8, font=app.theme.fonts["mono" if mono else "body"])
    app.theme.paint(t, bg="surface", fg="text", insertbackground="text", selectbackground="select",
                    selectforeground="text", highlightbackground="border", highlightcolor="accent")
    return t


def confirm(parent, title: str, text: str) -> bool:
    return messagebox.askyesno(title, text, icon="warning", parent=parent)
