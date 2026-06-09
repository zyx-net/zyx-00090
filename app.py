import tkinter as tk
from tkinter import ttk, messagebox, filedialog, simpledialog
from datetime import datetime
import os
import sys

from database import init_database, DB_PATH
from auth import (AuthManager, ROLE_DISPLAY, OPERATION_TYPE_DISPLAY,
                  STATUS_DISPLAY, RESERVATION_OPERATION_DISPLAY,
                  RESERVATION_STATUS_DISPLAY)
from business import ReagentManager, OperationError
from csv_utils import CSVManager


class ReagentManagementApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("实验室试剂管理系统")
        self.root.geometry("1200x800")
        self.root.minsize(1000, 700)

        init_database()

        self.auth = AuthManager()
        self.manager = ReagentManager(self.auth)
        self.csv_manager = CSVManager(self.auth)

        self.current_tab = None
        self.selected_reagent_id = None
        self.selected_approval_id = None
        self.selected_reservation_id = None
        self.selected_reservation_log_id = None

        self._current_preview_hash = None
        self._current_preview_result = None

        self.setup_styles()
        self.show_login_dialog()

    def setup_styles(self):
        style = ttk.Style()
        style.theme_use('clam')

        style.configure('Treeview', rowheight=28)
        style.configure('Treeview.Heading', font=('Microsoft YaHei', 10, 'bold'))
        style.configure('TNotebook.Tab', font=('Microsoft YaHei', 10))
        style.configure('TLabel', font=('Microsoft YaHei', 10))
        style.configure('TButton', font=('Microsoft YaHei', 10))
        style.configure('TEntry', font=('Microsoft YaHei', 10))
        style.configure('TCombobox', font=('Microsoft YaHei', 10))

        style.configure('Expired.Treeview', background='#ffcccc')
        style.configure('LowStock.Treeview', background='#fff3cd')
        style.configure('Normal.Treeview', background='white')

    def show_login_dialog(self):
        login_window = tk.Toplevel(self.root)
        login_window.title("用户登录")
        login_window.geometry("400x300")
        login_window.resizable(False, False)
        login_window.transient(self.root)
        login_window.grab_set()

        screen_width = login_window.winfo_screenwidth()
        screen_height = login_window.winfo_screenheight()
        x = (screen_width - 400) // 2
        y = (screen_height - 300) // 2
        login_window.geometry(f"400x300+{x}+{y}")

        frame = ttk.Frame(login_window, padding=30)
        frame.pack(fill='both', expand=True)

        ttk.Label(frame, text="实验室试剂管理系统", font=('Microsoft YaHei', 16, 'bold')).pack(pady=(0, 20))
        ttk.Label(frame, text="请选择用户身份登录", font=('Microsoft YaHei', 10)).pack(pady=(0, 20))

        users = self.auth.get_all_users()
        user_display = [f"{u['display_name']}（{ROLE_DISPLAY.get(u['role'], u['role'])}）" for u in users]

        self.login_var = tk.StringVar()
        combo = ttk.Combobox(frame, textvariable=self.login_var, values=user_display, state='readonly', width=30)
        combo.pack(pady=10)
        if user_display:
            combo.current(0)

        def do_login():
            idx = combo.current()
            if idx >= 0:
                user = users[idx]
                if self.auth.login(user["username"]):
                    login_window.destroy()
                    self.setup_main_ui()
                else:
                    messagebox.showerror("登录失败", "用户登录失败")

        ttk.Button(frame, text="登 录", command=do_login, width=20).pack(pady=20)

        login_window.protocol("WM_DELETE_WINDOW", lambda: (login_window.destroy(), self.root.destroy()))

    def setup_main_ui(self):
        main_frame = ttk.Frame(self.root, padding=10)
        main_frame.pack(fill='both', expand=True)

        header_frame = ttk.Frame(main_frame)
        header_frame.pack(fill='x', pady=(0, 10))

        ttk.Label(header_frame, text="实验室试剂管理系统", font=('Microsoft YaHei', 18, 'bold')).pack(side='left')

        user_info_frame = ttk.Frame(header_frame)
        user_info_frame.pack(side='right')

        ttk.Label(user_info_frame, text=f"当前用户：{self.auth.current_user['display_name']}",
                  font=('Microsoft YaHei', 10)).pack(side='left', padx=5)
        ttk.Label(user_info_frame, text=f"角色：{self.auth.get_role_display()}",
                  font=('Microsoft YaHei', 10, 'bold'), foreground='#1976D2').pack(side='left', padx=5)
        ttk.Button(user_info_frame, text="切换用户", command=self.switch_user).pack(side='left', padx=10)

        self.notebook = ttk.Notebook(main_frame)

        self.tab_inventory = ttk.Frame(self.notebook)
        self.tab_reservation = ttk.Frame(self.notebook)
        self.tab_approval = ttk.Frame(self.notebook)
        self.tab_operations = ttk.Frame(self.notebook)
        self.tab_history = ttk.Frame(self.notebook)
        self.tab_reservation_logs = ttk.Frame(self.notebook)
        self.tab_ledger = ttk.Frame(self.notebook)
        self.tab_import_export = ttk.Frame(self.notebook)

        self.notebook.add(self.tab_inventory, text='库存管理')
        self.notebook.add(self.tab_reservation, text='预约管理')
        self.notebook.add(self.tab_approval, text='预约审核')
        self.notebook.add(self.tab_operations, text='业务操作')
        self.notebook.add(self.tab_history, text='操作历史')
        self.notebook.add(self.tab_reservation_logs, text='预约日志')
        self.notebook.add(self.tab_ledger, text='库存台账')
        self.notebook.add(self.tab_import_export, text='导入导出')

        status_bar = ttk.Frame(main_frame)
        status_bar.pack(fill='x', side='bottom', pady=(10, 0))

        self.status_var = tk.StringVar(value="就绪")
        ttk.Label(status_bar, textvariable=self.status_var, font=('Microsoft YaHei', 9)).pack(side='left')

        db_info = f"数据库：{os.path.basename(DB_PATH)}"
        ttk.Label(status_bar, text=db_info, font=('Microsoft YaHei', 9)).pack(side='right')

        self.notebook.pack(fill='both', expand=True)

        self.setup_inventory_tab()
        self.setup_reservation_tab()
        self.setup_approval_tab()
        self.setup_operations_tab()
        self.setup_history_tab()
        self.setup_reservation_logs_tab()
        self.setup_ledger_tab()
        self.setup_import_export_tab()

        self.notebook.bind('<<NotebookTabChanged>>', self.on_tab_changed)

    def switch_user(self):
        if messagebox.askyesno("确认", "确定要切换用户吗？"):
            self.auth.logout()
            for widget in self.root.winfo_children():
                widget.destroy()
            self.setup_styles()
            self.show_login_dialog()

    def on_tab_changed(self, event):
        selected = self.notebook.select()
        tab_text = self.notebook.tab(selected, 'text')
        self.current_tab = tab_text

        if tab_text == '库存管理':
            self.refresh_inventory()
        elif tab_text == '预约管理':
            self.refresh_reservations()
        elif tab_text == '预约审核':
            self.refresh_reservation_approvals()
        elif tab_text == '操作历史':
            self.refresh_history()
        elif tab_text == '预约日志':
            self.refresh_reservation_logs()
        elif tab_text == '库存台账':
            self.refresh_ledger()

    def set_status(self, message: str):
        self.status_var.set(message)
        self.root.after(5000, lambda: self.status_var.set("就绪"))

    def setup_inventory_tab(self):
        frame = self.tab_inventory

        filter_frame = ttk.LabelFrame(frame, text="筛选条件", padding=10)
        filter_frame.pack(fill='x', pady=10, padx=10)

        ttk.Label(filter_frame, text="批号：").grid(row=0, column=0, padx=5, pady=5)
        self.filter_batch = ttk.Entry(filter_frame, width=20)
        self.filter_batch.grid(row=0, column=1, padx=5, pady=5)

        ttk.Label(filter_frame, text="过期状态：").grid(row=0, column=2, padx=5, pady=5)
        self.filter_expired = ttk.Combobox(filter_frame, values=["全部", "已过期", "未过期"], state='readonly', width=10)
        self.filter_expired.grid(row=0, column=3, padx=5, pady=5)
        self.filter_expired.current(0)

        ttk.Label(filter_frame, text="低库存：").grid(row=0, column=4, padx=5, pady=5)
        self.filter_low_stock = ttk.Combobox(filter_frame, values=["全部", "仅低库存", "正常库存"], state='readonly', width=10)
        self.filter_low_stock.grid(row=0, column=5, padx=5, pady=5)
        self.filter_low_stock.current(0)

        ttk.Button(filter_frame, text="查询", command=self.refresh_inventory).grid(row=0, column=6, padx=10, pady=5)
        ttk.Button(filter_frame, text="重置", command=self.reset_filters).grid(row=0, column=7, padx=5, pady=5)

        btn_frame = ttk.Frame(frame)
        btn_frame.pack(fill='x', padx=10, pady=5)

        if self.auth.has_permission("manage_reagents"):
            ttk.Button(btn_frame, text="新增试剂", command=self.add_reagent_dialog).pack(side='left', padx=5)
        if self.auth.has_permission("stock_in"):
            ttk.Button(btn_frame, text="入库", command=self.stock_in_dialog).pack(side='left', padx=5)
        if self.auth.has_permission("apply_use"):
            ttk.Button(btn_frame, text="申请领用", command=self.apply_use_dialog).pack(side='left', padx=5)
        if self.auth.has_permission("create_reservation"):
            ttk.Button(btn_frame, text="预约领用", command=self.create_reservation_dialog).pack(side='left', padx=5)
        if self.auth.has_permission("return_reagent"):
            ttk.Button(btn_frame, text="归还", command=self.return_dialog).pack(side='left', padx=5)
        if self.auth.has_permission("scrap"):
            ttk.Button(btn_frame, text="报废", command=self.scrap_dialog).pack(side='left', padx=5)
        if self.auth.has_permission("stocktake"):
            ttk.Button(btn_frame, text="盘点", command=self.stocktake_dialog).pack(side='left', padx=5)

        tree_frame = ttk.Frame(frame)
        tree_frame.pack(fill='both', expand=True, padx=10, pady=10)

        columns = ("id", "name", "batch", "quantity", "locked", "available", "unit", "expiration",
                  "threshold", "spec", "manufacturer", "storage", "reservation",
                  "is_expired", "is_low")
        self.inventory_tree = ttk.Treeview(tree_frame, columns=columns, show='headings')

        headings = [
            ("id", "ID", 50),
            ("name", "试剂名称", 130),
            ("batch", "批号", 110),
            ("quantity", "总库存", 70),
            ("locked", "已锁定", 70),
            ("available", "可用量", 70),
            ("unit", "单位", 50),
            ("expiration", "过期日期", 90),
            ("threshold", "低库存阈值", 80),
            ("spec", "规格", 90),
            ("manufacturer", "生产厂商", 110),
            ("storage", "储存条件", 90),
            ("reservation", "预约摘要", 180),
            ("is_expired", "过期状态", 70),
            ("is_low", "库存状态", 70)
        ]

        for col, text, width in headings:
            self.inventory_tree.heading(col, text=text)
            self.inventory_tree.column(col, width=width, anchor='center')

        scrollbar = ttk.Scrollbar(tree_frame, orient='vertical', command=self.inventory_tree.yview)
        self.inventory_tree.configure(yscrollcommand=scrollbar.set)

        self.inventory_tree.pack(side='left', fill='both', expand=True)
        scrollbar.pack(side='right', fill='y')

        self.inventory_tree.bind('<<TreeviewSelect>>', self.on_reagent_select)
        self.inventory_tree.bind('<Double-1>', self.show_reagent_detail)

        self.refresh_inventory()

    def reset_filters(self):
        self.filter_batch.delete(0, 'end')
        self.filter_expired.current(0)
        self.filter_low_stock.current(0)
        self.refresh_inventory()

    def get_inventory_filters(self):
        filters = {}
        batch = self.filter_batch.get().strip()
        if batch:
            filters["batch_number"] = batch

        expired_val = self.filter_expired.get()
        if expired_val == "已过期":
            filters["expired"] = True
        elif expired_val == "未过期":
            filters["expired"] = False

        low_stock_val = self.filter_low_stock.get()
        if low_stock_val == "仅低库存":
            filters["low_stock"] = True

        return filters

    def refresh_inventory(self):
        for item in self.inventory_tree.get_children():
            self.inventory_tree.delete(item)

        try:
            filters = self.get_inventory_filters()
            reagents = self.manager.get_reagents_with_lock_info(filters)

            for r in reagents:
                expired_status = "已过期" if r["is_expired"] else "正常"
                stock_status = "低库存" if r["is_low_stock"] else "正常"

                exp_date = r["expiration_date"] if r["expiration_date"] else "无"
                locked = r.get("locked_quantity", 0)
                available = r.get("available_quantity", r["quantity"])
                reservation_summary = r.get("reservation_summary", "") or "-"

                tags = ()
                if r["is_expired"]:
                    tags = ('expired',)
                elif r["is_low_stock"]:
                    tags = ('low_stock',)

                self.inventory_tree.insert('', 'end', iid=str(r["id"]), values=(
                    r["id"], r["name"], r["batch_number"], r["quantity"],
                    locked, available, r["unit"], exp_date, r["low_stock_threshold"],
                    r["specification"] or "-", r["manufacturer"] or "-",
                    r["storage_condition"] or "-", reservation_summary,
                    expired_status, stock_status
                ), tags=tags)

            self.inventory_tree.tag_configure('expired', background='#ffcccc')
            self.inventory_tree.tag_configure('low_stock', background='#fff3cd')

            self.set_status(f"查询到 {len(reagents)} 条试剂记录")
        except OperationError as e:
            messagebox.showerror("错误", str(e))

    def on_reagent_select(self, event):
        selection = self.inventory_tree.selection()
        if selection:
            self.selected_reagent_id = int(selection[0])

    def show_reagent_detail(self, event):
        selection = self.inventory_tree.selection()
        if not selection:
            return

        from database import ReagentDB
        reagent = ReagentDB.get_by_id(int(selection[0]))
        if not reagent:
            return

        detail_window = tk.Toplevel(self.root)
        detail_window.title(f"试剂详情 - {reagent['name']}")
        detail_window.geometry("500x500")
        detail_window.transient(self.root)

        frame = ttk.Frame(detail_window, padding=20)
        frame.pack(fill='both', expand=True)

        info = [
            ("试剂名称", reagent["name"]),
            ("批号", reagent["batch_number"]),
            ("当前库存", f"{reagent['quantity']} {reagent['unit']}"),
            ("低库存阈值", str(reagent["low_stock_threshold"])),
            ("过期日期", reagent["expiration_date"] or "无"),
            ("规格", reagent["specification"] or "-"),
            ("生产厂商", reagent["manufacturer"] or "-"),
            ("储存条件", reagent["storage_condition"] or "-"),
            ("备注", reagent["remarks"] or "-"),
            ("创建时间", reagent["created_at"]),
            ("更新时间", reagent["updated_at"])
        ]

        for i, (label, value) in enumerate(info):
            ttk.Label(frame, text=f"{label}：", font=('Microsoft YaHei', 10, 'bold')).grid(row=i, column=0, sticky='e', padx=5, pady=5)
            ttk.Label(frame, text=value, font=('Microsoft YaHei', 10)).grid(row=i, column=1, sticky='w', padx=5, pady=5)

        is_expired = ReagentDB.is_expired(reagent["id"])
        is_low = reagent["quantity"] <= reagent["low_stock_threshold"]

        status_text = []
        if is_expired:
            status_text.append(("已过期", "red"))
        if is_low:
            status_text.append(("低库存", "orange"))
        if not status_text:
            status_text.append(("状态正常", "green"))

        for i, (text, color) in enumerate(status_text, start=len(info)):
            ttk.Label(frame, text=text, foreground=color, font=('Microsoft YaHei', 10, 'bold')).grid(row=i, column=0, columnspan=2, pady=5)

    def add_reagent_dialog(self):
        dialog = tk.Toplevel(self.root)
        dialog.title("新增试剂")
        dialog.geometry("500x550")
        dialog.transient(self.root)
        dialog.grab_set()

        frame = ttk.Frame(dialog, padding=20)
        frame.pack(fill='both', expand=True)

        fields = {}

        labels = [
            ("试剂名称", "name", True),
            ("批号", "batch_number", True),
            ("数量", "quantity", True),
            ("单位", "unit", True),
            ("过期日期 (YYYY-MM-DD)", "expiration_date", False),
            ("低库存阈值", "low_stock_threshold", False),
            ("规格", "specification", False),
            ("生产厂商", "manufacturer", False),
            ("储存条件", "storage_condition", False),
            ("备注", "remarks", False)
        ]

        for i, (label, key, required) in enumerate(labels):
            lbl_text = f"{label} *" if required else label
            ttk.Label(frame, text=lbl_text).grid(row=i, column=0, sticky='e', padx=5, pady=8)
            entry = ttk.Entry(frame, width=35)
            entry.grid(row=i, column=1, padx=5, pady=8)
            fields[key] = entry

        fields["low_stock_threshold"].insert(0, "10")

        def do_add():
            try:
                name = fields["name"].get().strip()
                batch_number = fields["batch_number"].get().strip()
                quantity_str = fields["quantity"].get().strip()
                unit = fields["unit"].get().strip()

                if not name or not batch_number or not unit:
                    messagebox.showwarning("提示", "请填写所有必填项（带 *）")
                    return

                try:
                    quantity = int(quantity_str) if quantity_str else 0
                except ValueError:
                    messagebox.showerror("错误", "数量必须是整数")
                    return

                try:
                    threshold_str = fields["low_stock_threshold"].get().strip()
                    low_stock_threshold = int(threshold_str) if threshold_str else 10
                except ValueError:
                    low_stock_threshold = 10

                expiration_date = fields["expiration_date"].get().strip() or None
                if expiration_date:
                    try:
                        datetime.strptime(expiration_date, "%Y-%m-%d")
                    except ValueError:
                        messagebox.showerror("错误", "过期日期格式错误，请使用 YYYY-MM-DD")
                        return

                _, msg = self.manager.create_reagent(
                    name=name,
                    batch_number=batch_number,
                    quantity=quantity,
                    unit=unit,
                    expiration_date=expiration_date,
                    low_stock_threshold=low_stock_threshold,
                    specification=fields["specification"].get().strip(),
                    manufacturer=fields["manufacturer"].get().strip(),
                    storage_condition=fields["storage_condition"].get().strip(),
                    remarks=fields["remarks"].get().strip()
                )
                messagebox.showinfo("成功", msg)
                self.refresh_inventory()
                dialog.destroy()
            except OperationError as e:
                messagebox.showerror("错误", str(e))

        btn_frame = ttk.Frame(frame)
        btn_frame.grid(row=len(labels), column=0, columnspan=2, pady=20)
        ttk.Button(btn_frame, text="确 定", command=do_add, width=15).pack(side='left', padx=10)
        ttk.Button(btn_frame, text="取 消", command=dialog.destroy, width=15).pack(side='left', padx=10)

    def get_selected_reagent(self) -> dict:
        from database import ReagentDB
        if not self.selected_reagent_id:
            messagebox.showwarning("提示", "请先在列表中选择一个试剂")
            return None
        reagent = ReagentDB.get_by_id(self.selected_reagent_id)
        if not reagent:
            messagebox.showerror("错误", "试剂不存在")
            return None
        return reagent

    def stock_in_dialog(self):
        reagent = self.get_selected_reagent()
        if not reagent:
            return

        dialog = tk.Toplevel(self.root)
        dialog.title("试剂入库")
        dialog.geometry("400x300")
        dialog.transient(self.root)
        dialog.grab_set()

        frame = ttk.Frame(dialog, padding=20)
        frame.pack(fill='both', expand=True)

        ttk.Label(frame, text=f"试剂：{reagent['name']} ({reagent['batch_number']})",
                  font=('Microsoft YaHei', 10, 'bold')).grid(row=0, column=0, columnspan=2, pady=10)
        ttk.Label(frame, text=f"当前库存：{reagent['quantity']} {reagent['unit']}").grid(row=1, column=0, columnspan=2, pady=5)

        ttk.Label(frame, text="入库数量：").grid(row=2, column=0, sticky='e', padx=5, pady=15)
        qty_entry = ttk.Entry(frame, width=20)
        qty_entry.grid(row=2, column=1, padx=5, pady=15)
        qty_entry.focus()

        ttk.Label(frame, text="备注：").grid(row=3, column=0, sticky='e', padx=5, pady=5)
        remarks_entry = ttk.Entry(frame, width=30)
        remarks_entry.grid(row=3, column=1, padx=5, pady=5)

        def do_stock_in():
            try:
                qty_str = qty_entry.get().strip()
                if not qty_str:
                    messagebox.showwarning("提示", "请输入入库数量")
                    return
                quantity = int(qty_str)
                _, msg = self.manager.stock_in(
                    reagent["id"], quantity, remarks_entry.get().strip()
                )
                messagebox.showinfo("成功", msg)
                self.refresh_inventory()
                dialog.destroy()
            except ValueError:
                messagebox.showerror("错误", "数量必须是整数")
            except OperationError as e:
                messagebox.showerror("错误", str(e))

        btn_frame = ttk.Frame(frame)
        btn_frame.grid(row=4, column=0, columnspan=2, pady=20)
        ttk.Button(btn_frame, text="确 定", command=do_stock_in, width=12).pack(side='left', padx=10)
        ttk.Button(btn_frame, text="取 消", command=dialog.destroy, width=12).pack(side='left', padx=10)

    def apply_use_dialog(self):
        reagent = self.get_selected_reagent()
        if not reagent:
            return

        from database import ReagentDB
        if ReagentDB.is_expired(reagent["id"]):
            messagebox.showerror("错误", f"试剂已过期（过期日期：{reagent['expiration_date']}），禁止领用")
            return

        dialog = tk.Toplevel(self.root)
        dialog.title("申请领用")
        dialog.geometry("400x300")
        dialog.transient(self.root)
        dialog.grab_set()

        frame = ttk.Frame(dialog, padding=20)
        frame.pack(fill='both', expand=True)

        ttk.Label(frame, text=f"试剂：{reagent['name']} ({reagent['batch_number']})",
                  font=('Microsoft YaHei', 10, 'bold')).grid(row=0, column=0, columnspan=2, pady=10)
        ttk.Label(frame, text=f"当前库存：{reagent['quantity']} {reagent['unit']}").grid(row=1, column=0, columnspan=2, pady=5)

        ttk.Label(frame, text="领用数量：").grid(row=2, column=0, sticky='e', padx=5, pady=15)
        qty_entry = ttk.Entry(frame, width=20)
        qty_entry.grid(row=2, column=1, padx=5, pady=15)
        qty_entry.focus()

        ttk.Label(frame, text="用途：").grid(row=3, column=0, sticky='e', padx=5, pady=5)
        remarks_entry = ttk.Entry(frame, width=30)
        remarks_entry.grid(row=3, column=1, padx=5, pady=5)

        def do_apply():
            try:
                qty_str = qty_entry.get().strip()
                if not qty_str:
                    messagebox.showwarning("提示", "请输入领用数量")
                    return
                quantity = int(qty_str)
                _, msg = self.manager.apply_use(
                    reagent["id"], quantity, remarks_entry.get().strip()
                )
                messagebox.showinfo("成功", msg)
                self.refresh_inventory()
                dialog.destroy()
            except ValueError:
                messagebox.showerror("错误", "数量必须是整数")
            except OperationError as e:
                messagebox.showerror("错误", str(e))

        btn_frame = ttk.Frame(frame)
        btn_frame.grid(row=4, column=0, columnspan=2, pady=20)
        ttk.Button(btn_frame, text="提交申请", command=do_apply, width=12).pack(side='left', padx=10)
        ttk.Button(btn_frame, text="取 消", command=dialog.destroy, width=12).pack(side='left', padx=10)

    def create_reservation_dialog(self):
        reagent = self.get_selected_reagent()
        if not reagent:
            return

        from database import ReagentDB, ReagentLockDB
        if ReagentDB.is_expired(reagent["id"]):
            messagebox.showerror("错误", f"试剂已过期（过期日期：{reagent['expiration_date']}），禁止预约")
            return

        available = ReagentLockDB.get_available_quantity(reagent["id"])

        dialog = tk.Toplevel(self.root)
        dialog.title("预约领用")
        dialog.geometry("450x400")
        dialog.transient(self.root)
        dialog.grab_set()

        frame = ttk.Frame(dialog, padding=20)
        frame.pack(fill='both', expand=True)

        ttk.Label(frame, text=f"试剂：{reagent['name']} ({reagent['batch_number']})",
                  font=('Microsoft YaHei', 10, 'bold')).grid(row=0, column=0, columnspan=2, pady=10)
        ttk.Label(frame, text=f"总库存：{reagent['quantity']} {reagent['unit']}").grid(row=1, column=0, columnspan=2, pady=2)
        ttk.Label(frame, text=f"已锁定：{reagent.get('locked_quantity', 0)} {reagent['unit']}",
                  foreground='#FF9800').grid(row=2, column=0, columnspan=2, pady=2)
        ttk.Label(frame, text=f"可用量：{available} {reagent['unit']}",
                  foreground='#4CAF50', font=('Microsoft YaHei', 10, 'bold')).grid(row=3, column=0, columnspan=2, pady=5)

        ttk.Label(frame, text="预约数量：").grid(row=4, column=0, sticky='e', padx=5, pady=15)
        qty_entry = ttk.Entry(frame, width=20)
        qty_entry.grid(row=4, column=1, padx=5, pady=15)
        qty_entry.focus()

        ttk.Label(frame, text="计划使用日期：").grid(row=5, column=0, sticky='e', padx=5, pady=5)
        from datetime import datetime, timedelta
        default_date = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
        date_entry = ttk.Entry(frame, width=20)
        date_entry.insert(0, default_date)
        date_entry.grid(row=5, column=1, padx=5, pady=5)
        ttk.Label(frame, text="(格式：YYYY-MM-DD)", foreground='gray').grid(row=6, column=1, sticky='w', padx=5)

        ttk.Label(frame, text="用途：").grid(row=7, column=0, sticky='e', padx=5, pady=5)
        remarks_entry = ttk.Entry(frame, width=30)
        remarks_entry.grid(row=7, column=1, padx=5, pady=5)

        def do_create():
            try:
                qty_str = qty_entry.get().strip()
                if not qty_str:
                    messagebox.showwarning("提示", "请输入预约数量")
                    return
                quantity = int(qty_str)
                planned_date = date_entry.get().strip()
                remarks = remarks_entry.get().strip()

                _, msg = self.manager.create_reservation(
                    reagent["id"], quantity, planned_date, remarks
                )
                messagebox.showinfo("成功", msg)
                self.refresh_inventory()
                dialog.destroy()
            except ValueError:
                messagebox.showerror("错误", "数量必须是整数")
            except OperationError as e:
                messagebox.showerror("错误", str(e))

        btn_frame = ttk.Frame(frame)
        btn_frame.grid(row=8, column=0, columnspan=2, pady=20)
        ttk.Button(btn_frame, text="提交预约", command=do_create, width=12).pack(side='left', padx=10)
        ttk.Button(btn_frame, text="取 消", command=dialog.destroy, width=12).pack(side='left', padx=10)

    def return_dialog(self):
        reagent = self.get_selected_reagent()
        if not reagent:
            return

        from database import ReagentDB
        if ReagentDB.is_expired(reagent["id"]):
            messagebox.showerror("错误", f"试剂已过期（过期日期：{reagent['expiration_date']}），请走报废流程")
            return

        dialog = tk.Toplevel(self.root)
        dialog.title("试剂归还")
        dialog.geometry("400x300")
        dialog.transient(self.root)
        dialog.grab_set()

        frame = ttk.Frame(dialog, padding=20)
        frame.pack(fill='both', expand=True)

        ttk.Label(frame, text=f"试剂：{reagent['name']} ({reagent['batch_number']})",
                  font=('Microsoft YaHei', 10, 'bold')).grid(row=0, column=0, columnspan=2, pady=10)
        ttk.Label(frame, text=f"当前库存：{reagent['quantity']} {reagent['unit']}").grid(row=1, column=0, columnspan=2, pady=5)

        ttk.Label(frame, text="归还数量：").grid(row=2, column=0, sticky='e', padx=5, pady=15)
        qty_entry = ttk.Entry(frame, width=20)
        qty_entry.grid(row=2, column=1, padx=5, pady=15)
        qty_entry.focus()

        ttk.Label(frame, text="备注：").grid(row=3, column=0, sticky='e', padx=5, pady=5)
        remarks_entry = ttk.Entry(frame, width=30)
        remarks_entry.grid(row=3, column=1, padx=5, pady=5)

        def do_return():
            try:
                qty_str = qty_entry.get().strip()
                if not qty_str:
                    messagebox.showwarning("提示", "请输入归还数量")
                    return
                quantity = int(qty_str)
                _, msg = self.manager.return_reagent(
                    reagent["id"], quantity, remarks_entry.get().strip()
                )
                messagebox.showinfo("成功", msg)
                self.refresh_inventory()
                dialog.destroy()
            except ValueError:
                messagebox.showerror("错误", "数量必须是整数")
            except OperationError as e:
                messagebox.showerror("错误", str(e))

        btn_frame = ttk.Frame(frame)
        btn_frame.grid(row=4, column=0, columnspan=2, pady=20)
        ttk.Button(btn_frame, text="确 定", command=do_return, width=12).pack(side='left', padx=10)
        ttk.Button(btn_frame, text="取 消", command=dialog.destroy, width=12).pack(side='left', padx=10)

    def scrap_dialog(self):
        reagent = self.get_selected_reagent()
        if not reagent:
            return

        dialog = tk.Toplevel(self.root)
        dialog.title("试剂报废")
        dialog.geometry("400x300")
        dialog.transient(self.root)
        dialog.grab_set()

        frame = ttk.Frame(dialog, padding=20)
        frame.pack(fill='both', expand=True)

        ttk.Label(frame, text=f"试剂：{reagent['name']} ({reagent['batch_number']})",
                  font=('Microsoft YaHei', 10, 'bold')).grid(row=0, column=0, columnspan=2, pady=10)
        ttk.Label(frame, text=f"当前库存：{reagent['quantity']} {reagent['unit']}", foreground='red').grid(row=1, column=0, columnspan=2, pady=5)

        ttk.Label(frame, text="报废数量：").grid(row=2, column=0, sticky='e', padx=5, pady=15)
        qty_entry = ttk.Entry(frame, width=20)
        qty_entry.grid(row=2, column=1, padx=5, pady=15)
        qty_entry.focus()

        ttk.Label(frame, text="报废原因：").grid(row=3, column=0, sticky='e', padx=5, pady=5)
        remarks_entry = ttk.Entry(frame, width=30)
        remarks_entry.grid(row=3, column=1, padx=5, pady=5)

        def do_scrap():
            try:
                qty_str = qty_entry.get().strip()
                if not qty_str:
                    messagebox.showwarning("提示", "请输入报废数量")
                    return
                quantity = int(qty_str)

                if not messagebox.askyesno("确认", f"确定要报废 {quantity} {reagent['unit']} {reagent['name']} 吗？此操作不可恢复。"):
                    return

                _, msg = self.manager.scrap(
                    reagent["id"], quantity, remarks_entry.get().strip()
                )
                messagebox.showinfo("成功", msg)
                self.refresh_inventory()
                dialog.destroy()
            except ValueError:
                messagebox.showerror("错误", "数量必须是整数")
            except OperationError as e:
                messagebox.showerror("错误", str(e))

        btn_frame = ttk.Frame(frame)
        btn_frame.grid(row=4, column=0, columnspan=2, pady=20)
        ttk.Button(btn_frame, text="确定报废", command=do_scrap, width=12).pack(side='left', padx=10)
        ttk.Button(btn_frame, text="取 消", command=dialog.destroy, width=12).pack(side='left', padx=10)

    def stocktake_dialog(self):
        reagent = self.get_selected_reagent()
        if not reagent:
            return

        dialog = tk.Toplevel(self.root)
        dialog.title("库存盘点")
        dialog.geometry("450x350")
        dialog.transient(self.root)
        dialog.grab_set()

        frame = ttk.Frame(dialog, padding=20)
        frame.pack(fill='both', expand=True)

        ttk.Label(frame, text=f"试剂：{reagent['name']} ({reagent['batch_number']})",
                  font=('Microsoft YaHei', 10, 'bold')).grid(row=0, column=0, columnspan=2, pady=10)
        ttk.Label(frame, text=f"系统库存：{reagent['quantity']} {reagent['unit']}").grid(row=1, column=0, columnspan=2, pady=5)

        ttk.Label(frame, text="实际盘点数量：").grid(row=2, column=0, sticky='e', padx=5, pady=15)
        qty_entry = ttk.Entry(frame, width=20)
        qty_entry.grid(row=2, column=1, padx=5, pady=15)
        qty_entry.insert(0, str(reagent["quantity"]))
        qty_entry.focus()
        qty_entry.select_range(0, 'end')

        self.diff_label = ttk.Label(frame, text="差异：0", foreground='gray')
        self.diff_label.grid(row=3, column=0, columnspan=2, pady=5)

        def update_diff(*args):
            try:
                actual = int(qty_entry.get().strip())
                diff = actual - reagent["quantity"]
                if diff > 0:
                    self.diff_label.configure(text=f"差异：+{diff}", foreground='green')
                elif diff < 0:
                    self.diff_label.configure(text=f"差异：{diff}", foreground='red')
                else:
                    self.diff_label.configure(text=f"差异：{diff}", foreground='gray')
            except ValueError:
                self.diff_label.configure(text="差异：-", foreground='gray')

        qty_entry.bind('<KeyRelease>', update_diff)

        ttk.Label(frame, text="备注：").grid(row=4, column=0, sticky='e', padx=5, pady=5)
        remarks_entry = ttk.Entry(frame, width=30)
        remarks_entry.grid(row=4, column=1, padx=5, pady=5)

        def do_stocktake():
            try:
                qty_str = qty_entry.get().strip()
                if not qty_str:
                    messagebox.showwarning("提示", "请输入实际数量")
                    return
                actual_quantity = int(qty_str)
                _, msg = self.manager.stocktake(
                    reagent["id"], actual_quantity, remarks_entry.get().strip()
                )
                messagebox.showinfo("成功", msg)
                self.refresh_inventory()
                dialog.destroy()
            except ValueError:
                messagebox.showerror("错误", "数量必须是整数")
            except OperationError as e:
                messagebox.showerror("错误", str(e))

        btn_frame = ttk.Frame(frame)
        btn_frame.grid(row=5, column=0, columnspan=2, pady=20)
        ttk.Button(btn_frame, text="确认调整", command=do_stocktake, width=12).pack(side='left', padx=10)
        ttk.Button(btn_frame, text="取 消", command=dialog.destroy, width=12).pack(side='left', padx=10)

    def setup_reservation_tab(self):
        frame = self.tab_reservation

        if not self.auth.has_permission("view_reservations"):
            ttk.Label(frame, text="当前角色无预约查看权限", font=('Microsoft YaHei', 14), foreground='gray').pack(pady=50)
            return

        filter_frame = ttk.LabelFrame(frame, text="筛选条件", padding=10)
        filter_frame.pack(fill='x', pady=10, padx=10)

        ttk.Label(filter_frame, text="试剂名称：").grid(row=0, column=0, padx=5, pady=5)
        self.res_filter_name = ttk.Entry(filter_frame, width=15)
        self.res_filter_name.grid(row=0, column=1, padx=5, pady=5)

        ttk.Label(filter_frame, text="批号：").grid(row=0, column=2, padx=5, pady=5)
        self.res_filter_batch = ttk.Entry(filter_frame, width=15)
        self.res_filter_batch.grid(row=0, column=3, padx=5, pady=5)

        ttk.Label(filter_frame, text="状态：").grid(row=0, column=4, padx=5, pady=5)
        res_statuses = ["全部", "待审核", "已审批", "已拒绝", "已取消", "已领用", "已过期", "已改期"]
        self.res_filter_status = ttk.Combobox(filter_frame, values=res_statuses, state='readonly', width=10)
        self.res_filter_status.grid(row=0, column=5, padx=5, pady=5)
        self.res_filter_status.current(0)

        ttk.Label(filter_frame, text="计划日期从：").grid(row=1, column=0, padx=5, pady=5)
        self.res_filter_date_start = ttk.Entry(filter_frame, width=15)
        self.res_filter_date_start.grid(row=1, column=1, padx=5, pady=5)

        ttk.Label(filter_frame, text="到：").grid(row=1, column=2, padx=5, pady=5)
        self.res_filter_date_end = ttk.Entry(filter_frame, width=15)
        self.res_filter_date_end.grid(row=1, column=3, padx=5, pady=5)

        ttk.Button(filter_frame, text="查询", command=self.refresh_reservations).grid(row=0, column=6, padx=10, pady=5, rowspan=2)
        ttk.Button(filter_frame, text="重置", command=self.reset_reservation_filters).grid(row=0, column=7, padx=5, pady=5, rowspan=2)

        btn_frame = ttk.Frame(frame)
        btn_frame.pack(fill='x', padx=10, pady=5)

        if self.auth.has_permission("create_reservation"):
            ttk.Button(btn_frame, text="新建预约", command=self.create_reservation_dialog).pack(side='left', padx=5)
        if self.auth.has_permission("cancel_reservation"):
            ttk.Button(btn_frame, text="取消预约", command=self.cancel_selected_reservation).pack(side='left', padx=5)
        if self.auth.has_permission("complete_reservation"):
            ttk.Button(btn_frame, text="确认领用", command=self.complete_selected_reservation).pack(side='left', padx=5)
        if self.auth.has_permission("reschedule_reservation"):
            ttk.Button(btn_frame, text="改期", command=self.reschedule_selected_reservation).pack(side='left', padx=5)
        if self.auth.has_permission("release_expired_reservations"):
            ttk.Button(btn_frame, text="释放过期预约", command=self.release_expired_reservations).pack(side='left', padx=5)

        tree_frame = ttk.Frame(frame)
        tree_frame.pack(fill='both', expand=True, padx=10, pady=10)

        columns = ("id", "reagent", "batch", "qty", "unit", "planned_date", "status",
                  "operator", "reviewer", "created_at", "remarks")
        self.reservation_tree = ttk.Treeview(tree_frame, columns=columns, show='headings')

        headings = [
            ("id", "预约ID", 70),
            ("reagent", "试剂名称", 130),
            ("batch", "批号", 110),
            ("qty", "数量", 70),
            ("unit", "单位", 50),
            ("planned_date", "计划使用日期", 100),
            ("status", "状态", 80),
            ("operator", "申请人", 90),
            ("reviewer", "审核人", 90),
            ("created_at", "创建时间", 140),
            ("remarks", "备注", 180)
        ]

        for col, text, width in headings:
            self.reservation_tree.heading(col, text=text)
            self.reservation_tree.column(col, width=width, anchor='center')

        scrollbar = ttk.Scrollbar(tree_frame, orient='vertical', command=self.reservation_tree.yview)
        self.reservation_tree.configure(yscrollcommand=scrollbar.set)

        self.reservation_tree.pack(side='left', fill='both', expand=True)
        scrollbar.pack(side='right', fill='y')

        self.reservation_tree.bind('<<TreeviewSelect>>', self.on_reservation_select)
        self.reservation_tree.bind('<Double-1>', self.show_reservation_detail)

        self.refresh_reservations()

    def reset_reservation_filters(self):
        self.res_filter_name.delete(0, 'end')
        self.res_filter_batch.delete(0, 'end')
        self.res_filter_status.current(0)
        self.res_filter_date_start.delete(0, 'end')
        self.res_filter_date_end.delete(0, 'end')
        self.refresh_reservations()

    def get_reservation_filters(self):
        filters = {}
        name = self.res_filter_name.get().strip()
        if name:
            filters["reagent_name"] = name
        batch = self.res_filter_batch.get().strip()
        if batch:
            filters["batch_number"] = batch

        status_map = {
            "待审核": "pending",
            "已审批": "approved",
            "已拒绝": "rejected",
            "已取消": "cancelled",
            "已领用": "completed",
            "已过期": "expired",
            "已改期": "rescheduled"
        }
        status_val = self.res_filter_status.get()
        if status_val in status_map:
            filters["status"] = status_map[status_val]

        date_start = self.res_filter_date_start.get().strip()
        if date_start:
            filters["planned_start_date"] = date_start
        date_end = self.res_filter_date_end.get().strip()
        if date_end:
            filters["planned_end_date"] = date_end

        return filters

    def refresh_reservations(self):
        for item in self.reservation_tree.get_children():
            self.reservation_tree.delete(item)

        try:
            filters = self.get_reservation_filters()
            reservations = self.manager.get_reservations(filters)

            for r in reservations:
                status_display = RESERVATION_STATUS_DISPLAY.get(r["status"], r["status"])

                tags = ()
                if r["status"] == "approved":
                    tags = ('approved',)
                elif r["status"] == "rejected":
                    tags = ('rejected',)
                elif r["status"] == "cancelled":
                    tags = ('cancelled',)
                elif r["status"] == "completed":
                    tags = ('completed',)
                elif r["status"] == "expired":
                    tags = ('expired',)
                elif r["status"] == "pending":
                    tags = ('pending',)

                self.reservation_tree.insert('', 'end', iid=str(r["id"]), values=(
                    r["id"], r["reagent_name"], r["batch_number"], r["quantity"],
                    r.get("unit", ""), r["planned_use_date"], status_display,
                    r.get("operator_name", ""), r.get("reviewer_name", "") or "-",
                    r["created_at"], r.get("remarks", "") or ""
                ), tags=tags)

            self.reservation_tree.tag_configure('pending', background='#fff3cd')
            self.reservation_tree.tag_configure('approved', background='#d4edda')
            self.reservation_tree.tag_configure('rejected', background='#f8d7da')
            self.reservation_tree.tag_configure('cancelled', background='#e2e3e5')
            self.reservation_tree.tag_configure('completed', background='#d1ecf1')
            self.reservation_tree.tag_configure('expired', background='#f5c6cb')

            self.set_status(f"查询到 {len(reservations)} 条预约记录")
        except OperationError as e:
            messagebox.showerror("错误", str(e))

    def on_reservation_select(self, event):
        selection = self.reservation_tree.selection()
        if selection:
            self.selected_reservation_id = int(selection[0])

    def show_reservation_detail(self, event):
        selection = self.reservation_tree.selection()
        if not selection:
            return

        reservation = self.manager.get_reservation_by_id(int(selection[0]))
        if not reservation:
            return

        detail_window = tk.Toplevel(self.root)
        detail_window.title(f"预约详情 - #{reservation['id']}")
        detail_window.geometry("550x550")
        detail_window.transient(self.root)

        frame = ttk.Frame(detail_window, padding=20)
        frame.pack(fill='both', expand=True)

        status_display = RESERVATION_STATUS_DISPLAY.get(reservation["status"], reservation["status"])

        info = [
            ("预约ID", f"#{reservation['id']}"),
            ("试剂名称", reservation["reagent_name"]),
            ("批号", reservation["batch_number"]),
            ("预约数量", f"{reservation['quantity']} {reservation.get('unit', '')}"),
            ("当前总库存", f"{reservation.get('current_stock', 0)} {reservation.get('unit', '')}"),
            ("已锁定库存", f"{reservation.get('current_locked', 0)} {reservation.get('unit', '')}"),
            ("计划使用日期", reservation["planned_use_date"]),
            ("原计划日期", reservation.get("original_planned_date", "-") or "-"),
            ("状态", status_display),
            ("申请人", reservation.get("operator_name", "-") or "-"),
            ("审核人", reservation.get("reviewer_name", "-") or "-"),
            ("申请备注", reservation.get("remarks", "-") or "-"),
            ("审核备注", reservation.get("review_remarks", "-") or "-"),
            ("创建时间", reservation["created_at"]),
            ("更新时间", reservation["updated_at"])
        ]

        for i, (label, value) in enumerate(info):
            ttk.Label(frame, text=f"{label}：", font=('Microsoft YaHei', 10, 'bold')).grid(row=i, column=0, sticky='e', padx=5, pady=5)
            ttk.Label(frame, text=value, font=('Microsoft YaHei', 10)).grid(row=i, column=1, sticky='w', padx=5, pady=5)

        btn_frame = ttk.Frame(frame)
        btn_frame.grid(row=len(info), column=0, columnspan=2, pady=15)

        if reservation["status"] == "approved" and self.auth.has_permission("complete_reservation"):
            ttk.Button(btn_frame, text="确认领用",
                      command=lambda: (detail_window.destroy(), self.complete_selected_reservation())
                      ).pack(side='left', padx=5)
        if reservation["status"] in ["pending", "approved"] and self.auth.has_permission("cancel_reservation"):
            ttk.Button(btn_frame, text="取消预约",
                      command=lambda: (detail_window.destroy(), self.cancel_selected_reservation())
                      ).pack(side='left', padx=5)
        if reservation["status"] in ["pending", "approved"] and self.auth.has_permission("reschedule_reservation"):
            ttk.Button(btn_frame, text="改期",
                      command=lambda: (detail_window.destroy(), self.reschedule_selected_reservation())
                      ).pack(side='left', padx=5)

    def cancel_selected_reservation(self):
        if not self.selected_reservation_id:
            messagebox.showwarning("提示", "请先选择要取消的预约")
            return

        remarks = simpledialog.askstring("取消原因", "请输入取消原因（可选）：", parent=self.root)
        if remarks is None:
            return

        try:
            _, msg = self.manager.cancel_reservation(
                self.selected_reservation_id, remarks or ""
            )
            messagebox.showinfo("成功", msg)
            self.selected_reservation_id = None
            self.refresh_reservations()
            self.refresh_inventory()
        except OperationError as e:
            messagebox.showerror("错误", str(e))

    def complete_selected_reservation(self):
        if not self.selected_reservation_id:
            messagebox.showwarning("提示", "请先选择要领用的预约")
            return

        reservation = self.manager.get_reservation_by_id(self.selected_reservation_id)
        if not reservation:
            return

        if not messagebox.askyesno("确认",
            f"确认领用 {reservation['quantity']} {reservation.get('unit', '')} "
            f"{reservation['reagent_name']} ({reservation['batch_number']})？\n"
            f"此操作将扣减库存。"):
            return

        remarks = simpledialog.askstring("领用备注", "请输入领用备注（可选）：", parent=self.root)
        if remarks is None:
            return

        try:
            _, msg = self.manager.complete_reservation(
                self.selected_reservation_id, remarks or ""
            )
            messagebox.showinfo("成功", msg)
            self.selected_reservation_id = None
            self.refresh_reservations()
            self.refresh_inventory()
        except OperationError as e:
            messagebox.showerror("错误", str(e))

    def reschedule_selected_reservation(self):
        if not self.selected_reservation_id:
            messagebox.showwarning("提示", "请先选择要改期的预约")
            return

        reservation = self.manager.get_reservation_by_id(self.selected_reservation_id)
        if not reservation:
            return

        dialog = tk.Toplevel(self.root)
        dialog.title("预约改期")
        dialog.geometry("400x250")
        dialog.transient(self.root)
        dialog.grab_set()

        frame = ttk.Frame(dialog, padding=20)
        frame.pack(fill='both', expand=True)

        ttk.Label(frame, text=f"预约：{reservation['reagent_name']} ({reservation['batch_number']})",
                  font=('Microsoft YaHei', 10, 'bold')).grid(row=0, column=0, columnspan=2, pady=10)
        ttk.Label(frame, text=f"原计划日期：{reservation['planned_use_date']}").grid(row=1, column=0, columnspan=2, pady=5)

        ttk.Label(frame, text="新计划日期：").grid(row=2, column=0, sticky='e', padx=5, pady=15)
        from datetime import datetime, timedelta
        default_date = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
        date_entry = ttk.Entry(frame, width=20)
        date_entry.insert(0, default_date)
        date_entry.grid(row=2, column=1, padx=5, pady=15)

        ttk.Label(frame, text="改期原因：").grid(row=3, column=0, sticky='e', padx=5, pady=5)
        remarks_entry = ttk.Entry(frame, width=30)
        remarks_entry.grid(row=3, column=1, padx=5, pady=5)

        def do_reschedule():
            try:
                new_date = date_entry.get().strip()
                remarks = remarks_entry.get().strip()
                _, msg = self.manager.reschedule_reservation(
                    self.selected_reservation_id, new_date, remarks
                )
                messagebox.showinfo("成功", msg)
                self.selected_reservation_id = None
                self.refresh_reservations()
                self.refresh_inventory()
                dialog.destroy()
            except OperationError as e:
                messagebox.showerror("错误", str(e))

        btn_frame = ttk.Frame(frame)
        btn_frame.grid(row=4, column=0, columnspan=2, pady=15)
        ttk.Button(btn_frame, text="确 定", command=do_reschedule, width=12).pack(side='left', padx=10)
        ttk.Button(btn_frame, text="取 消", command=dialog.destroy, width=12).pack(side='left', padx=10)

    def release_expired_reservations(self):
        if not messagebox.askyesno("确认", "确定要释放所有过期的预约吗？"):
            return

        try:
            count, messages = self.manager.release_expired_reservations()
            if count > 0:
                msg = f"已释放 {count} 个过期预约：\n" + "\n".join(messages[:10])
                if len(messages) > 10:
                    msg += f"\n... 共 {len(messages)} 条处理结果"
                messagebox.showinfo("完成", msg)
            else:
                messagebox.showinfo("完成", "没有过期的预约需要释放")
            self.refresh_reservations()
            self.refresh_inventory()
        except OperationError as e:
            messagebox.showerror("错误", str(e))

    def setup_approval_tab(self):
        frame = self.tab_approval

        if not self.auth.has_permission("approve_reservation"):
            ttk.Label(frame, text="当前角色无预约审核权限", font=('Microsoft YaHei', 14), foreground='gray').pack(pady=50)
            return

        btn_frame = ttk.Frame(frame)
        btn_frame.pack(fill='x', padx=10, pady=10)

        ttk.Button(btn_frame, text="刷新", command=self.refresh_reservation_approvals).pack(side='left', padx=5)
        ttk.Button(btn_frame, text="批准", command=self.approve_selected_reservation).pack(side='left', padx=5)
        ttk.Button(btn_frame, text="拒绝", command=self.reject_selected_reservation).pack(side='left', padx=5)
        ttk.Button(btn_frame, text="改期", command=self.reschedule_selected_reservation).pack(side='left', padx=5)

        tree_frame = ttk.Frame(frame)
        tree_frame.pack(fill='both', expand=True, padx=10, pady=10)

        columns = ("id", "reagent", "batch", "apply_qty", "available_qty", "unit",
                  "planned_date", "operator", "time", "remarks")
        self.res_approval_tree = ttk.Treeview(tree_frame, columns=columns, show='headings')

        headings = [
            ("id", "预约ID", 70),
            ("reagent", "试剂名称", 150),
            ("batch", "批号", 120),
            ("apply_qty", "预约数量", 80),
            ("available_qty", "可用库存", 80),
            ("unit", "单位", 60),
            ("planned_date", "计划使用日期", 100),
            ("operator", "申请人", 100),
            ("time", "申请时间", 150),
            ("remarks", "备注", 150)
        ]

        for col, text, width in headings:
            self.res_approval_tree.heading(col, text=text)
            self.res_approval_tree.column(col, width=width, anchor='center')

        scrollbar = ttk.Scrollbar(tree_frame, orient='vertical', command=self.res_approval_tree.yview)
        self.res_approval_tree.configure(yscrollcommand=scrollbar.set)

        self.res_approval_tree.pack(side='left', fill='both', expand=True)
        scrollbar.pack(side='right', fill='y')

        self.res_approval_tree.bind('<<TreeviewSelect>>', self.on_reservation_approval_select)

        self.refresh_reservation_approvals()

    def on_reservation_approval_select(self, event):
        selection = self.res_approval_tree.selection()
        if selection:
            self.selected_reservation_id = int(selection[0])

    def refresh_reservation_approvals(self):
        if not self.auth.has_permission("approve_reservation"):
            return

        for item in self.res_approval_tree.get_children():
            self.res_approval_tree.delete(item)

        try:
            from database import ReagentLockDB
            approvals = self.manager.get_pending_reservations()
            for a in approvals:
                available = ReagentLockDB.get_available_quantity(a["reagent_id"])
                self.res_approval_tree.insert('', 'end', iid=str(a["id"]), values=(
                    a["id"], a["reagent_name"], a["batch_number"],
                    a["quantity"], available, a.get("unit", ""),
                    a["planned_use_date"], a.get("operator_name", ""),
                    a["created_at"], a.get("remarks", "") or ""
                ))
            self.set_status(f"待审核预约：{len(approvals)} 条")
        except OperationError as e:
            messagebox.showerror("错误", str(e))

    def approve_selected_reservation(self):
        if not self.selected_reservation_id:
            messagebox.showwarning("提示", "请先选择要审核的预约")
            return

        remarks = simpledialog.askstring("审核备注", "请输入审核备注（可选）：", parent=self.root)
        if remarks is None:
            return

        try:
            _, msg = self.manager.approve_reservation(
                self.selected_reservation_id, remarks or ""
            )
            messagebox.showinfo("成功", msg)
            self.selected_reservation_id = None
            self.refresh_reservation_approvals()
            self.refresh_reservations()
            self.refresh_inventory()
        except OperationError as e:
            messagebox.showerror("错误", str(e))

    def reject_selected_reservation(self):
        if not self.selected_reservation_id:
            messagebox.showwarning("提示", "请先选择要拒绝的预约")
            return

        remarks = simpledialog.askstring("拒绝原因", "请输入拒绝原因：", parent=self.root)
        if remarks is None:
            return
        if not remarks or not remarks.strip():
            messagebox.showwarning("提示", "请输入拒绝原因")
            return

        try:
            _, msg = self.manager.reject_reservation(
                self.selected_reservation_id, remarks.strip()
            )
            messagebox.showinfo("成功", msg)
            self.selected_reservation_id = None
            self.refresh_reservation_approvals()
            self.refresh_reservations()
        except OperationError as e:
            messagebox.showerror("错误", str(e))

    def on_approval_select(self, event):
        selection = self.approval_tree.selection()
        if selection:
            self.selected_approval_id = int(selection[0])

    def refresh_approvals(self):
        if not self.auth.has_permission("approve_use"):
            return

        for item in self.approval_tree.get_children():
            self.approval_tree.delete(item)

        try:
            approvals = self.manager.get_pending_approvals()
            for a in approvals:
                self.approval_tree.insert('', 'end', iid=str(a["id"]), values=(
                    a["id"], a["reagent_name"], a["batch_number"],
                    a["quantity"], a["current_quantity"], a.get("unit", ""),
                    a["operator_name"], a["operation_time"], a["remarks"] or ""
                ))
            self.set_status(f"待审核申请：{len(approvals)} 条")
        except OperationError as e:
            messagebox.showerror("错误", str(e))

    def approve_selected(self):
        if not self.selected_approval_id:
            messagebox.showwarning("提示", "请先选择要审核的申请")
            return

        remarks = simpledialog.askstring("审核备注", "请输入审核备注（可选）：", parent=self.root)
        if remarks is None:
            return

        try:
            _, msg = self.manager.approve_use(self.selected_approval_id, remarks or "")
            messagebox.showinfo("成功", msg)
            self.selected_approval_id = None
            self.refresh_approvals()
            self.refresh_inventory()
        except OperationError as e:
            messagebox.showerror("错误", str(e))

    def reject_selected(self):
        if not self.selected_approval_id:
            messagebox.showwarning("提示", "请先选择要拒绝的申请")
            return

        remarks = simpledialog.askstring("拒绝原因", "请输入拒绝原因：", parent=self.root)
        if remarks is None:
            return
        if not remarks or not remarks.strip():
            messagebox.showwarning("提示", "请输入拒绝原因")
            return

        try:
            _, msg = self.manager.reject_use(self.selected_approval_id, remarks.strip())
            messagebox.showinfo("成功", msg)
            self.selected_approval_id = None
            self.refresh_approvals()
        except OperationError as e:
            messagebox.showerror("错误", str(e))

    def setup_operations_tab(self):
        frame = self.tab_operations

        main_frame = ttk.Frame(frame, padding=20)
        main_frame.pack(fill='both', expand=True)

        ttk.Label(main_frame, text="快捷操作", font=('Microsoft YaHei', 14, 'bold')).pack(pady=(0, 20))

        ops_frame = ttk.Frame(main_frame)
        ops_frame.pack()

        operations = []
        if self.auth.has_permission("stock_in"):
            operations.append(("入库", "stock_in", self.stock_in_dialog))
        if self.auth.has_permission("apply_use"):
            operations.append(("申请领用", "apply_use", self.apply_use_dialog))
        if self.auth.has_permission("return_reagent"):
            operations.append(("归还", "return", self.return_dialog))
        if self.auth.has_permission("scrap"):
            operations.append(("报废", "scrap", self.scrap_dialog))
        if self.auth.has_permission("stocktake"):
            operations.append(("盘点", "stocktake", self.stocktake_dialog))
        if self.auth.has_permission("manage_reagents"):
            operations.append(("新增试剂", "add_reagent", self.add_reagent_dialog))

        for i, (text, key, cmd) in enumerate(operations):
            btn = ttk.Button(ops_frame, text=text, command=cmd, width=15)
            btn.grid(row=i // 3, column=i % 3, padx=15, pady=15, ipadx=10, ipady=10)

        ttk.Separator(main_frame, orient='horizontal').pack(fill='x', pady=30)

        if self.auth.has_permission("revert_operation"):
            revert_frame = ttk.LabelFrame(main_frame, text="撤销操作", padding=15)
            revert_frame.pack(fill='x')

            ttk.Label(revert_frame,
                      text="此操作将撤销最近一次可撤销的合规动作（入库、审核领用、归还、报废、盘点、预约审批、取消预约、实际领用）",
                      wraplength=800).pack(pady=5)

            self.last_op_var = tk.StringVar(value="检查中...")
            ttk.Label(revert_frame, textvariable=self.last_op_var, foreground='#1976D2').pack(pady=5)

            def check_revertable():
                try:
                    from database import OperationDB
                    last_op = OperationDB.get_last_revertable()
                    last_res_log = self.manager.get_last_revertable_reservation_log()

                    last = None
                    is_reservation = False

                    if last_op and last_res_log:
                        op_time = last_op.get("operation_time", "")
                        log_time = last_res_log.get("operation_time", "")
                        if log_time >= op_time:
                            last = last_res_log
                            is_reservation = True
                        else:
                            last = last_op
                    elif last_res_log:
                        last = last_res_log
                        is_reservation = True
                    elif last_op:
                        last = last_op

                    if last:
                        if is_reservation:
                            op_type = RESERVATION_OPERATION_DISPLAY.get(last["operation_type"], last["operation_type"])
                            reagent = last.get("reagent_name", "")
                            batch = last.get("batch_number", "")
                            self.last_op_var.set(
                                f"最近可撤销操作：#{last['id']} - {op_type} - {reagent} ({batch}) 数量：{last['quantity']}"
                            )
                        else:
                            op_type = OPERATION_TYPE_DISPLAY.get(last["operation_type"], last["operation_type"])
                            reagent = last.get("reagent_name", "")
                            batch = last.get("batch_number", "")
                            self.last_op_var.set(
                                f"最近可撤销操作：#{last['id']} - {op_type} - {reagent} ({batch}) 数量：{last['quantity']}"
                            )
                    else:
                        self.last_op_var.set("没有可撤销的操作")
                except Exception as e:
                    self.last_op_var.set(f"检查失败：{str(e)}")

            def do_revert():
                if not messagebox.askyesno("确认", "确定要撤销最近一次操作吗？"):
                    return
                try:
                    from database import OperationDB
                    last_op = OperationDB.get_last_revertable()
                    last_res_log = self.manager.get_last_revertable_reservation_log()

                    use_reservation_revert = False
                    if last_op and last_res_log:
                        op_time = last_op.get("operation_time", "")
                        log_time = last_res_log.get("operation_time", "")
                        if log_time >= op_time:
                            use_reservation_revert = True
                    elif last_res_log:
                        use_reservation_revert = True

                    if use_reservation_revert:
                        _, msg = self.manager.revert_last_reservation_operation()
                    else:
                        _, msg = self.manager.revert_last_operation()

                    messagebox.showinfo("成功", msg)
                    check_revertable()
                    self.refresh_inventory()
                    self.refresh_reservations()
                except OperationError as e:
                    messagebox.showerror("错误", str(e))
                    check_revertable()

            btn_row = ttk.Frame(revert_frame)
            btn_row.pack(pady=10)
            ttk.Button(btn_row, text="刷新状态", command=check_revertable).pack(side='left', padx=10)
            ttk.Button(btn_row, text="撤销最近操作", command=do_revert).pack(side='left', padx=10)

            check_revertable()

    def setup_history_tab(self):
        frame = self.tab_history

        tree_frame = ttk.Frame(frame)
        tree_frame.pack(fill='both', expand=True, padx=10, pady=10)

        columns = ("id", "type", "reagent", "batch", "qty", "operator", "reviewer", "status", "time", "remarks")
        self.history_tree = ttk.Treeview(tree_frame, columns=columns, show='headings')

        headings = [
            ("id", "ID", 60),
            ("type", "操作类型", 100),
            ("reagent", "试剂名称", 150),
            ("batch", "批号", 120),
            ("qty", "数量", 80),
            ("operator", "操作人", 100),
            ("reviewer", "审核人", 100),
            ("status", "状态", 80),
            ("time", "操作时间", 150),
            ("remarks", "备注", 200)
        ]

        for col, text, width in headings:
            self.history_tree.heading(col, text=text)
            self.history_tree.column(col, width=width, anchor='center')

        scrollbar = ttk.Scrollbar(tree_frame, orient='vertical', command=self.history_tree.yview)
        self.history_tree.configure(yscrollcommand=scrollbar.set)

        self.history_tree.pack(side='left', fill='both', expand=True)
        scrollbar.pack(side='right', fill='y')

        btn_frame = ttk.Frame(frame)
        btn_frame.pack(fill='x', padx=10, pady=5)
        ttk.Button(btn_frame, text="刷新", command=self.refresh_history).pack(side='left', padx=5)

        self.refresh_history()

    def refresh_history(self):
        for item in self.history_tree.get_children():
            self.history_tree.delete(item)

        try:
            history = self.manager.get_operation_history(200)
            for h in history:
                op_type = OPERATION_TYPE_DISPLAY.get(h["operation_type"], h["operation_type"])
                status = STATUS_DISPLAY.get(h["status"], h["status"])

                tags = ()
                if h["status"] == "reverted":
                    tags = ('reverted',)
                elif h["status"] == "rejected":
                    tags = ('rejected',)

                self.history_tree.insert('', 'end', values=(
                    h["id"], op_type, h.get("reagent_name", "-") or "-",
                    h.get("batch_number", "-") or "-", h["quantity"] if h["quantity"] is not None else "-",
                    h.get("operator_name", "-") or "-", h.get("reviewer_name", "-") or "-",
                    status, h["operation_time"], h["remarks"] or ""
                ), tags=tags)

            self.history_tree.tag_configure('reverted', background='#e0e0e0', foreground='gray')
            self.history_tree.tag_configure('rejected', background='#ffebee')

            self.set_status(f"操作历史：{len(history)} 条记录")
        except OperationError as e:
            messagebox.showerror("错误", str(e))

    def setup_reservation_logs_tab(self):
        frame = self.tab_reservation_logs

        if not self.auth.has_permission("view_reservation_logs"):
            ttk.Label(frame, text="当前角色无预约日志查看权限", font=('Microsoft YaHei', 14), foreground='gray').pack(pady=50)
            return

        filter_frame = ttk.LabelFrame(frame, text="筛选条件", padding=10)
        filter_frame.pack(fill='x', pady=10, padx=10)

        ttk.Label(filter_frame, text="试剂名称：").grid(row=0, column=0, padx=5, pady=5)
        self.res_log_name = ttk.Entry(filter_frame, width=15)
        self.res_log_name.grid(row=0, column=1, padx=5, pady=5)

        ttk.Label(filter_frame, text="批号：").grid(row=0, column=2, padx=5, pady=5)
        self.res_log_batch = ttk.Entry(filter_frame, width=15)
        self.res_log_batch.grid(row=0, column=3, padx=5, pady=5)

        ttk.Label(filter_frame, text="操作类型：").grid(row=0, column=4, padx=5, pady=5)
        log_types = ["全部", "创建预约", "审批通过", "拒绝预约", "取消预约",
                     "实际领用", "过期释放", "改期", "撤销操作"]
        self.res_log_type = ttk.Combobox(filter_frame, values=log_types, state='readonly', width=12)
        self.res_log_type.grid(row=0, column=5, padx=5, pady=5)
        self.res_log_type.current(0)

        ttk.Label(filter_frame, text="操作人：").grid(row=1, column=0, padx=5, pady=5)
        self.res_log_operator = ttk.Entry(filter_frame, width=15)
        self.res_log_operator.grid(row=1, column=1, padx=5, pady=5)

        ttk.Label(filter_frame, text="开始日期：").grid(row=1, column=2, padx=5, pady=5)
        self.res_log_start = ttk.Entry(filter_frame, width=15)
        self.res_log_start.grid(row=1, column=3, padx=5, pady=5)

        ttk.Label(filter_frame, text="结束日期：").grid(row=1, column=4, padx=5, pady=5)
        self.res_log_end = ttk.Entry(filter_frame, width=15)
        self.res_log_end.grid(row=1, column=5, padx=5, pady=5)

        ttk.Button(filter_frame, text="查询", command=self.refresh_reservation_logs).grid(row=0, column=6, padx=10, pady=5, rowspan=2)
        ttk.Button(filter_frame, text="重置", command=self.reset_reservation_log_filters).grid(row=0, column=7, padx=5, pady=5, rowspan=2)

        btn_frame = ttk.Frame(frame)
        btn_frame.pack(fill='x', padx=10, pady=5)
        ttk.Button(btn_frame, text="刷新", command=self.refresh_reservation_logs).pack(side='left', padx=5)
        if self.auth.has_permission("view_reservation_logs"):
            ttk.Button(btn_frame, text="导出当前日志 CSV",
                      command=self.export_reservation_logs_dialog).pack(side='left', padx=5)

        tree_frame = ttk.Frame(frame)
        tree_frame.pack(fill='both', expand=True, padx=10, pady=10)

        columns = ("id", "reservation_id", "op_type", "reagent", "batch", "qty",
                  "status_before", "status_after", "locked_change", "stock_change",
                  "operator", "reviewer", "time", "remarks")
        self.res_log_tree = ttk.Treeview(tree_frame, columns=columns, show='headings')

        headings = [
            ("id", "日志ID", 70),
            ("reservation_id", "预约ID", 70),
            ("op_type", "操作类型", 90),
            ("reagent", "试剂名称", 130),
            ("batch", "批号", 110),
            ("qty", "数量", 70),
            ("status_before", "变更前状态", 80),
            ("status_after", "变更后状态", 80),
            ("locked_change", "锁定变动", 80),
            ("stock_change", "库存变动", 80),
            ("operator", "操作人", 90),
            ("reviewer", "审核人", 90),
            ("time", "操作时间", 150),
            ("remarks", "备注", 180)
        ]

        for col, text, width in headings:
            self.res_log_tree.heading(col, text=text)
            self.res_log_tree.column(col, width=width, anchor='center')

        scrollbar = ttk.Scrollbar(tree_frame, orient='vertical', command=self.res_log_tree.yview)
        self.res_log_tree.configure(yscrollcommand=scrollbar.set)

        self.res_log_tree.pack(side='left', fill='both', expand=True)
        scrollbar.pack(side='right', fill='y')

        self.refresh_reservation_logs()

    def reset_reservation_log_filters(self):
        self.res_log_name.delete(0, 'end')
        self.res_log_batch.delete(0, 'end')
        self.res_log_type.current(0)
        self.res_log_operator.delete(0, 'end')
        self.res_log_start.delete(0, 'end')
        self.res_log_end.delete(0, 'end')
        self.refresh_reservation_logs()

    def get_reservation_log_filters(self):
        filters = {}
        name = self.res_log_name.get().strip()
        if name:
            filters["reagent_name"] = name
        batch = self.res_log_batch.get().strip()
        if batch:
            filters["batch_number"] = batch

        type_map = {
            "创建预约": "create",
            "审批通过": "approve",
            "拒绝预约": "reject",
            "取消预约": "cancel",
            "实际领用": "complete",
            "过期释放": "expire_release",
            "改期": "reschedule",
            "撤销操作": "revert"
        }
        type_val = self.res_log_type.get()
        if type_val in type_map:
            filters["operation_type"] = type_map[type_val]

        operator = self.res_log_operator.get().strip()
        if operator:
            filters["operator_name"] = operator

        date_start = self.res_log_start.get().strip()
        if date_start:
            filters["start_date"] = date_start
        date_end = self.res_log_end.get().strip()
        if date_end:
            filters["end_date"] = date_end

        return filters

    def refresh_reservation_logs(self):
        for item in self.res_log_tree.get_children():
            self.res_log_tree.delete(item)

        try:
            filters = self.get_reservation_log_filters()
            logs = self.manager.get_reservation_logs(filters)

            for log in logs:
                op_type = RESERVATION_OPERATION_DISPLAY.get(log["operation_type"], log["operation_type"])
                status_before = RESERVATION_STATUS_DISPLAY.get(log["status_before"], log["status_before"] or "-")
                status_after = RESERVATION_STATUS_DISPLAY.get(log["status_after"], log["status_after"] or "-")

                locked_change = log.get("locked_qty_change", 0)
                locked_str = f"+{locked_change}" if locked_change > 0 else str(locked_change) if locked_change != 0 else "-"
                stock_change = log.get("stock_qty_change", 0)
                stock_str = f"+{stock_change}" if stock_change > 0 else str(stock_change) if stock_change != 0 else "-"

                tags = ()
                if log["operation_type"] == "revert":
                    tags = ('reverted',)
                elif log["operation_type"] == "expire_release":
                    tags = ('expired',)

                self.res_log_tree.insert('', 'end', values=(
                    log["id"], log.get("reservation_id", "-") or "-",
                    op_type, log.get("reagent_name", "-") or "-",
                    log.get("batch_number", "-") or "-",
                    log.get("quantity", "-") or "-",
                    status_before, status_after,
                    locked_str, stock_str,
                    log.get("operator_name", "-") or "-",
                    log.get("reviewer_name", "-") or "-",
                    log["operation_time"], log.get("remarks", "") or ""
                ), tags=tags)

            self.res_log_tree.tag_configure('reverted', background='#e0e0e0', foreground='gray')
            self.res_log_tree.tag_configure('expired', background='#f5c6cb')

            self.set_status(f"预约日志：{len(logs)} 条记录")
        except OperationError as e:
            messagebox.showerror("错误", str(e))

    def export_reservation_logs_dialog(self):
        if not self.auth.has_permission("view_reservation_logs"):
            messagebox.showerror("权限不足", "当前角色无预约日志查看权限，无法导出")
            return

        filters = self.get_reservation_log_filters()

        current_count = 0
        try:
            current_logs = self.manager.get_reservation_logs(filters)
            current_count = len(current_logs)
        except OperationError as e:
            messagebox.showerror("错误", str(e))
            return

        if current_count == 0:
            messagebox.showinfo("提示", "当前没有符合筛选条件的预约日志，无需导出。")
            return

        default_filename = f"预约日志_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        filepath = filedialog.asksaveasfilename(
            title="导出预约日志 CSV",
            defaultextension=".csv",
            initialfile=default_filename,
            filetypes=[("CSV 文件", "*.csv"), ("所有文件", "*.*")]
        )

        if not filepath:
            return

        try:
            count, msg = self.csv_manager.export_reservation_logs(filepath, filters)
            if count == 0:
                messagebox.showinfo("提示", msg)
            else:
                messagebox.showinfo("导出成功", f"{msg}\n\n共导出 {count} 条记录。\n\n文件路径：{filepath}")
                self.set_status(f"已导出 {count} 条预约日志到 {filepath}")
        except PermissionError as e:
            messagebox.showerror("权限不足", str(e))
        except Exception as e:
            messagebox.showerror("导出失败", f"导出过程中发生错误：{str(e)}")

    def setup_ledger_tab(self):
        frame = self.tab_ledger

        filter_frame = ttk.LabelFrame(frame, text="筛选条件", padding=10)
        filter_frame.pack(fill='x', pady=10, padx=10)

        ttk.Label(filter_frame, text="试剂名称：").grid(row=0, column=0, padx=5, pady=5)
        self.ledger_name = ttk.Entry(filter_frame, width=15)
        self.ledger_name.grid(row=0, column=1, padx=5, pady=5)

        ttk.Label(filter_frame, text="批号：").grid(row=0, column=2, padx=5, pady=5)
        self.ledger_batch = ttk.Entry(filter_frame, width=15)
        self.ledger_batch.grid(row=0, column=3, padx=5, pady=5)

        ttk.Label(filter_frame, text="操作类型：").grid(row=0, column=4, padx=5, pady=5)
        ledger_types = ["全部", "入库", "审核领用", "归还", "报废", "盘点调整", "CSV导入"]
        self.ledger_type = ttk.Combobox(filter_frame, values=ledger_types, state='readonly', width=10)
        self.ledger_type.grid(row=0, column=5, padx=5, pady=5)
        self.ledger_type.current(0)

        ttk.Button(filter_frame, text="查询", command=self.refresh_ledger).grid(row=0, column=6, padx=10, pady=5)
        ttk.Button(filter_frame, text="重置", command=self.reset_ledger_filters).grid(row=0, column=7, padx=5, pady=5)
        ttk.Button(filter_frame, text="导出台账", command=self.export_ledger_dialog).grid(row=0, column=8, padx=5, pady=5)

        tree_frame = ttk.Frame(frame)
        tree_frame.pack(fill='both', expand=True, padx=10, pady=10)

        columns = ("id", "reagent", "batch", "type", "change", "balance", "operator", "reviewer", "time", "remarks")
        self.ledger_tree = ttk.Treeview(tree_frame, columns=columns, show='headings')

        headings = [
            ("id", "ID", 60),
            ("reagent", "试剂名称", 150),
            ("batch", "批号", 120),
            ("type", "操作类型", 100),
            ("change", "变动数量", 90),
            ("balance", "结存数量", 90),
            ("operator", "操作人", 100),
            ("reviewer", "审核人", 100),
            ("time", "操作时间", 150),
            ("remarks", "备注", 200)
        ]

        for col, text, width in headings:
            self.ledger_tree.heading(col, text=text)
            self.ledger_tree.column(col, width=width, anchor='center')

        scrollbar = ttk.Scrollbar(tree_frame, orient='vertical', command=self.ledger_tree.yview)
        self.ledger_tree.configure(yscrollcommand=scrollbar.set)

        self.ledger_tree.pack(side='left', fill='both', expand=True)
        scrollbar.pack(side='right', fill='y')

        self.refresh_ledger()

    def reset_ledger_filters(self):
        self.ledger_name.delete(0, 'end')
        self.ledger_batch.delete(0, 'end')
        self.ledger_type.current(0)
        self.refresh_ledger()

    def get_ledger_filters(self):
        filters = {}
        name = self.ledger_name.get().strip()
        if name:
            filters["reagent_name"] = name
        batch = self.ledger_batch.get().strip()
        if batch:
            filters["batch_number"] = batch

        type_map = {
            "入库": "stock_in",
            "审核领用": "approve_use",
            "归还": "return",
            "报废": "scrap",
            "盘点调整": "stocktake",
            "CSV导入": "import"
        }
        type_val = self.ledger_type.get()
        if type_val in type_map:
            filters["operation_type"] = type_map[type_val]

        return filters

    def refresh_ledger(self):
        for item in self.ledger_tree.get_children():
            self.ledger_tree.delete(item)

        try:
            filters = self.get_ledger_filters()
            ledger = self.manager.get_ledger(filters)
            for entry in ledger:
                op_type = OPERATION_TYPE_DISPLAY.get(entry["operation_type"], entry["operation_type"])
                change = entry["change_quantity"]
                change_str = f"+{change}" if change > 0 else str(change)

                tags = ()
                if change > 0:
                    tags = ('positive',)
                elif change < 0:
                    tags = ('negative',)

                self.ledger_tree.insert('', 'end', values=(
                    entry["id"], entry["reagent_name"], entry["batch_number"],
                    op_type, change_str, entry["balance_quantity"],
                    entry["operator"], entry.get("reviewer", "") or "",
                    entry["operation_time"], entry["remarks"] or ""
                ), tags=tags)

            self.ledger_tree.tag_configure('positive', foreground='green')
            self.ledger_tree.tag_configure('negative', foreground='red')

            self.set_status(f"库存台账：{len(ledger)} 条记录")
        except OperationError as e:
            messagebox.showerror("错误", str(e))

    def export_ledger_dialog(self):
        if not self.auth.has_permission("export_csv"):
            messagebox.showerror("错误", "权限不足")
            return

        default_name = f"库存台账_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        filepath = filedialog.asksaveasfilename(
            title="导出库存台账",
            defaultextension=".csv",
            initialfile=default_name,
            filetypes=[("CSV 文件", "*.csv")]
        )
        if not filepath:
            return

        try:
            filters = self.get_ledger_filters()
            count, msg = self.csv_manager.export_ledger(filepath, filters)
            messagebox.showinfo("成功", msg)
        except Exception as e:
            messagebox.showerror("错误", f"导出失败：{str(e)}")

    def setup_import_export_tab(self):
        frame = self.tab_import_export

        notebook = ttk.Notebook(frame)
        notebook.pack(fill='both', expand=True, padx=10, pady=10)

        export_tab = ttk.Frame(notebook)
        import_tab = ttk.Frame(notebook)
        sample_tab = ttk.Frame(notebook)

        notebook.add(export_tab, text='导出数据')
        notebook.add(import_tab, text='导入数据')
        notebook.add(sample_tab, text='生成样例')

        self.setup_export_tab(export_tab)
        self.setup_import_tab(import_tab)
        self.setup_sample_tab(sample_tab)

    def setup_export_tab(self, frame):
        main_frame = ttk.Frame(frame, padding=20)
        main_frame.pack(fill='both', expand=True)

        ttk.Label(main_frame, text="导出库存数据", font=('Microsoft YaHei', 14, 'bold')).pack(pady=(0, 20))

        export_frame = ttk.Frame(main_frame)
        export_frame.pack(pady=20)

        ttk.Button(export_frame, text="导出当前筛选的库存", command=self.export_reagents_dialog,
                   width=25).pack(pady=10, ipadx=10, ipady=10)

        ttk.Button(export_frame, text="导出全部库存台账", command=self.export_ledger_dialog,
                   width=25).pack(pady=10, ipadx=10, ipady=10)

        info = ttk.LabelFrame(main_frame, text="说明", padding=15)
        info.pack(fill='x', pady=30)
        ttk.Label(info, text="• 导出的 CSV 文件使用 UTF-8 BOM 编码，可直接用 Excel 打开", wraplength=800).pack(anchor='w', pady=2)
        ttk.Label(info, text="• 库存数据导出包含所有试剂信息", wraplength=800).pack(anchor='w', pady=2)
        ttk.Label(info, text="• 台账导出包含所有出入库历史记录", wraplength=800).pack(anchor='w', pady=2)

    def export_reagents_dialog(self):
        if not self.auth.has_permission("export_csv"):
            messagebox.showerror("错误", "权限不足")
            return

        default_name = f"试剂库存_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        filepath = filedialog.asksaveasfilename(
            title="导出试剂库存",
            defaultextension=".csv",
            initialfile=default_name,
            filetypes=[("CSV 文件", "*.csv")]
        )
        if not filepath:
            return

        try:
            filters = self.get_inventory_filters()
            count, msg = self.csv_manager.export_reagents(filepath, filters)
            messagebox.showinfo("成功", msg)
        except Exception as e:
            messagebox.showerror("错误", f"导出失败：{str(e)}")

    def setup_import_tab(self, frame):
        main_frame = ttk.Frame(frame, padding=20)
        main_frame.pack(fill='both', expand=True)

        ttk.Label(main_frame, text="导入库存数据（方案管理）", font=('Microsoft YaHei', 14, 'bold')).pack(pady=(0, 20))

        has_import_perm = self.auth.has_permission("import_csv")
        has_revert_perm = self.auth.has_permission("revert_import")
        has_audit_perm = self.auth.has_permission("view_import_audit")

        self._current_plan_id = None

        if not has_import_perm:
            perm_frame = ttk.Frame(main_frame)
            perm_frame.pack(pady=30)
            ttk.Label(perm_frame, text="⛔", font=('Microsoft YaHei', 32)).pack(pady=10)
            ttk.Label(perm_frame, text="当前角色无 CSV 导入和预检权限",
                     font=('Microsoft YaHei', 12, 'bold'), foreground='red').pack(pady=5)
            ttk.Label(perm_frame,
                     text=f"您的角色：{self.auth.get_role_display()}",
                     foreground='#666').pack(pady=2)
            ttk.Label(perm_frame,
                     text="如需导入数据，请联系管理员或授权用户操作。",
                     foreground='#666').pack(pady=10)

            if has_audit_perm:
                self._setup_audit_section(main_frame)

            history_frame = ttk.LabelFrame(main_frame, text="导入方案历史（只读）", padding=10)
            history_frame.pack(fill='both', expand=True, pady=10)
            self._setup_plan_history_tree(history_frame, readonly=True)
            self._refresh_plan_history()
            return

        self._check_pending_drafts()

        file_frame = ttk.Frame(main_frame)
        file_frame.pack(fill='x', pady=(10, 5))

        ttk.Label(file_frame, text="选择 CSV 文件：").pack(side='left', padx=5)
        self.import_path_var = tk.StringVar()
        path_entry = ttk.Entry(file_frame, textvariable=self.import_path_var, width=50)
        path_entry.pack(side='left', padx=5, fill='x', expand=True)

        def browse_file():
            filepath = filedialog.askopenfilename(
                title="选择 CSV 文件",
                filetypes=[("CSV 文件", "*.csv"), ("所有文件", "*.*")]
            )
            if filepath:
                self.import_path_var.set(filepath)
                self._current_plan_id = None
                self._current_preview_hash = None
                self._current_preview_result = None
                self._update_import_buttons()

        ttk.Button(file_frame, text="浏览...", command=browse_file).pack(side='left', padx=5)

        btn_frame = ttk.Frame(main_frame)
        btn_frame.pack(pady=10)

        self.btn_create_plan = ttk.Button(btn_frame, text="📋 创建导入方案", command=self._do_create_plan, width=15, state='disabled')
        self.btn_create_plan.pack(side='left', padx=5, ipadx=5, ipady=8)

        self.btn_confirm_import = ttk.Button(btn_frame, text="✅ 确认导入", command=self._do_confirm_import, width=15, state='disabled')
        self.btn_confirm_import.pack(side='left', padx=5, ipadx=5, ipady=8)

        self.btn_cancel_plan = ttk.Button(btn_frame, text="❌ 取消方案", command=self._do_cancel_plan, width=15, state='disabled')
        self.btn_cancel_plan.pack(side='left', padx=5, ipadx=5, ipady=8)

        if has_revert_perm:
            self.btn_revert_import = ttk.Button(btn_frame, text="↩️ 撤销上次导入", command=self._do_revert_import, width=15)
            self.btn_revert_import.pack(side='left', padx=5, ipadx=5, ipady=8)
            self._update_revert_button()

        self.import_status_var = tk.StringVar(value="请选择CSV文件后点击\"创建导入方案\"")
        status_label = ttk.Label(main_frame, textvariable=self.import_status_var, foreground='#1976D2')
        status_label.pack(pady=5)

        result_paned = ttk.PanedWindow(main_frame, orient='vertical')
        result_paned.pack(fill='both', expand=True, pady=5)

        preview_frame = ttk.LabelFrame(result_paned, text="方案预览/导入结果", padding=10)
        result_paned.add(preview_frame, weight=3)

        self.preview_text = tk.Text(preview_frame, height=15, font=('Consolas', 10), wrap='none')
        preview_scroll_y = ttk.Scrollbar(preview_frame, orient='vertical', command=self.preview_text.yview)
        preview_scroll_x = ttk.Scrollbar(preview_frame, orient='horizontal', command=self.preview_text.xview)
        self.preview_text.configure(yscrollcommand=preview_scroll_y.set, xscrollcommand=preview_scroll_x.set)
        self.preview_text.pack(side='left', fill='both', expand=True)
        preview_scroll_y.pack(side='right', fill='y')
        preview_scroll_x.pack(side='bottom', fill='x')
        self.preview_text.insert('1.0', "方案预览结果将显示在这里...")
        self.preview_text.configure(state='disabled')

        conflict_frame = ttk.LabelFrame(result_paned, text="冲突处理（如有）", padding=10)
        result_paned.add(conflict_frame, weight=2)

        self.conflict_tree = ttk.Treeview(conflict_frame, columns=("row", "name", "batch", "type", "existing_qty", "import_qty", "resolution"), show='headings')
        conflict_headings = [
            ("row", "行号", 60),
            ("name", "试剂名称", 150),
            ("batch", "批号", 120),
            ("type", "冲突类型", 100),
            ("existing_qty", "现有数量", 80),
            ("import_qty", "导入数量", 80),
            ("resolution", "处理方式", 120)
        ]
        for col, text, width in conflict_headings:
            self.conflict_tree.heading(col, text=text)
            self.conflict_tree.column(col, width=width, anchor='center')

        conflict_scroll = ttk.Scrollbar(conflict_frame, orient='vertical', command=self.conflict_tree.yview)
        self.conflict_tree.configure(yscrollcommand=conflict_scroll.set)
        self.conflict_tree.pack(side='left', fill='both', expand=True)
        conflict_scroll.pack(side='right', fill='y')
        self.conflict_tree.bind('<Double-1>', self._on_conflict_double_click)

        conflict_btn_frame = ttk.Frame(conflict_frame)
        conflict_btn_frame.pack(fill='x', pady=5)
        ttk.Button(conflict_btn_frame, text="批量处理（全部保留现有）",
                  command=lambda: self._do_resolve_all_conflicts("keep_existing")).pack(side='left', padx=5)
        ttk.Button(conflict_btn_frame, text="批量处理（全部覆盖）",
                  command=lambda: self._do_resolve_all_conflicts("overwrite")).pack(side='left', padx=5)
        ttk.Button(conflict_btn_frame, text="批量处理（全部跳过）",
                  command=lambda: self._do_resolve_all_conflicts("skip")).pack(side='left', padx=5)

        plan_history_frame = ttk.LabelFrame(main_frame, text="导入方案历史", padding=10)
        plan_history_frame.pack(fill='both', expand=True, pady=10)
        self._setup_plan_history_tree(plan_history_frame, readonly=False)
        self._refresh_plan_history()

        if has_audit_perm:
            self._setup_audit_section(main_frame)

        info = ttk.LabelFrame(main_frame, text="CSV 格式要求", padding=15)
        info.pack(fill='x', pady=10)

        required = ["试剂名称", "批号", "数量", "单位"]
        optional = ["过期日期", "低库存阈值", "规格", "生产厂商", "储存条件", "备注"]

        ttk.Label(info, text="必填列：" + "、".join(required), foreground='red').pack(anchor='w', pady=2)
        ttk.Label(info, text="可选列：" + "、".join(optional)).pack(anchor='w', pady=2)
        ttk.Label(info, text="• 过期日期格式：YYYY-MM-DD，如 2027-12-31", wraplength=800).pack(anchor='w', pady=2)
        ttk.Label(info, text="• 数量必须是正整数", wraplength=800).pack(anchor='w', pady=2)
        ttk.Label(info, text="• 相同名称和批号的试剂需要选择处理方式（保留/覆盖/跳过）", wraplength=800).pack(anchor='w', pady=2)
        ttk.Label(info, text="• 方案创建后不写入正式数据，确认后才会导入", wraplength=800, foreground='#1976D2').pack(anchor='w', pady=2)
        ttk.Label(info, text="• 方案支持跨重启恢复，关闭程序后可继续查看未完成方案", wraplength=800, foreground='#1976D2').pack(anchor='w', pady=2)

        self.import_path_var.trace_add('write', lambda *args: self._update_import_buttons())
        self._update_import_buttons()

    def _update_import_buttons(self):
        filepath = self.import_path_var.get().strip() if hasattr(self, 'import_path_var') else ""
        file_exists = filepath and os.path.exists(filepath)

        if hasattr(self, 'btn_preview'):
            self.btn_preview.configure(state='normal' if file_exists else 'disabled')

        if hasattr(self, 'btn_import'):
            has_preview = self._current_preview_hash is not None
            self.btn_import.configure(state='normal' if (file_exists and has_preview) else 'disabled')

        if hasattr(self, 'btn_reset_preview'):
            has_preview = self._current_preview_hash is not None
            self.btn_reset_preview.configure(state='normal' if has_preview else 'disabled')

        if hasattr(self, 'import_status_var'):
            if not filepath:
                self.import_status_var.set("请选择CSV文件后点击\"预检导入\"")
            elif not file_exists:
                self.import_status_var.set("文件不存在，请重新选择")
            elif self._current_preview_hash:
                file_changed, _ = self.csv_manager.check_file_changed(filepath, self._current_preview_hash)
                if file_changed:
                    self.import_status_var.set("⚠️ 文件已修改，请重新预检")
                else:
                    self.import_status_var.set("✅ 已完成预检，可执行导入")
            else:
                self.import_status_var.set("请点击\"预检导入\"验证数据")

    def _set_preview_text(self, text):
        self.preview_text.configure(state='normal')
        self.preview_text.delete('1.0', 'end')
        self.preview_text.insert('1.0', text)
        self.preview_text.configure(state='disabled')

    def _do_preview(self):
        filepath = self.import_path_var.get().strip()
        if not filepath:
            messagebox.showwarning("提示", "请先选择 CSV 文件")
            return
        if not os.path.exists(filepath):
            messagebox.showerror("错误", "文件不存在")
            return

        try:
            self.set_status("正在预检数据...")
            self.root.update_idletasks()

            preview_result = self.csv_manager.preview_import(filepath)
            self._current_preview_hash = preview_result["file_hash"]
            self._current_preview_result = preview_result

            summary = self.csv_manager.get_preview_summary(preview_result)
            self._set_preview_text(summary)

            if preview_result.get("is_cached"):
                self.import_status_var.set("ℹ️ 使用缓存的预检结果")
            else:
                self.import_status_var.set("✅ 预检完成，可执行导入")

            self._update_import_buttons()
            self.set_status("预检完成")

            if preview_result["stock_warnings"] or preview_result["conflict_batches"]:
                messagebox.showwarning(
                    "预检完成（含警告）",
                    f"预检完成，发现 {len(preview_result['conflict_batches'])} 个批号冲突，"
                    f"{len(preview_result['stock_warnings'])} 条库存警告。\n"
                    "请在下方查看详细信息后再决定是否导入。"
                )
            else:
                messagebox.showinfo(
                    "预检完成",
                    f"预检完成！\n\n"
                    f"预计新增：{preview_result['success_count']} 条\n"
                    f"预计跳过：{preview_result['skip_count']} 条\n\n"
                    "请在下方查看详细信息后再决定是否导入。"
                )
        except PermissionError as e:
            messagebox.showerror("权限不足", str(e))
            self.set_status("预检失败：权限不足")
        except Exception as e:
            messagebox.showerror("预检失败", f"预检过程中发生错误：{str(e)}")
            self.set_status("预检失败")

    def _reset_preview(self):
        self._current_preview_hash = None
        self._current_preview_result = None
        self._set_preview_text("预检结果已清除，可重新执行预检...")
        self._update_import_buttons()

    def _do_import(self):
        filepath = self.import_path_var.get().strip()
        if not filepath:
            messagebox.showwarning("提示", "请先选择 CSV 文件")
            return
        if not os.path.exists(filepath):
            messagebox.showerror("错误", "文件不存在")
            return

        if self._current_preview_hash:
            file_changed, _ = self.csv_manager.check_file_changed(filepath, self._current_preview_hash)
            if file_changed:
                if not messagebox.askyesno(
                    "文件已修改",
                    "检测到文件内容已变化，预检结果可能已失效。\n\n"
                    "是否重新执行预检？\n\n"
                    "是 - 重新预检\n"
                    "否 - 继续使用当前文件（将重新校验）"
                ):
                    self._current_preview_hash = None
                else:
                    self._do_preview()
                    return

        if not messagebox.askyesno(
            "确认导入",
            "即将执行正式导入操作。\n\n"
            "导入数据会自动创建新试剂记录，并写入操作日志和台账。\n"
            "此操作不可撤销，请确认数据无误。\n\n"
            "确定继续吗？"
        ):
            return

        try:
            self.set_status("正在导入数据...")
            self.root.update_idletasks()

            use_cached = self._current_preview_hash is not None
            expected_hash = self._current_preview_hash if use_cached else None

            success, skipped, errors, warnings = self.csv_manager.import_reagents(
                filepath, use_cached=use_cached, expected_hash=expected_hash
            )

            summary = self.csv_manager.get_import_summary(success, skipped, errors, warnings)
            self._set_preview_text(summary)

            self._current_preview_hash = None
            self._current_preview_result = None
            self._update_import_buttons()
            self._refresh_import_history()
            self.refresh_inventory()
            self.refresh_history()
            self.refresh_ledger()
            self.set_status("导入完成")

            if warnings or errors:
                messagebox.showwarning(
                    "导入完成（含警告/错误）",
                    f"导入完成！\n\n"
                    f"成功：{success} 条\n"
                    f"跳过：{skipped} 条\n\n"
                    f"警告：{len(warnings)} 条\n"
                    f"错误：{len(errors)} 条\n\n"
                    "请在下方查看详细结果。"
                )
            else:
                messagebox.showinfo(
                    "导入完成",
                    f"导入完成！\n\n"
                    f"成功导入：{success} 条\n"
                    f"跳过：{skipped} 条\n\n"
                    "导入结果已记录到日志和台账。"
                )
        except PermissionError as e:
            messagebox.showerror("权限不足", str(e))
            self.set_status("导入失败：权限不足")
        except ValueError as e:
            if "文件内容已变化" in str(e):
                if messagebox.askyesno("文件已变化", f"{str(e)}\n\n是否重新执行预检？"):
                    self._do_preview()
            else:
                messagebox.showerror("错误", str(e))
            self.set_status("导入失败")
        except Exception as e:
            messagebox.showerror("导入失败", f"导入过程中发生错误：{str(e)}")
            self.set_status("导入失败")

    def _refresh_import_history(self):
        if not hasattr(self, 'import_history_tree'):
            return

        for item in self.import_history_tree.get_children():
            self.import_history_tree.delete(item)

        try:
            history = self.csv_manager.get_import_history(50)
            status_map = {"previewed": "已预检", "imported": "已导入", "cancelled": "已取消"}
            status_tags = {"previewed": "previewed", "imported": "imported", "cancelled": "cancelled"}

            for h in history:
                filename = os.path.basename(h["filepath"])
                status_display = status_map.get(h["status"], h["status"])
                tag = status_tags.get(h["status"], "")
                self.import_history_tree.insert('', 'end', values=(
                    h["created_at"], h["operator_name"], filename,
                    h["success_count"], h["skip_count"], status_display
                ), tags=(tag,))

            self.import_history_tree.tag_configure('imported', background='#d4edda')
            self.import_history_tree.tag_configure('previewed', background='#fff3cd')
            self.import_history_tree.tag_configure('cancelled', background='#e2e3e5')
        except Exception:
            pass

    def setup_sample_tab(self, frame):
        main_frame = ttk.Frame(frame, padding=20)
        main_frame.pack(fill='both', expand=True)

        ttk.Label(main_frame, text="生成 CSV 导入样例", font=('Microsoft YaHei', 14, 'bold')).pack(pady=(0, 20))

        ttk.Button(main_frame, text="生成样例文件", command=self.create_sample_file,
                   width=20).pack(pady=20, ipadx=10, ipady=10)

        info = ttk.LabelFrame(main_frame, text="样例预览", padding=15)
        info.pack(fill='both', expand=True, pady=20)

        sample_text = tk.Text(info, height=10, font=('Consolas', 10))
        sample_text.pack(fill='both', expand=True)

        sample_content = """试剂名称,批号,数量,单位,过期日期,低库存阈值,规格,生产厂商,储存条件,备注
无水乙醇,20250101,100,瓶,2027-12-31,10,500ml,国药集团,阴凉干燥处,分析纯
氯化钠,20250215,50,瓶,2028-06-30,5,500g,西陇化工,室温,分析纯
甲醇,20241201,30,瓶,2026-11-30,8,500ml,默克,阴凉处,色谱纯
"""
        sample_text.insert('1.0', sample_content)
        sample_text.configure(state='disabled')

    def create_sample_file(self):
        default_name = "试剂导入样例.csv"
        filepath = filedialog.asksaveasfilename(
            title="保存样例文件",
            defaultextension=".csv",
            initialfile=default_name,
            filetypes=[("CSV 文件", "*.csv")]
        )
        if not filepath:
            return

        try:
            msg = self.csv_manager.create_sample_import(filepath)
            messagebox.showinfo("成功", msg)
        except Exception as e:
            messagebox.showerror("错误", f"生成失败：{str(e)}")

    def _setup_plan_history_tree(self, parent_frame, readonly=False):
        self.plan_history_tree = ttk.Treeview(parent_frame, columns=(
            "batch_no", "created_at", "operator", "file", "total", "new", "update",
            "skip", "conflict", "permission", "status"
        ), show='headings')

        plan_headings = [
            ("batch_no", "批次号", 160),
            ("created_at", "创建时间", 150),
            ("operator", "操作人", 80),
            ("file", "文件名", 180),
            ("total", "总行数", 60),
            ("new", "新增", 50),
            ("update", "更新", 50),
            ("skip", "跳过", 50),
            ("conflict", "冲突", 50),
            ("permission", "权限受限", 70),
            ("status", "状态", 80)
        ]
        for col, text, width in plan_headings:
            self.plan_history_tree.heading(col, text=text)
            self.plan_history_tree.column(col, width=width, anchor='center')

        plan_scroll = ttk.Scrollbar(parent_frame, orient='vertical', command=self.plan_history_tree.yview)
        self.plan_history_tree.configure(yscrollcommand=plan_scroll.set)
        self.plan_history_tree.pack(side='left', fill='both', expand=True)
        plan_scroll.pack(side='right', fill='y')

        if not readonly:
            self.plan_history_tree.bind('<Double-1>', self._on_plan_double_click)

    def _refresh_plan_history(self):
        if not hasattr(self, 'plan_history_tree'):
            return

        for item in self.plan_history_tree.get_children():
            self.plan_history_tree.delete(item)

        try:
            plans = self.csv_manager.get_all_plans(50)
            status_map = {
                "draft": "草稿",
                "confirmed": "已确认",
                "cancelled": "已取消",
                "reverted": "已撤销"
            }
            status_tags = {
                "draft": "draft",
                "confirmed": "confirmed",
                "cancelled": "cancelled",
                "reverted": "reverted"
            }

            for p in plans:
                filename = os.path.basename(p["filepath"])
                status_display = status_map.get(p["status"], p["status"])
                tag = status_tags.get(p["status"], "")
                self.plan_history_tree.insert('', 'end', values=(
                    p["batch_no"], p["created_at"], p["operator_name"],
                    filename, p["total_rows"], p["new_count"], p["update_count"],
                    p["skip_count"], p["conflict_count"], p["permission_denied_count"],
                    status_display
                ), tags=(tag,), iid=str(p["id"]))

            self.plan_history_tree.tag_configure('draft', background='#fff3cd')
            self.plan_history_tree.tag_configure('confirmed', background='#d4edda')
            self.plan_history_tree.tag_configure('cancelled', background='#e2e3e5')
            self.plan_history_tree.tag_configure('reverted', background='#ffeeba')
        except Exception:
            pass

    def _setup_audit_section(self, parent_frame):
        audit_frame = ttk.LabelFrame(parent_frame, text="导入审计日志", padding=10)
        audit_frame.pack(fill='x', pady=10)

        self.audit_tree = ttk.Treeview(audit_frame, columns=(
            "time", "operator", "action", "file", "counts"
        ), show='headings', height=6)

        audit_headings = [
            ("time", "操作时间", 150),
            ("operator", "操作人", 80),
            ("action", "操作类型", 100),
            ("file", "文件", 250),
            ("counts", "处理数量", 150)
        ]
        for col, text, width in audit_headings:
            self.audit_tree.heading(col, text=text)
            self.audit_tree.column(col, width=width, anchor='w')

        audit_scroll = ttk.Scrollbar(audit_frame, orient='vertical', command=self.audit_tree.yview)
        self.audit_tree.configure(yscrollcommand=audit_scroll.set)
        self.audit_tree.pack(side='left', fill='both', expand=True)
        audit_scroll.pack(side='right', fill='y')

        self._refresh_audit_logs()

    def _refresh_audit_logs(self):
        if not hasattr(self, 'audit_tree'):
            return

        for item in self.audit_tree.get_children():
            self.audit_tree.delete(item)

        try:
            logs = self.csv_manager.get_audit_logs(limit=20)
            action_map = {
                "create_plan": "创建方案",
                "confirm_import": "确认导入",
                "cancel_plan": "取消方案",
                "revert_import": "撤销导入"
            }

            for log in logs:
                try:
                    import json
                    counts = json.loads(log["counts_summary"])
                    counts_str = f"总{counts.get('total', 0)} 新{counts.get('new', 0)} 更{counts.get('update', 0)} 跳{counts.get('skip', 0)}"
                except Exception:
                    counts_str = "-"

                self.audit_tree.insert('', 'end', values=(
                    log["operation_time"], log["operator_name"],
                    action_map.get(log["action"], log["action"]),
                    log["file_summary"], counts_str
                ))
        except Exception:
            pass

    def _check_pending_drafts(self):
        try:
            drafts = self.csv_manager.get_pending_drafts()
            if drafts:
                msg = f"您有 {len(drafts)} 个未完成的导入方案。\n\n"
                for d in drafts[:3]:
                    msg += f"  • {d['batch_no']} - {os.path.basename(d['filepath'])}\n"
                if len(drafts) > 3:
                    msg += f"  ... 还有 {len(drafts) - 3} 个\n"
                msg += "\n是否在下方历史记录中双击查看并继续？"
                messagebox.showinfo("未完成方案", msg)
        except Exception:
            pass

    def _on_plan_double_click(self, event):
        item = self.plan_history_tree.selection()
        if not item:
            return

        try:
            plan_id = int(item[0])
            plan = self.csv_manager.get_plan_preview(plan_id)
            if not plan:
                messagebox.showwarning("提示", "方案不存在或已被删除")
                return

            self._current_plan_id = plan_id
            self._display_plan_preview(plan)
            self._display_conflicts(plan)
            self._update_import_buttons()
            self.import_status_var.set(f"已加载方案：{plan['plan']['batch_no']}")

        except Exception as e:
            messagebox.showerror("错误", f"加载方案失败：{str(e)}")

    def _display_plan_preview(self, plan_data):
        summary = self.csv_manager.get_plan_summary(plan_data)
        self._set_preview_text(summary)

    def _display_conflicts(self, plan_data):
        for item in self.conflict_tree.get_children():
            self.conflict_tree.delete(item)

        import json
        for item in plan_data["conflict_items"]:
            resolution = item.get("conflict_resolution")
            resolution_display = ""
            if resolution == "keep_existing":
                resolution_display = "保留现有"
            elif resolution == "overwrite":
                resolution_display = "覆盖"
            elif resolution == "skip":
                resolution_display = "跳过"

            existing_qty = ""
            try:
                if item.get("conflict_details"):
                    details = item["conflict_details"]
                    if isinstance(details, str):
                        details = json.loads(details)
                    existing_qty = details.get("existing_quantity", "")
            except Exception:
                pass

            conflict_type_map = {
                "duplicate_batch": "批号重复",
                "personnel": "人员冲突",
                "date": "日期冲突",
                "shift": "班次冲突",
                "role_permission": "角色权限"
            }
            conflict_type_display = conflict_type_map.get(item.get("conflict_type", ""), item.get("conflict_type", ""))

            self.conflict_tree.insert('', 'end', values=(
                item["row_num"], item["name"], item["batch_number"],
                conflict_type_display, existing_qty, item["quantity"],
                resolution_display or "待处理"
            ), iid=str(item["id"]))

    def _on_conflict_double_click(self, event):
        selection = self.conflict_tree.selection()
        if not selection:
            return

        item_id = int(selection[0])
        self._show_conflict_resolution_dialog(item_id)

    def _show_conflict_resolution_dialog(self, item_id):
        item = self.csv_manager.get_plan_preview(self._current_plan_id)
        if not item:
            return

        conflict_item = None
        for ci in item["conflict_items"]:
            if ci["id"] == item_id:
                conflict_item = ci
                break

        if not conflict_item:
            return

        dialog = tk.Toplevel(self.root)
        dialog.title("冲突处理选择")
        dialog.geometry("500x400")
        dialog.transient(self.root)
        dialog.grab_set()

        import json
        try:
            details = conflict_item.get("conflict_details")
            if isinstance(details, str):
                details = json.loads(details)
        except Exception:
            details = {}

        frame = ttk.Frame(dialog, padding=20)
        frame.pack(fill='both', expand=True)

        ttk.Label(frame, text="⚠️  冲突处理", font=('Microsoft YaHei', 14, 'bold')).pack(pady=(0, 15))

        info_frame = ttk.LabelFrame(frame, text="冲突详情", padding=10)
        info_frame.pack(fill='x', pady=10)

        ttk.Label(info_frame, text=f"试剂名称：{conflict_item['name']}").pack(anchor='w', pady=2)
        ttk.Label(info_frame, text=f"批号：{conflict_item['batch_number']}").pack(anchor='w', pady=2)
        ttk.Label(info_frame, text=f"导入数量：{conflict_item['quantity']} {conflict_item['unit']}").pack(anchor='w', pady=2)
        if details:
            ttk.Label(info_frame, text=f"现有数量：{details.get('existing_quantity', '未知')} {details.get('existing_unit', '')}").pack(anchor='w', pady=2)
            if details.get('existing_expiration'):
                ttk.Label(info_frame, text=f"现有过期日期：{details['existing_expiration']}").pack(anchor='w', pady=2)

        ttk.Label(frame, text="请选择处理方式：", font=('Microsoft YaHei', 11, 'bold')).pack(anchor='w', pady=(15, 10))

        resolution_var = tk.StringVar(value="keep_existing")

        ttk.Radiobutton(frame, text="保留现有数据（跳过此条）",
                       variable=resolution_var, value="keep_existing").pack(anchor='w', pady=5)
        ttk.Radiobutton(frame, text="覆盖现有数据（数量累加，其他字段更新）",
                       variable=resolution_var, value="overwrite").pack(anchor='w', pady=5)
        ttk.Radiobutton(frame, text="跳过此条（不导入）",
                       variable=resolution_var, value="skip").pack(anchor='w', pady=5)

        def apply_resolution():
            try:
                self.csv_manager.resolve_conflict(item_id, resolution_var.get())
                plan = self.csv_manager.get_plan_preview(self._current_plan_id)
                if plan:
                    self._display_conflicts(plan)
                messagebox.showinfo("成功", "冲突处理方式已保存")
                dialog.destroy()
                self._update_import_buttons()
            except Exception as e:
                messagebox.showerror("错误", f"处理失败：{str(e)}")

        btn_frame = ttk.Frame(frame)
        btn_frame.pack(pady=20)
        ttk.Button(btn_frame, text="确定", command=apply_resolution, width=15).pack(side='left', padx=10)
        ttk.Button(btn_frame, text="取消", command=dialog.destroy, width=15).pack(side='left', padx=10)

    def _do_resolve_all_conflicts(self, resolution):
        if not self._current_plan_id:
            messagebox.showwarning("提示", "请先选择或创建导入方案")
            return

        try:
            count = self.csv_manager.resolve_all_conflicts(self._current_plan_id, resolution)
            plan = self.csv_manager.get_plan_preview(self._current_plan_id)
            if plan:
                self._display_conflicts(plan)
            resolution_text = {"keep_existing": "保留现有", "overwrite": "覆盖", "skip": "跳过"}[resolution]
            messagebox.showinfo("成功", f"已批量处理 {count} 条冲突（{resolution_text}）")
            self._update_import_buttons()
        except Exception as e:
            messagebox.showerror("错误", f"批量处理失败：{str(e)}")

    def _do_create_plan(self):
        filepath = self.import_path_var.get().strip()
        if not filepath:
            messagebox.showwarning("提示", "请先选择 CSV 文件")
            return
        if not os.path.exists(filepath):
            messagebox.showerror("错误", "文件不存在")
            return

        try:
            self.set_status("正在创建导入方案...")
            self.root.update_idletasks()

            plan = self.csv_manager.create_import_plan(filepath)
            self._current_plan_id = plan["plan_id"]

            plan_data = self.csv_manager.get_plan_preview(plan["plan_id"])
            self._display_plan_preview(plan_data)
            self._display_conflicts(plan_data)
            self._refresh_plan_history()
            self._refresh_audit_logs()

            msg = f"方案创建成功！\n\n批次号：{plan['batch_no']}\n\n"
            msg += f"总行数：{plan['total_rows']}\n"
            msg += f"新增：{plan['new_count']} 条\n"
            msg += f"更新：{plan['update_count']} 条\n"
            msg += f"跳过：{plan['skip_count']} 条\n"
            msg += f"冲突：{plan['conflict_count']} 条\n"
            msg += f"权限受限：{plan['permission_denied_count']} 条\n\n"

            if plan['conflict_count'] > 0:
                msg += "⚠️  存在冲突记录，请在下方冲突列表中双击处理，或使用批量处理按钮。\n\n"

            msg += "方案已保存，关闭程序后可在历史记录中双击继续。\n"
            msg += "确认无误后点击\"确认导入\"执行正式导入。"

            messagebox.showinfo("方案创建成功", msg)
            self.import_status_var.set(f"方案已创建：{plan['batch_no']}")
            self._update_import_buttons()
            self.set_status("方案创建完成")

        except PermissionError as e:
            messagebox.showerror("权限不足", str(e))
            self.set_status("创建方案失败：权限不足")
        except Exception as e:
            messagebox.showerror("创建方案失败", f"{str(e)}")
            self.set_status("创建方案失败")

    def _do_confirm_import(self):
        if not self._current_plan_id:
            messagebox.showwarning("提示", "请先创建或选择导入方案")
            return

        plan_data = self.csv_manager.get_plan_preview(self._current_plan_id)
        if not plan_data:
            messagebox.showerror("错误", "方案不存在")
            return

        if plan_data["conflict_items"]:
            messagebox.showerror("错误", f"还有 {len(plan_data['conflict_items'])} 条冲突未处理，请先处理所有冲突")
            return

        plan = plan_data["plan"]
        if not messagebox.askyesno(
            "确认导入",
            f"即将确认导入方案：{plan['batch_no']}\n\n"
            f"文件：{plan['file_summary']}\n\n"
            f"新增：{plan['new_count']} 条\n"
            f"更新：{plan['update_count']} 条\n"
            f"跳过：{plan['skip_count']} 条\n"
            f"权限受限：{plan['permission_denied_count']} 条\n\n"
            "确认导入后将写入正式数据库，此操作可通过撤销功能恢复。\n\n"
            "确定继续吗？"
        ):
            return

        try:
            self.set_status("正在执行导入...")
            self.root.update_idletasks()

            result = self.csv_manager.confirm_import_plan(self._current_plan_id)

            summary = self.csv_manager.get_plan_summary(
                self.csv_manager.get_plan_preview(self._current_plan_id)
            )
            self._set_preview_text(summary)

            self._refresh_plan_history()
            self._refresh_audit_logs()
            self._refresh_import_history()
            self.refresh_inventory()
            self.refresh_history()
            self.refresh_ledger()
            self._update_revert_button()

            msg = f"导入完成！\n\n"
            msg += f"批次号：{result['batch_no']}\n"
            msg += f"新增：{result['new_count']} 条\n"
            msg += f"更新：{result['update_count']} 条\n"
            msg += f"跳过：{result['skip_count']} 条\n"
            msg += f"总计导入：{result['total_imported']} 条\n"

            if result['errors']:
                msg += f"\n错误：{len(result['errors'])} 条\n"

            messagebox.showinfo("导入完成", msg)
            self.import_status_var.set(f"✅ 导入完成：{result['batch_no']}")
            self.set_status("导入完成")

        except ValueError as e:
            messagebox.showerror("错误", str(e))
            self.set_status("导入失败")
        except PermissionError as e:
            messagebox.showerror("权限不足", str(e))
            self.set_status("导入失败：权限不足")
        except Exception as e:
            messagebox.showerror("导入失败", f"{str(e)}")
            self.set_status("导入失败")

    def _do_cancel_plan(self):
        if not self._current_plan_id:
            messagebox.showwarning("提示", "请先选择导入方案")
            return

        if not messagebox.askyesno("确认取消", "确定要取消此导入方案吗？\n\n取消后方案将标记为已取消，无法继续使用。"):
            return

        try:
            self.csv_manager.cancel_import_plan(self._current_plan_id)
            self._current_plan_id = None
            self._refresh_plan_history()
            self._refresh_audit_logs()
            self._set_preview_text("方案已取消")
            for item in self.conflict_tree.get_children():
                self.conflict_tree.delete(item)
            messagebox.showinfo("成功", "方案已取消")
            self.import_status_var.set("方案已取消")
            self._update_import_buttons()
        except Exception as e:
            messagebox.showerror("错误", f"取消失败：{str(e)}")

    def _do_revert_import(self):
        last_import = self.csv_manager.get_last_revertable_import()
        if not last_import:
            messagebox.showwarning("提示", "没有可撤销的导入记录")
            return

        if not messagebox.askyesno(
            "确认撤销",
            f"即将撤销最近一次导入：\n\n"
            f"批次号：{last_import['batch_no']}\n"
            f"文件：{last_import['file_summary']}\n"
            f"操作人：{last_import['operator_name']}\n"
            f"时间：{last_import['confirmed_at']}\n\n"
            f"新增：{last_import['new_count']} 条\n"
            f"更新：{last_import['update_count']} 条\n\n"
            "撤销后：\n"
            "• 新增的试剂将被删除\n"
            "• 更新的试剂将恢复到导入前状态\n"
            "• 相关台账和操作记录将被移除\n\n"
            "此操作不可恢复，确定继续吗？"
        ):
            return

        try:
            self.set_status("正在撤销导入...")
            self.root.update_idletasks()

            result = self.csv_manager.revert_last_import()

            self._refresh_plan_history()
            self._refresh_audit_logs()
            self._refresh_import_history()
            self.refresh_inventory()
            self.refresh_history()
            self.refresh_ledger()
            self._update_revert_button()

            messagebox.showinfo("撤销成功", result["message"])
            self.set_status("撤销完成")

        except PermissionError as e:
            messagebox.showerror("权限不足", str(e))
            self.set_status("撤销失败：权限不足")
        except Exception as e:
            messagebox.showerror("撤销失败", f"{str(e)}")
            self.set_status("撤销失败")

    def _update_revert_button(self):
        if not hasattr(self, 'btn_revert_import'):
            return

        try:
            last_import = self.csv_manager.get_last_revertable_import()
            if last_import:
                self.btn_revert_import.configure(state='normal')
                self.btn_revert_import.configure(
                    text=f"↩️ 撤销导入 ({last_import['batch_no'][:12]}...)"
                )
            else:
                self.btn_revert_import.configure(state='disabled')
                self.btn_revert_import.configure(text="↩️ 撤销上次导入")
        except Exception:
            self.btn_revert_import.configure(state='disabled')

    def _update_import_buttons(self):
        filepath = self.import_path_var.get().strip() if hasattr(self, 'import_path_var') else ""
        file_exists = filepath and os.path.exists(filepath)
        has_plan = self._current_plan_id is not None

        if hasattr(self, 'btn_create_plan'):
            self.btn_create_plan.configure(state='normal' if file_exists else 'disabled')

        if hasattr(self, 'btn_confirm_import'):
            can_confirm = False
            if has_plan:
                plan = self.csv_manager.get_plan_preview(self._current_plan_id)
                if plan and plan["plan"]["status"] == "draft" and not plan["unresolved_conflict_items"]:
                    can_confirm = True
            self.btn_confirm_import.configure(state='normal' if can_confirm else 'disabled')

        if hasattr(self, 'btn_cancel_plan'):
            can_cancel = False
            if has_plan:
                plan = self.csv_manager.get_plan_preview(self._current_plan_id)
                if plan and plan["plan"]["status"] == "draft":
                    can_cancel = True
            self.btn_cancel_plan.configure(state='normal' if can_cancel else 'disabled')

        if hasattr(self, 'import_status_var'):
            if not filepath:
                self.import_status_var.set("请选择CSV文件后点击\"创建导入方案\"")
            elif not file_exists:
                self.import_status_var.set("文件不存在，请重新选择")
            elif has_plan:
                plan = self.csv_manager.get_plan_preview(self._current_plan_id)
                if plan:
                    if plan["unresolved_conflict_items"]:
                        self.import_status_var.set(f"⚠️ 方案：{plan['plan']['batch_no']}（还有 {len(plan['unresolved_conflict_items'])} 条冲突待处理）")
                    elif plan["plan"]["status"] == "draft":
                        self.import_status_var.set(f"✅ 方案：{plan['plan']['batch_no']}（就绪，可确认导入）")
                    elif plan["plan"]["status"] == "confirmed":
                        self.import_status_var.set(f"✅ 方案：{plan['plan']['batch_no']}（已确认导入）")
                    elif plan["plan"]["status"] == "cancelled":
                        self.import_status_var.set(f"❌ 方案：{plan['plan']['batch_no']}（已取消）")
                    elif plan["plan"]["status"] == "reverted":
                        self.import_status_var.set(f"↩️ 方案：{plan['plan']['batch_no']}（已撤销）")
            else:
                self.import_status_var.set("请点击\"创建导入方案\"生成预览方案")


def main():
    root = tk.Tk()
    app = ReagentManagementApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
