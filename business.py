import json
from typing import Dict, Optional, Tuple, List
from datetime import datetime

from database import (ReagentDB, OperationDB, LedgerDB, UserDB,
                      ReservationDB, ReservationLogDB, ReagentLockDB,
                      StocktakeOrderDB, StocktakeItemDB, StocktakeLogDB)
from auth import AuthManager, OPERATION_TYPE_DISPLAY, RESERVATION_OPERATION_DISPLAY


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

    def create_reservation(self, reagent_id: int, quantity: int,
                           planned_use_date: str, remarks: str = "") -> Tuple[int, str]:
        self._check_permission("create_reservation")

        if quantity <= 0:
            raise OperationError("预约数量必须大于0")

        reagent = ReagentDB.get_by_id(reagent_id)
        if not reagent:
            raise OperationError("试剂不存在")

        if ReagentDB.is_expired(reagent_id):
            raise OperationError(f"试剂已过期（过期日期：{reagent['expiration_date']}），禁止预约")

        available_qty = ReagentLockDB.get_available_quantity(reagent_id)
        if available_qty < quantity:
            raise OperationError(
                f"可用库存不足。当前库存：{reagent['quantity']}，"
                f"已锁定：{reagent.get('locked_quantity', 0)}，"
                f"可用：{available_qty}，需要：{quantity}"
            )

        try:
            datetime.strptime(planned_use_date, "%Y-%m-%d")
        except ValueError:
            raise OperationError("计划使用日期格式错误，请使用 YYYY-MM-DD 格式")

        if planned_use_date < datetime.now().strftime("%Y-%m-%d"):
            raise OperationError("计划使用日期不能早于今天")

        reservation_id = ReservationDB.create(
            reagent_id=reagent_id,
            reagent_name=reagent["name"],
            batch_number=reagent["batch_number"],
            quantity=quantity,
            planned_use_date=planned_use_date,
            operator_id=self.auth.current_user["id"],
            remarks=remarks
        )

        ReservationLogDB.create(
            operation_type="create",
            reservation_id=reservation_id,
            reagent_id=reagent_id,
            reagent_name=reagent["name"],
            batch_number=reagent["batch_number"],
            quantity=quantity,
            operator_id=self.auth.current_user["id"],
            operator_name=self.auth.current_user["display_name"],
            status_before=None,
            status_after="pending",
            remarks=remarks,
            revertable=0
        )

        return reservation_id, (
            f"预约已提交，等待审核：{reagent['name']} ({reagent['batch_number']}) "
            f"{quantity} {reagent['unit']}，计划使用日期：{planned_use_date}"
        )

    def approve_reservation(self, reservation_id: int,
                            review_remarks: str = "") -> Tuple[int, str]:
        self._check_permission("approve_reservation")

        reservation = ReservationDB.get_by_id(reservation_id)
        if not reservation:
            raise OperationError("预约记录不存在")

        if reservation["status"] != "pending":
            raise OperationError(
                f"当前状态为「{reservation['status']}」，无法审批"
            )

        reagent = ReagentDB.get_by_id(reservation["reagent_id"])
        if not reagent:
            raise OperationError("关联试剂不存在")

        if ReagentDB.is_expired(reservation["reagent_id"]):
            raise OperationError(
                f"试剂已过期（过期日期：{reagent['expiration_date']}），禁止通过审批"
            )

        available_qty = ReagentLockDB.get_available_quantity(reservation["reagent_id"])
        if available_qty < reservation["quantity"]:
            raise OperationError(
                f"可用库存不足。当前库存：{reagent['quantity']}，"
                f"已锁定：{reagent.get('locked_quantity', 0)}，"
                f"可用：{available_qty}，需要：{reservation['quantity']}"
            )

        snapshot_before = json.dumps(reagent, ensure_ascii=False)

        if not ReagentLockDB.update_locked_quantity(
            reservation["reagent_id"], reservation["quantity"]
        ):
            raise OperationError("审批失败，库存锁定更新错误")

        reagent_after = ReagentDB.get_by_id(reservation["reagent_id"])
        snapshot_after = json.dumps(reagent_after, ensure_ascii=False)

        ReservationDB.update_status(
            reservation_id, "approved",
            reviewer_id=self.auth.current_user["id"],
            review_remarks=review_remarks
        )

        log_id = ReservationLogDB.create(
            operation_type="approve",
            reservation_id=reservation_id,
            reagent_id=reservation["reagent_id"],
            reagent_name=reservation["reagent_name"],
            batch_number=reservation["batch_number"],
            quantity=reservation["quantity"],
            operator_id=reservation["operator_id"],
            operator_name=reservation.get("operator_name", ""),
            reviewer_id=self.auth.current_user["id"],
            reviewer_name=self.auth.current_user["display_name"],
            status_before="pending",
            status_after="approved",
            locked_qty_change=reservation["quantity"],
            remarks=review_remarks,
            revertable=1,
            snapshot_before=snapshot_before,
            snapshot_after=snapshot_after
        )

        return log_id, (
            f"审批通过，已锁定库存：{reservation['reagent_name']} "
            f"({reservation['batch_number']}) {reservation['quantity']} "
            f"{reagent.get('unit', '')}"
        )

    def reject_reservation(self, reservation_id: int,
                           review_remarks: str = "") -> Tuple[int, str]:
        self._check_permission("reject_reservation")

        reservation = ReservationDB.get_by_id(reservation_id)
        if not reservation:
            raise OperationError("预约记录不存在")

        if reservation["status"] != "pending":
            raise OperationError(
                f"当前状态为「{reservation['status']}」，无法拒绝"
            )

        ReservationDB.update_status(
            reservation_id, "rejected",
            reviewer_id=self.auth.current_user["id"],
            review_remarks=review_remarks
        )

        log_id = ReservationLogDB.create(
            operation_type="reject",
            reservation_id=reservation_id,
            reagent_id=reservation["reagent_id"],
            reagent_name=reservation["reagent_name"],
            batch_number=reservation["batch_number"],
            quantity=reservation["quantity"],
            operator_id=reservation["operator_id"],
            operator_name=reservation.get("operator_name", ""),
            reviewer_id=self.auth.current_user["id"],
            reviewer_name=self.auth.current_user["display_name"],
            status_before="pending",
            status_after="rejected",
            remarks=review_remarks,
            revertable=0
        )

        return log_id, f"已拒绝预约申请：{review_remarks}"

    def reschedule_reservation(self, reservation_id: int,
                               new_planned_date: str,
                               review_remarks: str = "") -> Tuple[int, str]:
        self._check_permission("reschedule_reservation")

        reservation = ReservationDB.get_by_id(reservation_id)
        if not reservation:
            raise OperationError("预约记录不存在")

        if reservation["status"] not in ["pending", "approved"]:
            raise OperationError(
                f"当前状态为「{reservation['status']}」，无法改期"
            )

        try:
            datetime.strptime(new_planned_date, "%Y-%m-%d")
        except ValueError:
            raise OperationError("新计划使用日期格式错误，请使用 YYYY-MM-DD 格式")

        if new_planned_date < datetime.now().strftime("%Y-%m-%d"):
            raise OperationError("新计划使用日期不能早于今天")

        old_date = reservation["planned_use_date"]
        qty = reservation["quantity"]
        reagent_id = reservation["reagent_id"]

        if reservation["status"] == "approved":
            reagent_before = ReagentDB.get_by_id(reagent_id)
            snapshot_before_release = json.dumps(reagent_before, ensure_ascii=False)
            if not ReagentLockDB.update_locked_quantity(reagent_id, -qty):
                raise OperationError("释放原预约锁定量失败")
            reagent_after_release = ReagentDB.get_by_id(reagent_id)
            snapshot_after_release = json.dumps(reagent_after_release, ensure_ascii=False)

            ReservationLogDB.create(
                operation_type="reschedule_release",
                reservation_id=reservation_id,
                reagent_id=reagent_id,
                reagent_name=reservation["reagent_name"],
                batch_number=reservation["batch_number"],
                quantity=qty,
                operator_id=reservation["operator_id"],
                operator_name=reservation.get("operator_name", ""),
                reviewer_id=self.auth.current_user["id"],
                reviewer_name=self.auth.current_user["display_name"],
                status_before="approved",
                status_after="rescheduled",
                locked_qty_change=-qty,
                remarks=f"改期释放原锁定量，原日期：{old_date}",
                revertable=0,
                snapshot_before=snapshot_before_release,
                snapshot_after=snapshot_after_release
            )

        ReservationDB.update_status(
            reservation_id, "rescheduled",
            reviewer_id=self.auth.current_user["id"],
            review_remarks=review_remarks,
            planned_use_date=new_planned_date
        )

        new_reservation_id = ReservationDB.create(
            reagent_id=reagent_id,
            reagent_name=reservation["reagent_name"],
            batch_number=reservation["batch_number"],
            quantity=qty,
            planned_use_date=new_planned_date,
            operator_id=reservation["operator_id"],
            remarks=f"由预约#{reservation_id}改期而来，原日期：{old_date}",
            original_planned_date=old_date
        )

        if reservation["status"] == "approved":
            reagent_before_approve = ReagentDB.get_by_id(reagent_id)
            snapshot_before_approve = json.dumps(reagent_before_approve, ensure_ascii=False)
            if not ReagentLockDB.update_locked_quantity(reagent_id, qty):
                raise OperationError("锁定新预约库存失败")
            reagent_after_approve = ReagentDB.get_by_id(reagent_id)
            snapshot_after_approve = json.dumps(reagent_after_approve, ensure_ascii=False)

            ReservationDB.update_status(
                new_reservation_id, "approved",
                reviewer_id=self.auth.current_user["id"],
                review_remarks=f"改期自动审批，原预约#{reservation_id}"
            )

            ReservationLogDB.create(
                operation_type="approve",
                reservation_id=new_reservation_id,
                reagent_id=reagent_id,
                reagent_name=reservation["reagent_name"],
                batch_number=reservation["batch_number"],
                quantity=qty,
                operator_id=reservation["operator_id"],
                operator_name=reservation.get("operator_name", ""),
                reviewer_id=self.auth.current_user["id"],
                reviewer_name=self.auth.current_user["display_name"],
                status_before="pending",
                status_after="approved",
                locked_qty_change=qty,
                remarks=f"改期自动审批，原预约#{reservation_id}",
                revertable=1,
                snapshot_before=snapshot_before_approve,
                snapshot_after=snapshot_after_approve
            )

        log_id = ReservationLogDB.create(
            operation_type="reschedule",
            reservation_id=reservation_id,
            reagent_id=reservation["reagent_id"],
            reagent_name=reservation["reagent_name"],
            batch_number=reservation["batch_number"],
            quantity=reservation["quantity"],
            operator_id=reservation["operator_id"],
            operator_name=reservation.get("operator_name", ""),
            reviewer_id=self.auth.current_user["id"],
            reviewer_name=self.auth.current_user["display_name"],
            status_before=reservation["status"],
            status_after="rescheduled",
            remarks=f"改期：{old_date} → {new_planned_date}。{review_remarks}",
            revertable=0
        )

        return log_id, (
            f"改期成功：{old_date} → {new_planned_date}，"
            f"新预约ID：#{new_reservation_id}"
        )

    def cancel_reservation(self, reservation_id: int,
                           remarks: str = "") -> Tuple[int, str]:
        self._check_permission("cancel_reservation")

        reservation = ReservationDB.get_by_id(reservation_id)
        if not reservation:
            raise OperationError("预约记录不存在")

        if reservation["status"] not in ["pending", "approved"]:
            raise OperationError(
                f"当前状态为「{reservation['status']}」，无法取消"
            )

        if (reservation["operator_id"] != self.auth.current_user["id"]
                and not self.auth.has_permission("approve_reservation")):
            raise OperationError("只能取消自己创建的预约，或需要管理员权限")

        reagent = ReagentDB.get_by_id(reservation["reagent_id"])
        snapshot_before = json.dumps(reagent, ensure_ascii=False) if reagent else ""

        locked_change = 0
        if reservation["status"] == "approved":
            if not ReagentLockDB.update_locked_quantity(
                reservation["reagent_id"], -reservation["quantity"]
            ):
                raise OperationError("取消失败，库存锁定释放错误")
            locked_change = -reservation["quantity"]

        reagent_after = ReagentDB.get_by_id(reservation["reagent_id"])
        snapshot_after = json.dumps(reagent_after, ensure_ascii=False) if reagent_after else ""

        ReservationDB.update_status(
            reservation_id, "cancelled",
            review_remarks=remarks
        )

        log_id = ReservationLogDB.create(
            operation_type="cancel",
            reservation_id=reservation_id,
            reagent_id=reservation["reagent_id"],
            reagent_name=reservation["reagent_name"],
            batch_number=reservation["batch_number"],
            quantity=reservation["quantity"],
            operator_id=reservation["operator_id"],
            operator_name=reservation.get("operator_name", ""),
            reviewer_id=self.auth.current_user["id"],
            reviewer_name=self.auth.current_user["display_name"],
            status_before=reservation["status"],
            status_after="cancelled",
            locked_qty_change=locked_change,
            remarks=remarks,
            revertable=1 if reservation["status"] == "approved" else 0,
            snapshot_before=snapshot_before,
            snapshot_after=snapshot_after
        )

        return log_id, f"预约已取消，已释放锁定库存 {reservation['quantity']} 单位"

    def complete_reservation(self, reservation_id: int,
                             remarks: str = "") -> Tuple[int, str]:
        self._check_permission("complete_reservation")

        reservation = ReservationDB.get_by_id(reservation_id)
        if not reservation:
            raise OperationError("预约记录不存在")

        if reservation["status"] != "approved":
            raise OperationError(
                f"当前状态为「{reservation['status']}」，只有已审批的预约可以领用"
            )

        reagent = ReagentDB.get_by_id(reservation["reagent_id"])
        if not reagent:
            raise OperationError("关联试剂不存在")

        if ReagentDB.is_expired(reservation["reagent_id"]):
            raise OperationError(
                f"试剂已过期（过期日期：{reagent['expiration_date']}），禁止领用"
            )

        if reagent["quantity"] < reservation["quantity"]:
            raise OperationError(
                f"库存不足。当前库存：{reagent['quantity']}，需要：{reservation['quantity']}"
            )

        snapshot_before = json.dumps(reagent, ensure_ascii=False)

        if not ReagentLockDB.update_locked_quantity(
            reservation["reagent_id"], -reservation["quantity"]
        ):
            raise OperationError("领用失败，库存锁定释放错误")

        if not ReagentDB.update_quantity(
            reservation["reagent_id"], -reservation["quantity"]
        ):
            raise OperationError("领用失败，库存扣减错误")

        reagent_after = ReagentDB.get_by_id(reservation["reagent_id"])
        snapshot_after = json.dumps(reagent_after, ensure_ascii=False)

        ReservationDB.update_status(
            reservation_id, "completed",
            review_remarks=remarks
        )

        log_id = ReservationLogDB.create(
            operation_type="complete",
            reservation_id=reservation_id,
            reagent_id=reservation["reagent_id"],
            reagent_name=reservation["reagent_name"],
            batch_number=reservation["batch_number"],
            quantity=reservation["quantity"],
            operator_id=reservation["operator_id"],
            operator_name=reservation.get("operator_name", ""),
            reviewer_id=self.auth.current_user["id"],
            reviewer_name=self.auth.current_user["display_name"],
            status_before="approved",
            status_after="completed",
            locked_qty_change=-reservation["quantity"],
            stock_qty_change=-reservation["quantity"],
            remarks=remarks,
            revertable=1,
            snapshot_before=snapshot_before,
            snapshot_after=snapshot_after
        )

        operator = UserDB.get_by_id(reservation["operator_id"])
        operator_name = operator["display_name"] if operator else "未知"

        LedgerDB.create(
            reagent_id=reservation["reagent_id"],
            reagent_name=reservation["reagent_name"],
            batch_number=reservation["batch_number"],
            operation_type="approve_use",
            change_quantity=-reservation["quantity"],
            balance_quantity=reagent_after["quantity"],
            operator=operator_name,
            reviewer=self.auth.current_user["display_name"],
            remarks=f"预约领用 #{reservation_id}。{remarks}"
        )

        return log_id, (
            f"领用完成：{reservation['reagent_name']} "
            f"({reservation['batch_number']}) -{reservation['quantity']} "
            f"{reagent['unit']}"
        )

    def release_expired_reservations(self) -> Tuple[int, List[str]]:
        self._check_permission("release_expired_reservations")

        expired = ReservationDB.get_expired_reservations()
        released_count = 0
        messages = []

        for reservation in expired:
            try:
                reagent = ReagentDB.get_by_id(reservation["reagent_id"])
                snapshot_before = json.dumps(reagent, ensure_ascii=False) if reagent else ""

                if not ReagentLockDB.update_locked_quantity(
                    reservation["reagent_id"], -reservation["quantity"]
                ):
                    messages.append(
                        f"预约#{reservation['id']} 释放锁定失败，跳过"
                    )
                    continue

                reagent_after = ReagentDB.get_by_id(reservation["reagent_id"])
                snapshot_after = json.dumps(reagent_after, ensure_ascii=False) if reagent_after else ""

                ReservationDB.update_status(
                    reservation["id"], "expired",
                    review_remarks=f"系统自动过期释放，原计划日期：{reservation['planned_use_date']}"
                )

                ReservationLogDB.create(
                    operation_type="expire_release",
                    reservation_id=reservation["id"],
                    reagent_id=reservation["reagent_id"],
                    reagent_name=reservation["reagent_name"],
                    batch_number=reservation["batch_number"],
                    quantity=reservation["quantity"],
                    operator_id=reservation["operator_id"],
                    operator_name=reservation.get("operator_name", ""),
                    reviewer_id=self.auth.current_user["id"],
                    reviewer_name=self.auth.current_user["display_name"],
                    status_before="approved",
                    status_after="expired",
                    locked_qty_change=-reservation["quantity"],
                    remarks=f"计划使用日期 {reservation['planned_use_date']} 已过期，系统自动释放锁定",
                    revertable=0,
                    snapshot_before=snapshot_before,
                    snapshot_after=snapshot_after
                )

                released_count += 1
                messages.append(
                    f"预约#{reservation['id']} 已过期释放：{reservation['reagent_name']} "
                    f"{reservation['quantity']} 单位"
                )
            except Exception as e:
                messages.append(
                    f"预约#{reservation['id']} 处理失败：{str(e)}"
                )

        return released_count, messages

    def get_reservations(self, filters: Dict = None) -> List[Dict]:
        self._check_permission("view_reservations")
        return ReservationDB.get_all(filters)

    def get_reservation_by_id(self, reservation_id: int) -> Optional[Dict]:
        self._check_permission("view_reservations")
        return ReservationDB.get_by_id(reservation_id)

    def get_pending_reservations(self) -> List[Dict]:
        self._check_permission("approve_reservation")
        return ReservationDB.get_pending_approvals()

    def get_reservation_logs(self, filters: Dict = None) -> List[Dict]:
        self._check_permission("view_reservation_logs")
        return ReservationLogDB.get_all(filters)

    def get_reagents_with_lock_info(self, filters: Dict = None) -> List[Dict]:
        self._check_permission("view_inventory")
        reagents = ReagentDB.get_all(filters)
        for r in reagents:
            r["is_expired"] = ReagentDB.is_expired(r["id"])
            r["is_low_stock"] = r["quantity"] <= r["low_stock_threshold"]
            r["locked_quantity"] = r.get("locked_quantity", 0)
            r["available_quantity"] = r["quantity"] - r["locked_quantity"]
            r["reservation_summary"] = ReservationDB.get_reservation_summary_for_reagent(r["id"])
        return reagents

    def revert_last_reservation_operation(self) -> Tuple[int, str]:
        self._check_permission("revert_operation")

        last_log = ReservationLogDB.get_last_revertable()
        if not last_log:
            raise OperationError("没有可撤销的预约操作记录")

        reservation = ReservationDB.get_by_id(last_log["reservation_id"])
        if not reservation:
            raise OperationError("关联预约记录不存在，无法撤销")

        op_type = last_log["operation_type"]
        if op_type == "approve":
            if reservation["status"] != "approved":
                raise OperationError(
                    f"预约当前状态为「{reservation['status']}」，无法撤销审批"
                )

            reagent = ReagentDB.get_by_id(last_log["reagent_id"])
            if not reagent:
                raise OperationError("关联试剂不存在，无法撤销")

            if not ReagentLockDB.update_locked_quantity(
                last_log["reagent_id"], -last_log["quantity"]
            ):
                raise OperationError("撤销失败，库存锁定释放错误")

            ReservationDB.update_status(
                last_log["reservation_id"], "pending",
                review_remarks=f"撤销审批操作 #{last_log['id']}"
            )

        elif op_type == "cancel":
            if reservation["status"] != "cancelled":
                raise OperationError(
                    f"预约当前状态为「{reservation['status']}」，无法撤销取消"
                )

            reagent = ReagentDB.get_by_id(last_log["reagent_id"])
            if not reagent:
                raise OperationError("关联试剂不存在，无法撤销")

            if not ReagentLockDB.update_locked_quantity(
                last_log["reagent_id"], last_log["quantity"]
            ):
                raise OperationError("撤销失败，库存锁定恢复错误")

            ReservationDB.update_status(
                last_log["reservation_id"], "approved",
                review_remarks=f"撤销取消操作 #{last_log['id']}"
            )

        elif op_type == "complete":
            if reservation["status"] != "completed":
                raise OperationError(
                    f"预约当前状态为「{reservation['status']}」，无法撤销领用"
                )

            reagent = ReagentDB.get_by_id(last_log["reagent_id"])
            if not reagent:
                raise OperationError("关联试剂不存在，无法撤销")

            if not ReagentLockDB.update_locked_quantity(
                last_log["reagent_id"], last_log["quantity"]
            ):
                raise OperationError("撤销失败，库存锁定恢复错误")

            if not ReagentDB.update_quantity(
                last_log["reagent_id"], last_log["quantity"]
            ):
                raise OperationError("撤销失败，库存恢复错误")

            ReservationDB.update_status(
                last_log["reservation_id"], "approved",
                review_remarks=f"撤销领用操作 #{last_log['id']}"
            )

            LedgerDB.create(
                reagent_id=last_log["reagent_id"],
                reagent_name=last_log["reagent_name"],
                batch_number=last_log["batch_number"],
                operation_type="stocktake",
                change_quantity=last_log["quantity"],
                balance_quantity=reagent["quantity"] + last_log["quantity"],
                operator=self.auth.current_user["display_name"],
                remarks=f"撤销预约领用 #{last_log['reservation_id']}"
            )

        else:
            raise OperationError(f"该类型操作（{op_type}）不可撤销")

        ReservationLogDB.mark_reverted(last_log["id"])

        op_display = RESERVATION_OPERATION_DISPLAY.get(op_type, op_type)
        return last_log["id"], f"已撤销预约操作 #{last_log['id']}（{op_display}）"

    def get_last_revertable_reservation_log(self) -> Optional[Dict]:
        self._check_permission("revert_operation")
        return ReservationLogDB.get_last_revertable()


class StocktakeManager:
    def __init__(self, auth: AuthManager):
        self.auth = auth

    def _check_permission(self, permission: str) -> None:
        if not self.auth.has_permission(permission):
            raise OperationError(f"权限不足：当前角色无此操作权限")

    def create_order(self, title: str, storage_location: str = "",
                   remarks: str = "",
                   auto_fill_from_inventory: bool = False) -> Tuple[int, str]:
        self._check_permission("create_stocktake_order")

        if not title or not title.strip():
            raise OperationError("盘点单标题不能为空")

        order_id = StocktakeOrderDB.create(
            title=title.strip(),
            operator_id=self.auth.current_user["id"],
            operator_name=self.auth.current_user["display_name"],
            storage_location=storage_location.strip(),
            remarks=remarks.strip()
        )

        StocktakeLogDB.create(
            operator_id=self.auth.current_user["id"],
            operator_name=self.auth.current_user["display_name"],
            operation_type="create_order",
            order_id=order_id,
            remarks=f"创建盘点单：{title}"
        )

        if auto_fill_from_inventory:
            reagents = ReagentDB.get_all()
            items = []
            for reagent in reagents:
                conflict_type = "none"
                if ReagentDB.is_expired(reagent["id"]):
                    conflict_type = "expired"
                elif reagent["quantity"] <= reagent["low_stock_threshold"]:
                    conflict_type = "low_stock"

                snapshot_before = json.dumps(reagent, ensure_ascii=False)

                items.append({
                    "reagent_name": reagent["name"],
                    "batch_number": reagent["batch_number"],
                    "storage_location": reagent.get("storage_condition", ""),
                    "expected_quantity": reagent["quantity"],
                    "actual_quantity": reagent["quantity"],
                    "unit": reagent["unit"],
                    "expiration_date": reagent.get("expiration_date"),
                    "low_stock_threshold": reagent["low_stock_threshold"],
                    "reagent_id": reagent["id"],
                    "conflict_type": conflict_type,
                    "snapshot_before": snapshot_before
                })

            if items:
                StocktakeItemDB.bulk_create(order_id, items)
                StocktakeLogDB.create(
                    operator_id=self.auth.current_user["id"],
                    operator_name=self.auth.current_user["display_name"],
                    operation_type="import_items",
                    order_id=order_id,
                    remarks=f"自动填充库存数据：{len(items)} 条"
                )

        return order_id, f"盘点单创建成功，单号：{StocktakeOrderDB.get_by_id(order_id)['order_no']}"

    def get_orders(self, filters: Dict = None) -> List[Dict]:
        self._check_permission("view_stocktake")
        return StocktakeOrderDB.get_all(filters)

    def get_order_by_id(self, order_id: int) -> Optional[Dict]:
        self._check_permission("view_stocktake")
        return StocktakeOrderDB.get_by_id(order_id)

    def get_items(self, order_id: int, filters: Dict = None) -> List[Dict]:
        self._check_permission("view_stocktake")
        return StocktakeItemDB.get_by_order_id(order_id, filters)

    def add_item(self, order_id: int, reagent_name: str, batch_number: str,
                 actual_quantity: int, storage_location: str = "",
                 unit: str = "", diff_reason: str = "") -> Tuple[int, str]:
        self._check_permission("edit_stocktake_item")

        order = StocktakeOrderDB.get_by_id(order_id)
        if not order:
            raise OperationError("盘点单不存在")
        if order["status"] != "draft":
            raise OperationError("只能在草稿状态下添加盘点项")

        if not reagent_name or not reagent_name.strip():
            raise OperationError("试剂名称不能为空")
        if not batch_number or not batch_number.strip():
            raise OperationError("批号不能为空")
        if actual_quantity < 0:
            raise OperationError("实际数量不能为负数")

        reagent = ReagentDB.get_by_name_and_batch(
            reagent_name.strip(), batch_number.strip()
        )

        expected_quantity = 0
        conflict_type = "none"
        reagent_id = None
        snapshot_before = ""

        if reagent:
            expected_quantity = reagent["quantity"]
            reagent_id = reagent["id"]
            snapshot_before = json.dumps(reagent, ensure_ascii=False)

            if ReagentDB.is_expired(reagent["id"]):
                conflict_type = "expired"
            elif reagent["quantity"] <= reagent["low_stock_threshold"]:
                conflict_type = "low_stock"
        else:
            conflict_type = "batch_not_found"

        item_id = StocktakeItemDB.create(
            order_id=order_id,
            reagent_name=reagent_name.strip(),
            batch_number=batch_number.strip(),
            expected_quantity=expected_quantity,
            actual_quantity=actual_quantity,
            unit=unit.strip(),
            storage_location=storage_location.strip(),
            expiration_date=reagent.get("expiration_date") if reagent else None,
            low_stock_threshold=reagent["low_stock_threshold"] if reagent else 10,
            reagent_id=reagent_id,
            diff_reason=diff_reason.strip(),
            conflict_type=conflict_type,
            process_status="pending" if conflict_type != "none" else "pending"
        )

        if snapshot_before:
            StocktakeItemDB.update(item_id, snapshot_before=snapshot_before)

        StocktakeLogDB.create(
            operator_id=self.auth.current_user["id"],
            operator_name=self.auth.current_user["display_name"],
            operation_type="update_item",
            order_id=order_id,
            item_id=item_id,
            reagent_name=reagent_name.strip(),
            batch_number=batch_number.strip(),
            old_value=str(expected_quantity),
            new_value=str(actual_quantity),
            diff_reason=diff_reason.strip(),
            remarks="添加盘点项"
        )

        return item_id, "盘点项添加成功"

    def update_item(self, item_id: int, actual_quantity: int = None,
                    diff_reason: str = None,
                    storage_location: str = None) -> Tuple[bool, str]:
        self._check_permission("edit_stocktake_item")

        item = StocktakeItemDB.get_by_id(item_id)
        if not item:
            raise OperationError("盘点项不存在")

        order = StocktakeOrderDB.get_by_id(item["order_id"])
        if not order or order["status"] != "draft":
            raise OperationError("只能在草稿状态下修改盘点项")

        update_kwargs = {}
        old_values = {}
        new_values = {}

        if actual_quantity is not None:
            if actual_quantity < 0:
                raise OperationError("实际数量不能为负数")
            update_kwargs["actual_quantity"] = actual_quantity
            old_values["actual_quantity"] = item["actual_quantity"]
            new_values["actual_quantity"] = actual_quantity

        if diff_reason is not None:
            update_kwargs["diff_reason"] = diff_reason.strip()
            old_values["diff_reason"] = item.get("diff_reason", "")
            new_values["diff_reason"] = diff_reason.strip()

        if storage_location is not None:
            update_kwargs["storage_location"] = storage_location.strip()
            old_values["storage_location"] = item.get("storage_location", "")
            new_values["storage_location"] = storage_location.strip()

        if not update_kwargs:
            return False, "没有需要更新的内容"

        success = StocktakeItemDB.update(item_id, **update_kwargs)
        if not success:
            raise OperationError("更新失败")

        StocktakeLogDB.create(
            operator_id=self.auth.current_user["id"],
            operator_name=self.auth.current_user["display_name"],
            operation_type="update_item",
            order_id=item["order_id"],
            item_id=item_id,
            reagent_name=item["reagent_name"],
            batch_number=item["batch_number"],
            old_value=json.dumps(old_values, ensure_ascii=False),
            new_value=json.dumps(new_values, ensure_ascii=False),
            remarks="更新盘点项"
        )

        return True, "盘点项更新成功"

    def delete_item(self, item_id: int) -> Tuple[bool, str]:
        self._check_permission("edit_stocktake_item")

        item = StocktakeItemDB.get_by_id(item_id)
        if not item:
            raise OperationError("盘点项不存在")

        order = StocktakeOrderDB.get_by_id(item["order_id"])
        if not order or order["status"] != "draft":
            raise OperationError("只能在草稿状态下删除盘点项")

        StocktakeLogDB.create(
            operator_id=self.auth.current_user["id"],
            operator_name=self.auth.current_user["display_name"],
            operation_type="update_item",
            order_id=item["order_id"],
            item_id=None,
            reagent_name=item["reagent_name"],
            batch_number=item["batch_number"],
            old_value=str(item.get("actual_quantity", "")),
            remarks="删除盘点项"
        )

        success = StocktakeItemDB.delete(item_id)
        if not success:
            raise OperationError("删除失败")

        return True, "盘点项删除成功"

    def import_items_from_csv(self, order_id: int,
                          csv_rows: List[Dict]) -> Tuple[int, str]:
        self._check_permission("import_stocktake")

        order = StocktakeOrderDB.get_by_id(order_id)
        if not order:
            raise OperationError("盘点单不存在")
        if order["status"] != "draft":
            raise OperationError("只能在草稿状态下导入盘点项")

        if not csv_rows:
            raise OperationError("导入数据为空")

        items = []
        errors = []

        for row_num, row in enumerate(csv_rows, start=1):
            reagent_name = row.get("试剂名称", "").strip()
            batch_number = row.get("批号", "").strip()
            actual_quantity_str = row.get("实盘数量", "").strip()
            storage_location = row.get("存放位置", "").strip()
            unit = row.get("单位", "").strip()
            diff_reason = row.get("差异原因", "").strip()

            if not reagent_name or not batch_number:
                errors.append(f"第 {row_num} 行：试剂名称和批号不能为空")
                continue

            try:
                actual_quantity = int(actual_quantity_str) if actual_quantity_str else 0
            except ValueError:
                errors.append(f"第 {row_num} 行：实盘数量必须是整数")
                continue

            if actual_quantity < 0:
                errors.append(f"第 {row_num} 行：实盘数量不能为负数")
                continue

            reagent = ReagentDB.get_by_name_and_batch(reagent_name, batch_number)

            expected_quantity = 0
            conflict_type = "none"
            reagent_id = None
            snapshot_before = ""
            expiration_date = None
            low_stock_threshold = 10

            if reagent:
                expected_quantity = reagent["quantity"]
                reagent_id = reagent["id"]
                snapshot_before = json.dumps(reagent, ensure_ascii=False)
                expiration_date = reagent.get("expiration_date")
                low_stock_threshold = reagent["low_stock_threshold"]

                if ReagentDB.is_expired(reagent["id"]):
                    conflict_type = "expired"
                elif reagent["quantity"] <= reagent["low_stock_threshold"]:
                    conflict_type = "low_stock"
            else:
                conflict_type = "batch_not_found"

            items.append({
                "reagent_name": reagent_name,
                "batch_number": batch_number,
                "storage_location": storage_location,
                "expected_quantity": expected_quantity,
                "actual_quantity": actual_quantity,
                "unit": unit,
                "expiration_date": expiration_date,
                "low_stock_threshold": low_stock_threshold,
                "reagent_id": reagent_id,
                "diff_reason": diff_reason,
                "conflict_type": conflict_type,
                "snapshot_before": snapshot_before
            })

        if errors:
            raise OperationError("\n".join(errors))

        if not items:
            raise OperationError("没有有效的导入数据")

        item_ids = StocktakeItemDB.bulk_create(order_id, items)

        StocktakeLogDB.create(
            operator_id=self.auth.current_user["id"],
            operator_name=self.auth.current_user["display_name"],
            operation_type="import_items",
            order_id=order_id,
            remarks=f"CSV导入：{len(items)} 条"
        )

        return len(item_ids), f"成功导入 {len(item_ids)} 条盘点项"

    def confirm_item(self, item_id: int,
                     skip: bool = False) -> Tuple[bool, str]:
        self._check_permission("confirm_stocktake")

        item = StocktakeItemDB.get_by_id(item_id)
        if not item:
            raise OperationError("盘点项不存在")

        order = StocktakeOrderDB.get_by_id(item["order_id"])
        if not order or order["status"] != "draft":
            raise OperationError("只能在草稿状态下确认盘点项")

        if item["process_status"] == "confirmed":
            return False, "该盘点项已确认"

        process_status = "skipped" if skip else "confirmed"

        success = StocktakeItemDB.update(
            item_id,
            process_status=process_status
        )

        if not success:
            raise OperationError("确认失败")

        StocktakeLogDB.create(
            operator_id=self.auth.current_user["id"],
            operator_name=self.auth.current_user["display_name"],
            operation_type="confirm_item",
            order_id=item["order_id"],
            item_id=item_id,
            reagent_name=item["reagent_name"],
            batch_number=item["batch_number"],
            old_value=item["expected_quantity"],
            new_value=item["actual_quantity"],
            diff_reason=item.get("diff_reason", "") if not skip else "跳过",
            remarks="跳过盘点项" if skip else "确认盘点项"
        )

        return True, f"盘点项已{process_status}"

    def confirm_batch(self, item_ids: List[int],
                   skip_all_pending: bool = False,
                   skip: bool = False) -> Tuple[int, str]:
        self._check_permission("confirm_stocktake")

        if not item_ids and not skip_all_pending:
            raise OperationError("请选择要确认的盘点项")

        count = 0
        errors = []

        if skip_all_pending:
            if item_ids:
                first_item = StocktakeItemDB.get_by_id(item_ids[0])
                if first_item:
                    pending_items = StocktakeItemDB.get_pending_items(first_item["order_id"])
                    item_ids = [item["id"] for item in pending_items]
            else:
                raise OperationError("无法确定盘点单ID")

        for item_id in item_ids:
            try:
                success, _ = self.confirm_item(item_id, skip=skip)
                if success:
                    count += 1
            except Exception as e:
                errors.append(f"ID {item_id}: {str(e)}")

        if errors:
            raise OperationError("\n".join(errors))

        StocktakeLogDB.create(
            operator_id=self.auth.current_user["id"],
            operator_name=self.auth.current_user["display_name"],
            operation_type="confirm_batch",
            remarks=f"批量确认：{count} 条"
        )

        return count, f"成功处理 {count} 条盘点项"

    def write_back_to_inventory(self, order_id: int,
                              item_ids: List[int] = None,
                              write_all_confirmed: bool = False) -> Tuple[int, str]:
        self._check_permission("write_back_stocktake")

        order = StocktakeOrderDB.get_by_id(order_id)
        if not order:
            raise OperationError("盘点单不存在")
        if order["status"] != "draft":
            raise OperationError("只能在草稿状态下写回库存")

        if write_all_confirmed:
            items = StocktakeItemDB.get_by_order_id(
                order_id, {"process_status": "confirmed"}
            )
            items = [item for item in items if item["diff_quantity"] != 0]
        elif item_ids:
            items = [StocktakeItemDB.get_by_id(iid) for iid in item_ids]
            items = [item for item in items if item]
        else:
            raise OperationError("请选择要写回的盘点项")

        if not items:
            raise OperationError("没有可写回的盘点项，请先确认盘点项")

        count = 0
        errors = []

        for item in items:
            if not item:
                continue
            if item["process_status"] != "confirmed":
                errors.append(
                    f"{item['reagent_name']} ({item['batch_number']})：状态不是已确认，跳过"
                )
                continue
            if item["diff_quantity"] == 0:
                continue
            if not item["reagent_id"]:
                errors.append(
                    f"{item['reagent_name']} ({item['batch_number']})：批号不存在，无法写回"
                )
                continue

            try:
                reagent = ReagentDB.get_by_id(item["reagent_id"])
                if not reagent:
                    errors.append(
                        f"{item['reagent_name']} ({item['batch_number']})：试剂不存在"
                    )
                    continue

                quantity_change = item["actual_quantity"] - item["expected_quantity"]

                if quantity_change != 0:
                    snapshot_before = json.dumps(reagent, ensure_ascii=False)

                    success = ReagentDB.update_quantity(
                        item["reagent_id"], quantity_change
                    )

                    if not success:
                        errors.append(
                            f"{item['reagent_name']} ({item['batch_number']})：库存更新失败"
                        )
                        continue

                    reagent_after = ReagentDB.get_by_id(item["reagent_id"])
                    snapshot_after = json.dumps(reagent_after, ensure_ascii=False)

                    StocktakeItemDB.update(
                        item["id"],
                        snapshot_after=snapshot_after
                    )

                    diff_remark = item.get("diff_reason", "") or "盘点调整"

                    OperationDB.create(
                        operation_type="stocktake",
                        reagent_id=item["reagent_id"],
                        quantity=quantity_change,
                        operator_id=self.auth.current_user["id"],
                        status="completed",
                        remarks=f"盘点调整：{diff_remark}",
                        revertable=1,
                        snapshot_before=snapshot_before,
                        snapshot_after=snapshot_after
                    )

                    LedgerDB.create(
                        reagent_id=item["reagent_id"],
                        reagent_name=item["reagent_name"],
                        batch_number=item["batch_number"],
                        operation_type="stocktake",
                        change_quantity=quantity_change,
                        balance_quantity=reagent_after["quantity"],
                        operator=self.auth.current_user["display_name"],
                        remarks=diff_remark
                    )

                    StocktakeLogDB.create(
                        operator_id=self.auth.current_user["id"],
                        operator_name=self.auth.current_user["display_name"],
                        operation_type="write_back",
                        order_id=order_id,
                        item_id=item["id"],
                        reagent_name=item["reagent_name"],
                        batch_number=item["batch_number"],
                        old_value=str(item["expected_quantity"]),
                        new_value=str(item["actual_quantity"]),
                        diff_reason=item.get("diff_reason", ""),
                        remarks="写回库存"
                    )

                    count += 1
            except Exception as e:
                errors.append(
                    f"{item['reagent_name']} ({item['batch_number']}): {str(e)}"
                )

        if errors:
            raise OperationError("\n".join(errors))

        StocktakeOrderDB.update_status(order_id, "confirmed")

        StocktakeLogDB.create(
            operator_id=self.auth.current_user["id"],
            operator_name=self.auth.current_user["display_name"],
            operation_type="write_back",
            order_id=order_id,
            remarks=f"写回完成，盘点单已确认"
        )

        return count, f"成功写回 {count} 条差异到库存"

    def cancel_order(self, order_id: int) -> Tuple[bool, str]:
        self._check_permission("cancel_stocktake_order")

        order = StocktakeOrderDB.get_by_id(order_id)
        if not order:
            raise OperationError("盘点单不存在")

        if order["status"] == "cancelled":
            return False, "盘点单已取消"

        if order["status"] == "confirmed":
            raise OperationError("已确认的盘点单无法取消")

        success = StocktakeOrderDB.update_status(order_id, "cancelled")
        if not success:
            raise OperationError("取消失败")

        StocktakeLogDB.create(
            operator_id=self.auth.current_user["id"],
            operator_name=self.auth.current_user["display_name"],
            operation_type="cancel_order",
            order_id=order_id,
            remarks=f"取消盘点单：{order['title']}"
        )

        return True, "盘点单已取消"

    def get_logs(self, filters: Dict = None) -> List[Dict]:
        self._check_permission("view_stocktake")
        return StocktakeLogDB.get_all(filters)
