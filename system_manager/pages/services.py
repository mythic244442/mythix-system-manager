"""Systemd Services Manager page (system & user units)."""
from ..core import *


class ServicesMixin:
    # ────────────────────────────────────────────────────────
    def _build_services_tab(self):
        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        bar = Gtk.Box(spacing=6)
        bar.get_style_context().add_class("tab-action-bar")
        bar.set_margin_start(8); bar.set_margin_end(8); bar.set_margin_top(6); bar.set_margin_bottom(6)

        self.sv_search = Gtk.SearchEntry()
        self.sv_search.set_placeholder_text("Filter services (e.g. ollama, ssh, ufw, pipewire)…")
        self.sv_search.set_hexpand(True)
        self.sv_search.connect("search-changed", self._on_sv_filter_changed)
        bar.pack_start(self.sv_search, True, True, 0)

        self.sv_scope_combo = Gtk.ComboBoxText()
        for opt in ("System Services", "User Services", "Running Only", "Failed Only"):
            self.sv_scope_combo.append_text(opt)
        self.sv_scope_combo.set_active(0)
        self.sv_scope_combo.connect("changed", self._on_sv_scope_changed)
        bar.pack_start(self.sv_scope_combo, False, False, 0)

        self.btn_sv_start   = self._mkbtn("media-playback-start-symbolic",   "Start",   lambda *_: self._on_sv_action("start"))
        self.btn_sv_stop    = self._mkbtn("media-playback-stop-symbolic",    "Stop",    lambda *_: self._on_sv_action("stop"))
        self.btn_sv_restart = self._mkbtn("view-refresh-symbolic",           "Restart", lambda *_: self._on_sv_action("restart"))
        self.btn_sv_logs    = self._mkbtn("utilities-terminal-symbolic",     "Logs",    self._on_sv_view_logs)
        self.btn_sv_stop.get_style_context().add_class("btn-warn")

        for b in (self.btn_sv_start, self.btn_sv_stop, self.btn_sv_restart, self.btn_sv_logs):
            bar.pack_start(b, False, False, 0)

        vbox.pack_start(bar, False, False, 0)
        vbox.pack_start(Gtk.Separator(), False, False, 0)

        # active, enabled, unit, active_state, sub_state, description, scope
        self.sv_store = Gtk.ListStore(bool, bool, str, str, str, str, str)
        self.sv_tree  = Gtk.TreeView(model=self.sv_store)
        self.sv_tree.set_headers_clickable(True)
        self.sv_tree.set_enable_search(True)
        self.sv_tree.set_search_column(COL_SV_UNIT)
        self.sv_tree.get_selection().set_mode(Gtk.SelectionMode.SINGLE)

        tog_en = Gtk.CellRendererToggle()
        tog_en.connect("toggled", self._on_sv_enable_toggle)
        c_en = Gtk.TreeViewColumn("Boot", tog_en, active=COL_SV_ENABLED)
        c_en.set_fixed_width(48)
        self.sv_tree.append_column(c_en)

        cols = [
            ("Service Unit", COL_SV_UNIT,  230, False),
            ("State",        COL_SV_STATE,  90, False),
            ("Sub",          COL_SV_SUB,    95, False),
            ("Description",  COL_SV_DESC,  320, True),
        ]
        for lbl, idx, w, exp in cols:
            r = Gtk.CellRendererText()
            r.set_property("ellipsize", Pango.EllipsizeMode.END)
            c = Gtk.TreeViewColumn(lbl, r, text=idx)
            c.set_fixed_width(w)
            c.set_resizable(True)
            if exp:
                c.set_expand(True)
            c.set_sort_column_id(idx)
            c.set_cell_data_func(r, self._cell_sv_color)
            self.sv_tree.append_column(c)

        sw = Gtk.ScrolledWindow()
        sw.add(self.sv_tree)
        vbox.pack_start(sw, True, True, 0)

        vbox.pack_start(Gtk.Separator(), False, False, 0)
        sw2 = Gtk.ScrolledWindow()
        sw2.set_min_content_height(85)
        self.sv_log_buf = Gtk.TextBuffer()
        sv_log_view = Gtk.TextView(buffer=self.sv_log_buf)
        sv_log_view.set_editable(False)
        sv_log_view.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        sv_log_view.get_style_context().add_class("log-view")
        sw2.add(sv_log_view)
        vbox.pack_start(sw2, False, False, 0)
        return vbox

    def _cell_sv_color(self, col, cell, model, it, data=None):
        st = (model.get_value(it, COL_SV_STATE) or "").lower()
        sub = (model.get_value(it, COL_SV_SUB) or "").lower()
        if st == "failed" or sub == "failed":
            cell.set_property("foreground", "#ef5350")
        elif st == "active":
            cell.set_property("foreground", "#4dd0e1" if sub == "running" else "#b39ddb")
        else:
            cell.set_property("foreground", "#757590")

    def _svlog(self, text):
        GLib.idle_add(self._svlog_append, text)

    def _svlog_append(self, text):
        end = self.sv_log_buf.get_end_iter()
        self.sv_log_buf.insert(end, f"[{datetime.now().strftime('%H:%M:%S')}] {text}\n")

    def _refresh_services(self, *_):
        self._set_status("Loading systemd services…")
        threading.Thread(target=self._services_worker, daemon=True).start()

    def _services_worker(self):
        scope_txt = self.sv_scope_combo.get_active_text() if hasattr(self, "sv_scope_combo") else "System Services"
        is_user = (scope_txt == "User Services")
        scope = "user" if is_user else "system"
        rows = []
        try:
            # 1. Read unit-files state (enabled / disabled / static)
            uf_cmd = ["systemctl"] + (["--user"] if is_user else []) + [
                "list-unit-files", "--type=service", "--no-pager", "--no-legend"
            ]
            r_uf = run_as_user(uf_cmd, timeout=15) if is_user else subprocess.run(
                uf_cmd, capture_output=True, text=True, timeout=15
            )
            enabled_map = {}
            for ln in (r_uf.stdout or "").splitlines():
                parts = ln.split()
                if len(parts) >= 2 and parts[0].endswith(".service") and "@" not in parts[0]:
                    unit_short = parts[0][:-8]
                    enabled_map[unit_short] = parts[1] in ("enabled", "enabled-runtime", "static")

            # 2. Read live unit states (active / inactive / failed + description)
            u_cmd = ["systemctl"] + (["--user"] if is_user else []) + [
                "list-units", "--type=service", "--all", "--no-pager", "--no-legend"
            ]
            r_u = run_as_user(u_cmd, timeout=15) if is_user else subprocess.run(
                u_cmd, capture_output=True, text=True, timeout=15
            )
            seen = set()
            for ln in (r_u.stdout or "").splitlines():
                ln = ln.lstrip("●").strip()
                parts = ln.split(None, 4)
                if len(parts) < 4:
                    continue
                unit, _load, active_st, sub_st = parts[0], parts[1], parts[2], parts[3]
                desc = parts[4] if len(parts) > 4 else ""
                if not unit.endswith(".service"):
                    continue
                short = unit[:-8]
                seen.add(short)
                is_act = (active_st == "active")
                is_en = enabled_map.get(short, is_act)
                rows.append([is_act, is_en, short, active_st, sub_st, desc, scope])

            for short, is_en in sorted(enabled_map.items()):
                if short not in seen:
                    rows.append([False, is_en, short, "inactive", "dead", "", scope])

            self._services = rows
            self._services_loaded = True
            GLib.idle_add(self._apply_sv_filter)
        except Exception as e:
            self._svlog(f"Error loading services: {e}")
        finally:
            self._set_status("Ready")

    def _on_sv_scope_changed(self, *_):
        self._refresh_services()

    def _on_sv_filter_changed(self, *_):
        self._apply_sv_filter()

    def _apply_sv_filter(self):
        if not hasattr(self, "sv_store"):
            return
        term = (self.sv_search.get_text() or "").strip().lower()
        scope_txt = self.sv_scope_combo.get_active_text() or "System Services"
        self.sv_store.clear()
        for r in getattr(self, "_services", []):
            is_act, is_en, unit, active_st, sub_st, desc, scope = r
            if scope_txt == "Running Only" and sub_st != "running":
                continue
            if scope_txt == "Failed Only" and active_st != "failed" and sub_st != "failed":
                continue
            if term and term not in unit.lower() and term not in desc.lower():
                continue
            self.sv_store.append(r)

    def _get_selected_service(self):
        model, it = self.sv_tree.get_selection().get_selected()
        if it is None:
            return None, None, None
        return (
            model.get_value(it, COL_SV_UNIT),
            model.get_value(it, COL_SV_SCOPE),
            model.get_value(it, COL_SV_ENABLED),
        )

    def _on_sv_action(self, action):
        unit, scope, _en = self._get_selected_service()
        if not unit:
            self._show_error("No selection", "Select a service first.")
            return
        def _worker():
            self._svlog(f"Running systemctl {action} {unit}.service ({scope})…")
            try:
                cmd = ["systemctl"] + (["--user"] if scope == "user" else []) + [action, f"{unit}.service"]
                r = run_as_user(cmd, timeout=30) if scope == "user" else subprocess.run(
                    cmd, capture_output=True, text=True, timeout=30
                )
                if r.returncode == 0:
                    self._svlog(f"✓ {unit}.service: {action} succeeded.")
                else:
                    err = (r.stderr or r.stdout or "").strip()
                    self._svlog(f"✗ {unit}.service {action} failed (exit {r.returncode}): {err}")
            except Exception as e:
                self._svlog(f"Error: {e}")
            GLib.idle_add(self._refresh_services)
        threading.Thread(target=_worker, daemon=True).start()

    def _on_sv_enable_toggle(self, _widget, path):
        row = self.sv_store[path]
        unit = row[COL_SV_UNIT]
        scope = row[COL_SV_SCOPE]
        cur_en = row[COL_SV_ENABLED]
        action = "disable" if cur_en else "enable"
        def _worker():
            self._svlog(f"Running systemctl {action} {unit}.service ({scope})…")
            try:
                cmd = ["systemctl"] + (["--user"] if scope == "user" else []) + [action, f"{unit}.service"]
                r = run_as_user(cmd, timeout=20) if scope == "user" else subprocess.run(
                    cmd, capture_output=True, text=True, timeout=20
                )
                if r.returncode == 0:
                    self._svlog(f"✓ {unit}.service {action}d on boot.")
                    GLib.idle_add(lambda: row.__setitem__(COL_SV_ENABLED, not cur_en))
                else:
                    self._svlog(f"✗ Failed to {action} {unit}: {(r.stderr or '').strip()}")
            except Exception as e:
                self._svlog(f"Error: {e}")
        threading.Thread(target=_worker, daemon=True).start()

    def _on_sv_view_logs(self, *_):
        unit, _scope, _en = self._get_selected_service()
        if not unit:
            self._show_error("No selection", "Select a service to view its logs.")
            return
        if hasattr(self, "log_unit_entry"):
            self.log_unit_entry.set_text(f"{unit}.service")
        if "logs" in getattr(self, "_nav_rows", {}):
            self.sidebar.select_row(self._nav_rows["logs"])
            self._on_log_fetch()
