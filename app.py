import tkinter as tk
from tkinter import ttk, messagebox, filedialog, simpledialog
from datetime import datetime
import os
import sys

from database import init_database, DB_PATH
from auth import AuthManager, ROLE_DISPLAY, OPERATION_TYPE_DISPLAY, STATUS_DISPLAY
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
        self.notebook.pack(fill='both', expand=True)

        self.tab_inventory = ttk.Frame(self.notebook)
        self.tab_approval = ttk.Frame(self.notebook)
        self.tab_operations = ttk.Frame(self.notebook)
        self.tab_history = ttk.Frame(self.notebook)
        self.tab_ledger = ttk.Frame(self.notebook)
        self.tab_import_export = ttk.Frame(self.notebook)

        self.notebook.add(self.tab_inventory, text='库存管理')
        self.notebook.add(self.tab_approval, text='领用审核')
        self.notebook.add(self.tab_operations, text='业务操作')
        self.notebook.add(self.tab_history, text='操作历史')
        self.notebook.add(self.tab_ledger, text='库存台账')
        self.notebook.add(self.tab_import_export, text='导入导出')

        self.setup_inventory_tab()
        self.setup_approval_tab()
        self.setup_operations_tab()
        self.setup_history_tab()
        self.setup_ledger_tab()
        self.setup_import_export_tab()

        self.notebook.bind('<<NotebookTabChanged>>', self.on_tab_changed)

        status_bar = ttk.Frame(main_frame)
        status_bar.pack(fill='x', pady=(10, 0))

        self.status_var = tk.StringVar(value="就绪")
        ttk.Label(status_bar, textvariable=self.status_var, font=('Microsoft YaHei', 9)).pack(side='left')

        db_info = f"数据库：{os.path.basename(DB_PATH)}"
        ttk.Label(status_bar, text=db_info, font=('Microsoft YaHei', 9)).pack(side='right')

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
        elif tab_text == '领用审核':
            self.refresh_approvals()
        elif tab_text == '操作历史':
            self.refresh_history()
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
        if self.auth.has_permission("return_reagent"):
            ttk.Button(btn_frame, text="归还", command=self.return_dialog).pack(side='left', padx=5)
        if self.auth.has_permission("scrap"):
            ttk.Button(btn_frame, text="报废", command=self.scrap_dialog).pack(side='left', padx=5)
        if self.auth.has_permission("stocktake"):
            ttk.Button(btn_frame, text="盘点", command=self.stocktake_dialog).pack(side='left', padx=5)

        tree_frame = ttk.Frame(frame)
        tree_frame.pack(fill='both', expand=True, padx=10, pady=10)

        columns = ("id", "name", "batch", "quantity", "unit", "expiration", "threshold",
                  "spec", "manufacturer", "storage", "is_expired", "is_low")
        self.inventory_tree = ttk.Treeview(tree_frame, columns=columns, show='headings')

        headings = [
            ("id", "ID", 50),
            ("name", "试剂名称", 150),
            ("batch", "批号", 120),
            ("quantity", "数量", 80),
            ("unit", "单位", 60),
            ("expiration", "过期日期", 100),
            ("threshold", "低库存阈值", 90),
            ("spec", "规格", 100),
            ("manufacturer", "生产厂商", 120),
            ("storage", "储存条件", 100),
            ("is_expired", "过期状态", 80),
            ("is_low", "库存状态", 80)
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
            reagents = self.manager.get_reagents(filters)

            for r in reagents:
                expired_status = "已过期" if r["is_expired"] else "正常"
                stock_status = "低库存" if r["is_low_stock"] else "正常"

                exp_date = r["expiration_date"] if r["expiration_date"] else "无"

                tags = ()
                if r["is_expired"]:
                    tags = ('expired',)
                elif r["is_low_stock"]:
                    tags = ('low_stock',)

                self.inventory_tree.insert('', 'end', iid=str(r["id"]), values=(
                    r["id"], r["name"], r["batch_number"], r["quantity"],
                    r["unit"], exp_date, r["low_stock_threshold"],
                    r["specification"] or "-", r["manufacturer"] or "-",
                    r["storage_condition"] or "-", expired_status, stock_status
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

    def setup_approval_tab(self):
        frame = self.tab_approval

        if not self.auth.has_permission("approve_use"):
            ttk.Label(frame, text="当前角色无领用审核权限", font=('Microsoft YaHei', 14), foreground='gray').pack(pady=50)
            return

        btn_frame = ttk.Frame(frame)
        btn_frame.pack(fill='x', padx=10, pady=10)

        ttk.Button(btn_frame, text="刷新", command=self.refresh_approvals).pack(side='left', padx=5)
        ttk.Button(btn_frame, text="批准", command=self.approve_selected).pack(side='left', padx=5)
        ttk.Button(btn_frame, text="拒绝", command=self.reject_selected).pack(side='left', padx=5)

        tree_frame = ttk.Frame(frame)
        tree_frame.pack(fill='both', expand=True, padx=10, pady=10)

        columns = ("id", "reagent", "batch", "apply_qty", "current_qty", "unit", "operator", "time", "remarks")
        self.approval_tree = ttk.Treeview(tree_frame, columns=columns, show='headings')

        headings = [
            ("id", "申请ID", 70),
            ("reagent", "试剂名称", 150),
            ("batch", "批号", 120),
            ("apply_qty", "申请数量", 80),
            ("current_qty", "当前库存", 80),
            ("unit", "单位", 60),
            ("operator", "申请人", 100),
            ("time", "申请时间", 150),
            ("remarks", "备注", 200)
        ]

        for col, text, width in headings:
            self.approval_tree.heading(col, text=text)
            self.approval_tree.column(col, width=width, anchor='center')

        scrollbar = ttk.Scrollbar(tree_frame, orient='vertical', command=self.approval_tree.yview)
        self.approval_tree.configure(yscrollcommand=scrollbar.set)

        self.approval_tree.pack(side='left', fill='both', expand=True)
        scrollbar.pack(side='right', fill='y')

        self.approval_tree.bind('<<TreeviewSelect>>', self.on_approval_select)

        self.refresh_approvals()

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

            ttk.Label(revert_frame, text="此操作将撤销最近一次可撤销的合规动作（入库、审核领用、归还、报废、盘点）",
                      wraplength=800).pack(pady=5)

            self.last_op_var = tk.StringVar(value="检查中...")
            ttk.Label(revert_frame, textvariable=self.last_op_var, foreground='#1976D2').pack(pady=5)

            def check_revertable():
                try:
                    from database import OperationDB
                    last = OperationDB.get_last_revertable()
                    if last:
                        op_type = OPERATION_TYPE_DISPLAY.get(last["operation_type"], last["operation_type"])
                        reagent = last.get("reagent_name", "")
                        batch = last.get("batch_number", "")
                        self.last_op_var.set(f"最近可撤销操作：#{last['id']} - {op_type} - {reagent} ({batch}) 数量：{last['quantity']}")
                    else:
                        self.last_op_var.set("没有可撤销的操作")
                except Exception:
                    self.last_op_var.set("检查失败")

            def do_revert():
                if not messagebox.askyesno("确认", "确定要撤销最近一次操作吗？"):
                    return
                try:
                    _, msg = self.manager.revert_last_operation()
                    messagebox.showinfo("成功", msg)
                    check_revertable()
                    self.refresh_inventory()
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

        ttk.Label(main_frame, text="导入库存数据", font=('Microsoft YaHei', 14, 'bold')).pack(pady=(0, 20))

        if not self.auth.has_permission("import_csv"):
            ttk.Label(main_frame, text="当前角色无 CSV 导入权限", foreground='red').pack(pady=30)
            return

        file_frame = ttk.Frame(main_frame)
        file_frame.pack(pady=20)

        ttk.Label(file_frame, text="选择 CSV 文件：").pack(side='left', padx=5)
        self.import_path_var = tk.StringVar()
        path_entry = ttk.Entry(file_frame, textvariable=self.import_path_var, width=50)
        path_entry.pack(side='left', padx=5)

        def browse_file():
            filepath = filedialog.askopenfilename(
                title="选择 CSV 文件",
                filetypes=[("CSV 文件", "*.csv"), ("所有文件", "*.*")]
            )
            if filepath:
                self.import_path_var.set(filepath)

        ttk.Button(file_frame, text="浏览...", command=browse_file).pack(side='left', padx=5)

        btn_frame = ttk.Frame(main_frame)
        btn_frame.pack(pady=20)

        def do_import():
            filepath = self.import_path_var.get().strip()
            if not filepath:
                messagebox.showwarning("提示", "请先选择 CSV 文件")
                return
            if not os.path.exists(filepath):
                messagebox.showerror("错误", "文件不存在")
                return

            if not messagebox.askyesno("确认", "导入数据会自动创建新试剂记录，确定继续吗？"):
                return

            try:
                success, skipped, errors = self.csv_manager.import_reagents(filepath)
                msg = f"导入完成！\n成功：{success} 条\n跳过：{skipped} 条"
                if errors:
                    msg += f"\n\n错误详情：\n" + "\n".join(errors[:10])
                    if len(errors) > 10:
                        msg += f"\n... 共 {len(errors)} 条错误"
                messagebox.showinfo("导入结果", msg)
                self.refresh_inventory()
                self.refresh_history()
            except ValueError as e:
                messagebox.showerror("错误", str(e))
            except Exception as e:
                messagebox.showerror("错误", f"导入失败：{str(e)}")

        ttk.Button(btn_frame, text="开始导入", command=do_import, width=15).pack(ipadx=10, ipady=10)

        info = ttk.LabelFrame(main_frame, text="CSV 格式要求", padding=15)
        info.pack(fill='x', pady=30)

        required = ["试剂名称", "批号", "数量", "单位"]
        optional = ["过期日期", "低库存阈值", "规格", "生产厂商", "储存条件", "备注"]

        ttk.Label(info, text="必填列：" + "、".join(required), foreground='red').pack(anchor='w', pady=2)
        ttk.Label(info, text="可选列：" + "、".join(optional)).pack(anchor='w', pady=2)
        ttk.Label(info, text="• 过期日期格式：YYYY-MM-DD，如 2027-12-31", wraplength=800).pack(anchor='w', pady=2)
        ttk.Label(info, text="• 数量必须是正整数", wraplength=800).pack(anchor='w', pady=2)
        ttk.Label(info, text="• 相同名称和批号的试剂不会重复导入", wraplength=800).pack(anchor='w', pady=2)
        ttk.Label(info, text="• 建议先生成样例文件查看格式", wraplength=800).pack(anchor='w', pady=2)

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


def main():
    root = tk.Tk()
    app = ReagentManagementApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
