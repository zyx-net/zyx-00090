import json
from typing import Dict, Optional, Tuple, List
from datetime import datetime

from database import ReagentDB, OperationDB, LedgerDB, UserDB
from auth import AuthManager, OPERATION_TYPE_DISPLAY


class OperationError(Exception):
    pass


class ReagentManager:
    def __init__(self, auth: AuthManager):
        self.auth = auth

    def _check_permission(self, permission: str) -> None:
        if not self.auth.has_permission(permission):
            raise OperationError(f"权限不足：当前角色无此操作权限")

    def create_reagent(self, name: str, batch_number: str, quantity: int, unit: str,
                       expiration_date: str = None, low_stock_threshold: int = 10,
                       specification: str = "", manufacturer: str = "",
                       storage_condition: str = "", remarks: str = "") -> Tuple[int, str]:
        self._check_permission("manage_reagents")

        if not name or not name.strip():
            raise OperationError("试剂名称不能为空")
        if not batch_number or not batch_number.strip():
            raise OperationError("批号不能为空")
        if quantity < 0:
            raise OperationError("数量不能为负数")
        if low_stock_threshold < 0:
            raise OperationError("低库存阈值不能为负数")

        existing = ReagentDB.get_by_name_and_batch(name.strip(), batch_number.strip())
        if existing:
            raise OperationError(f"已存在相同名称和批号的试剂：{name} - {batch_number}")

        if expiration_date:
            try:
                datetime.strptime(expiration_date, "%Y-%m-%d")
            except ValueError:
                raise OperationError("过期日期格式错误，请使用 YYYY-MM-DD 格式")

        reagent_id = ReagentDB.create(
            name.strip(), batch_number.strip(), quantity, unit,
            expiration_date, low_stock_threshold, specification,
            manufacturer, storage_condition, remarks
        )

        reagent = ReagentDB.get_by_id(reagent_id)
        snapshot_after = json.dumps(reagent, ensure_ascii=False)

        operation_id = OperationDB.create(
            operation_type="stock_in",
            reagent_id=reagent_id,
            quantity=quantity,
            operator_id=self.auth.current_user["id"],
            status="completed",
            remarks=f"新建试剂并入库 {quantity} {unit}",
            revertable=1,
            snapshot_before="",
            snapshot_after=snapshot_after
        )

        LedgerDB.create(
            reagent_id=reagent_id,
            reagent_name=name,
            batch_number=batch_number,
            operation_type="stock_in",
            change_quantity=quantity,
            balance_quantity=quantity,
            operator=self.auth.current_user["display_name"],
            remarks="新建试剂入库"
        )

        return reagent_id, f"试剂创建成功，已自动入库 {quantity} {unit}"

    def stock_in(self, reagent_id: int, quantity: int, remarks: str = "") -> Tuple[int, str]:
        self._check_permission("stock_in")

        if quantity <= 0:
            raise OperationError("入库数量必须大于0")

        reagent = ReagentDB.get_by_id(reagent_id)
        if not reagent:
            raise OperationError("试剂不存在")

        snapshot_before = json.dumps(reagent, ensure_ascii=False)

        if not ReagentDB.update_quantity(reagent_id, quantity):
            raise OperationError("入库失败，数据库更新错误")

        reagent_after = ReagentDB.get_by_id(reagent_id)
        snapshot_after = json.dumps(reagent_after, ensure_ascii=False)

        operation_id = OperationDB.create(
            operation_type="stock_in",
            reagent_id=reagent_id,
            quantity=quantity,
            operator_id=self.auth.current_user["id"],
            status="completed",
            remarks=remarks,
            revertable=1,
            snapshot_before=snapshot_before,
            snapshot_after=snapshot_after
        )

        LedgerDB.create(
            reagent_id=reagent_id,
            reagent_name=reagent["name"],
            batch_number=reagent["batch_number"],
            operation_type="stock_in",
            change_quantity=quantity,
            balance_quantity=reagent_after["quantity"],
            operator=self.auth.current_user["display_name"],
            remarks=remarks
        )

        return operation_id, f"入库成功：{reagent['name']} ({reagent['batch_number']}) +{quantity} {reagent['unit']}"

    def apply_use(self, reagent_id: int, quantity: int, remarks: str = "") -> Tuple[int, str]:
        self._check_permission("apply_use")

        if quantity <= 0:
            raise OperationError("领用数量必须大于0")

        reagent = ReagentDB.get_by_id(reagent_id)
        if not reagent:
            raise OperationError("试剂不存在")

        if ReagentDB.is_expired(reagent_id):
            raise OperationError(f"试剂已过期（过期日期：{reagent['expiration_date']}），禁止领用")

        if reagent["quantity"] < quantity:
            raise OperationError(f"库存不足，当前库存：{reagent['quantity']} {reagent['unit']}")

        operation_id = OperationDB.create(
            operation_type="apply_use",
            reagent_id=reagent_id,
            quantity=quantity,
            operator_id=self.auth.current_user["id"],
            status="pending",
            remarks=remarks,
            revertable=0
        )

        return operation_id, f"领用申请已提交，等待审核：{reagent['name']} ({reagent['batch_number']}) -{quantity} {reagent['unit']}"

    def approve_use(self, operation_id: int, remarks: str = "") -> Tuple[int, str]:
        self._check_permission("approve_use")

        operation = OperationDB.get_by_id(operation_id)
        if not operation:
            raise OperationError("操作记录不存在")

        if operation["operation_type"] != "apply_use":
            raise OperationError("只能审核领用申请")

        if operation["status"] != "pending":
            raise OperationError(f"当前状态为 {operation['status']}，无法审核")

        reagent = ReagentDB.get_by_id(operation["reagent_id"])
        if not reagent:
            raise OperationError("试剂不存在")

        if ReagentDB.is_expired(operation["reagent_id"]):
            raise OperationError(f"试剂已过期（过期日期：{reagent['expiration_date']}），禁止通过审核")

        if reagent["quantity"] < operation["quantity"]:
            raise OperationError(f"库存不足，当前库存：{reagent['quantity']} {reagent['unit']}")

        snapshot_before = json.dumps(reagent, ensure_ascii=False)

        if not ReagentDB.update_quantity(operation["reagent_id"], -operation["quantity"]):
            raise OperationError("审核失败，库存更新错误")

        reagent_after = ReagentDB.get_by_id(operation["reagent_id"])
        snapshot_after = json.dumps(reagent_after, ensure_ascii=False)

        OperationDB.update_status(
            operation_id, "approved",
            reviewer_id=self.auth.current_user["id"],
            remarks=remarks
        )

        approve_op_id = OperationDB.create(
            operation_type="approve_use",
            reagent_id=operation["reagent_id"],
            quantity=operation["quantity"],
            operator_id=self.auth.current_user["id"],
            status="completed",
            remarks=remarks,
            revertable=1,
            snapshot_before=snapshot_before,
            snapshot_after=snapshot_after
        )

        operator = UserDB.get_by_id(operation["operator_id"])
        operator_name = operator["display_name"] if operator else "未知"

        LedgerDB.create(
            reagent_id=operation["reagent_id"],
            reagent_name=reagent["name"],
            batch_number=reagent["batch_number"],
            operation_type="approve_use",
            change_quantity=-operation["quantity"],
            balance_quantity=reagent_after["quantity"],
            operator=operator_name,
            reviewer=self.auth.current_user["display_name"],
            remarks=remarks
        )

        return approve_op_id, f"审核通过：{reagent['name']} ({reagent['batch_number']}) -{operation['quantity']} {reagent['unit']}"

    def reject_use(self, operation_id: int, remarks: str = "") -> Tuple[int, str]:
        self._check_permission("reject_use")

        operation = OperationDB.get_by_id(operation_id)
        if not operation:
            raise OperationError("操作记录不存在")

        if operation["operation_type"] != "apply_use":
            raise OperationError("只能拒绝领用申请")

        if operation["status"] != "pending":
            raise OperationError(f"当前状态为 {operation['status']}，无法拒绝")

        OperationDB.update_status(
            operation_id, "rejected",
            reviewer_id=self.auth.current_user["id"],
            remarks=remarks
        )

        OperationDB.create(
            operation_type="reject_use",
            reagent_id=operation["reagent_id"],
            quantity=operation["quantity"],
            operator_id=self.auth.current_user["id"],
            status="completed",
            remarks=remarks,
            revertable=0
        )

        return operation_id, f"已拒绝领用申请"

    def return_reagent(self, reagent_id: int, quantity: int, remarks: str = "") -> Tuple[int, str]:
        self._check_permission("return_reagent")

        if quantity <= 0:
            raise OperationError("归还数量必须大于0")

        reagent = ReagentDB.get_by_id(reagent_id)
        if not reagent:
            raise OperationError("试剂不存在")

        if ReagentDB.is_expired(reagent_id):
            raise OperationError(f"试剂已过期（过期日期：{reagent['expiration_date']}），请走报废流程")

        snapshot_before = json.dumps(reagent, ensure_ascii=False)

        if not ReagentDB.update_quantity(reagent_id, quantity):
            raise OperationError("归还失败，数据库更新错误")

        reagent_after = ReagentDB.get_by_id(reagent_id)
        snapshot_after = json.dumps(reagent_after, ensure_ascii=False)

        operation_id = OperationDB.create(
            operation_type="return",
            reagent_id=reagent_id,
            quantity=quantity,
            operator_id=self.auth.current_user["id"],
            status="completed",
            remarks=remarks,
            revertable=1,
            snapshot_before=snapshot_before,
            snapshot_after=snapshot_after
        )

        LedgerDB.create(
            reagent_id=reagent_id,
            reagent_name=reagent["name"],
            batch_number=reagent["batch_number"],
            operation_type="return",
            change_quantity=quantity,
            balance_quantity=reagent_after["quantity"],
            operator=self.auth.current_user["display_name"],
            remarks=remarks
        )

        return operation_id, f"归还成功：{reagent['name']} ({reagent['batch_number']}) +{quantity} {reagent['unit']}"

    def scrap(self, reagent_id: int, quantity: int, remarks: str = "") -> Tuple[int, str]:
        self._check_permission("scrap")

        if quantity <= 0:
            raise OperationError("报废数量必须大于0")

        reagent = ReagentDB.get_by_id(reagent_id)
        if not reagent:
            raise OperationError("试剂不存在")

        if reagent["quantity"] < quantity:
            raise OperationError(f"库存不足，当前库存：{reagent['quantity']} {reagent['unit']}")

        snapshot_before = json.dumps(reagent, ensure_ascii=False)

        if not ReagentDB.update_quantity(reagent_id, -quantity):
            raise OperationError("报废失败，数据库更新错误")

        reagent_after = ReagentDB.get_by_id(reagent_id)
        snapshot_after = json.dumps(reagent_after, ensure_ascii=False)

        operation_id = OperationDB.create(
            operation_type="scrap",
            reagent_id=reagent_id,
            quantity=quantity,
            operator_id=self.auth.current_user["id"],
            status="completed",
            remarks=remarks,
            revertable=1,
            snapshot_before=snapshot_before,
            snapshot_after=snapshot_after
        )

        LedgerDB.create(
            reagent_id=reagent_id,
            reagent_name=reagent["name"],
            batch_number=reagent["batch_number"],
            operation_type="scrap",
            change_quantity=-quantity,
            balance_quantity=reagent_after["quantity"],
            operator=self.auth.current_user["display_name"],
            remarks=remarks
        )

        return operation_id, f"报废成功：{reagent['name']} ({reagent['batch_number']}) -{quantity} {reagent['unit']}"

    def stocktake(self, reagent_id: int, actual_quantity: int, remarks: str = "") -> Tuple[int, str]:
        self._check_permission("stocktake")

        if actual_quantity < 0:
            raise OperationError("实际数量不能为负数")

        reagent = ReagentDB.get_by_id(reagent_id)
        if not reagent:
            raise OperationError("试剂不存在")

        quantity_diff = actual_quantity - reagent["quantity"]

        if quantity_diff == 0:
            return 0, f"盘点无差异：{reagent['name']} ({reagent['batch_number']}) 数量正确"

        snapshot_before = json.dumps(reagent, ensure_ascii=False)

        if not ReagentDB.update_quantity(reagent_id, quantity_diff):
            raise OperationError("盘点调整失败，数据库更新错误")

        reagent_after = ReagentDB.get_by_id(reagent_id)
        snapshot_after = json.dumps(reagent_after, ensure_ascii=False)

        operation_id = OperationDB.create(
            operation_type="stocktake",
            reagent_id=reagent_id,
            quantity=quantity_diff,
            operator_id=self.auth.current_user["id"],
            status="completed",
            remarks=remarks,
            revertable=1,
            snapshot_before=snapshot_before,
            snapshot_after=snapshot_after
        )

        diff_str = f"+{quantity_diff}" if quantity_diff > 0 else str(quantity_diff)

        LedgerDB.create(
            reagent_id=reagent_id,
            reagent_name=reagent["name"],
            batch_number=reagent["batch_number"],
            operation_type="stocktake",
            change_quantity=quantity_diff,
            balance_quantity=reagent_after["quantity"],
            operator=self.auth.current_user["display_name"],
            remarks=f"盘点调整，系统库存：{reagent['quantity']}，实际：{actual_quantity}，差异：{diff_str}。{remarks}"
        )

        return operation_id, f"盘点调整成功：{reagent['name']} ({reagent['batch_number']}) {diff_str} {reagent['unit']}，当前库存：{actual_quantity}"

    def revert_last_operation(self) -> Tuple[int, str]:
        self._check_permission("revert_operation")

        last_op = OperationDB.get_last_revertable()
        if not last_op:
            raise OperationError("没有可撤销的操作记录")

        if not last_op.get("revertable"):
            raise OperationError("该操作不可撤销")

        if last_op["operation_type"] not in ["stock_in", "approve_use", "return", "scrap", "stocktake"]:
            raise OperationError("该类型操作不可撤销")

        reagent_id = last_op["reagent_id"]
        quantity = last_op["quantity"]

        reverse_quantity = 0
        if last_op["operation_type"] in ["stock_in", "return"]:
            reverse_quantity = -quantity
        elif last_op["operation_type"] in ["approve_use", "scrap"]:
            reverse_quantity = quantity
        elif last_op["operation_type"] == "stocktake":
            reverse_quantity = -quantity

        reagent = ReagentDB.get_by_id(reagent_id)
        if not reagent:
            raise OperationError("关联试剂不存在，无法撤销")

        if reagent["quantity"] + reverse_quantity < 0:
            raise OperationError(f"撤销后库存将为负数（当前库存：{reagent['quantity']}，需要调整：{reverse_quantity}），无法撤销")

        if not ReagentDB.update_quantity(reagent_id, reverse_quantity):
            raise OperationError("撤销失败，数据库更新错误")

        OperationDB.mark_reverted(last_op["id"])

        reagent_after = ReagentDB.get_by_id(reagent_id)

        LedgerDB.create(
            reagent_id=reagent_id,
            reagent_name=reagent["name"],
            batch_number=reagent["batch_number"],
            operation_type="stocktake",
            change_quantity=reverse_quantity,
            balance_quantity=reagent_after["quantity"],
            operator=self.auth.current_user["display_name"],
            remarks=f"撤销操作 #{last_op['id']}（{OPERATION_TYPE_DISPLAY.get(last_op['operation_type'], last_op['operation_type'])}）"
        )

        op_type_display = OPERATION_TYPE_DISPLAY.get(last_op["operation_type"], last_op["operation_type"])
        return last_op["id"], f"已撤销操作 #{last_op['id']}（{op_type_display}），库存已恢复"

    def get_reagents(self, filters: Dict = None) -> List[Dict]:
        self._check_permission("view_inventory")
        reagents = ReagentDB.get_all(filters)
        for r in reagents:
            r["is_expired"] = ReagentDB.is_expired(r["id"])
            r["is_low_stock"] = r["quantity"] <= r["low_stock_threshold"]
        return reagents

    def get_pending_approvals(self) -> List[Dict]:
        self._check_permission("approve_use")
        return OperationDB.get_pending_approvals()

    def get_operation_history(self, limit: int = 100) -> List[Dict]:
        self._check_permission("view_history")
        return OperationDB.get_all(limit)

    def get_ledger(self, filters: Dict = None) -> List[Dict]:
        self._check_permission("view_ledger")
        return LedgerDB.get_all(filters)

    def update_reagent_info(self, reagent_id: int, **kwargs) -> Tuple[bool, str]:
        self._check_permission("manage_reagents")
        success = ReagentDB.update(reagent_id, **kwargs)
        if success:
            return True, "试剂信息更新成功"
        return False, "试剂信息更新失败"
