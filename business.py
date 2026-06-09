import json
from typing import Dict, Optional, Tuple, List
from datetime import datetime

from database import (ReagentDB, OperationDB, LedgerDB, UserDB,
                      ReservationDB, ReservationLogDB, ReagentLockDB)
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
