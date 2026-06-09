from typing import Dict, Optional, List
from database import UserDB


ROLE_PERMISSIONS = {
    "admin": {
        "view_inventory": True,
        "stock_in": True,
        "apply_use": True,
        "approve_use": True,
        "reject_use": True,
        "return_reagent": True,
        "scrap": True,
        "stocktake": True,
        "view_history": True,
        "revert_operation": True,
        "import_csv": True,
        "export_csv": True,
        "manage_reagents": True,
        "view_ledger": True,
        "create_reservation": True,
        "approve_reservation": True,
        "reject_reservation": True,
        "reschedule_reservation": True,
        "cancel_reservation": True,
        "complete_reservation": True,
        "view_reservations": True,
        "view_reservation_logs": True,
        "release_expired_reservations": True,
        "revert_import": True,
        "view_import_audit": True,
        "view_stocktake": True,
        "create_stocktake_order": True,
        "edit_stocktake_item": True,
        "import_stocktake": True,
        "confirm_stocktake": True,
        "write_back_stocktake": True,
        "cancel_stocktake_order": True,
        "export_stocktake": True,
    },
    "lab_staff": {
        "view_inventory": True,
        "stock_in": False,
        "apply_use": True,
        "approve_use": False,
        "reject_use": False,
        "return_reagent": True,
        "scrap": False,
        "stocktake": False,
        "view_history": True,
        "revert_operation": False,
        "import_csv": False,
        "export_csv": True,
        "manage_reagents": False,
        "view_ledger": True,
        "create_reservation": True,
        "approve_reservation": False,
        "reject_reservation": False,
        "reschedule_reservation": False,
        "cancel_reservation": True,
        "complete_reservation": False,
        "view_reservations": True,
        "view_reservation_logs": True,
        "release_expired_reservations": False,
        "revert_import": False,
        "view_import_audit": False,
        "view_stocktake": True,
        "create_stocktake_order": False,
        "edit_stocktake_item": False,
        "import_stocktake": False,
        "confirm_stocktake": False,
        "write_back_stocktake": False,
        "cancel_stocktake_order": False,
        "export_stocktake": True,
    },
    "auditor": {
        "view_inventory": True,
        "stock_in": False,
        "apply_use": False,
        "approve_use": True,
        "reject_use": True,
        "return_reagent": False,
        "scrap": True,
        "stocktake": True,
        "view_history": True,
        "revert_operation": True,
        "import_csv": False,
        "export_csv": True,
        "manage_reagents": False,
        "view_ledger": True,
        "create_reservation": False,
        "approve_reservation": True,
        "reject_reservation": True,
        "reschedule_reservation": True,
        "cancel_reservation": True,
        "complete_reservation": True,
        "view_reservations": True,
        "view_reservation_logs": True,
        "release_expired_reservations": True,
        "revert_import": True,
        "view_import_audit": True,
        "view_stocktake": True,
        "create_stocktake_order": True,
        "edit_stocktake_item": True,
        "import_stocktake": True,
        "confirm_stocktake": True,
        "write_back_stocktake": True,
        "cancel_stocktake_order": True,
        "export_stocktake": True,
    }
}

ROLE_DISPLAY = {
    "admin": "管理员",
    "lab_staff": "实验员",
    "auditor": "审核员"
}

OPERATION_TYPE_DISPLAY = {
    "stock_in": "入库",
    "apply_use": "申请领用",
    "approve_use": "审核领用",
    "reject_use": "拒绝领用",
    "return": "归还",
    "scrap": "报废",
    "stocktake": "盘点调整",
    "import": "CSV导入"
}

RESERVATION_OPERATION_DISPLAY = {
    "create": "创建预约",
    "approve": "审批通过",
    "reject": "拒绝预约",
    "cancel": "取消预约",
    "complete": "实际领用",
    "expire_release": "过期释放",
    "reschedule": "改期",
    "reschedule_release": "改期释放锁定",
    "revert": "撤销操作"
}

RESERVATION_STATUS_DISPLAY = {
    "pending": "待审核",
    "approved": "已审批",
    "rejected": "已拒绝",
    "cancelled": "已取消",
    "completed": "已领用",
    "expired": "已过期",
    "rescheduled": "已改期"
}

STATUS_DISPLAY = {
    "pending": "待审核",
    "approved": "已通过",
    "rejected": "已拒绝",
    "completed": "已完成",
    "cancelled": "已取消",
    "reverted": "已撤销"
}

STOCKTAKE_ORDER_STATUS_DISPLAY = {
    "draft": "草稿",
    "confirmed": "已确认",
    "cancelled": "已取消"
}

STOCKTAKE_PROCESS_STATUS_DISPLAY = {
    "pending": "待确认",
    "confirmed": "已确认",
    "skipped": "已跳过"
}

STOCKTAKE_CONFLICT_TYPE_DISPLAY = {
    "none": "无冲突",
    "expired": "已过期",
    "low_stock": "低于安全库存",
    "batch_not_found": "批号不存在"
}

STOCKTAKE_OPERATION_TYPE_DISPLAY = {
    "create_order": "创建盘点单",
    "update_item": "更新盘点项",
    "import_items": "导入盘点项",
    "confirm_item": "确认单条",
    "confirm_batch": "批量确认",
    "write_back": "写回库存",
    "cancel_order": "取消盘点单",
    "export": "导出数据"
}


class AuthManager:
    def __init__(self):
        self.current_user: Optional[Dict] = None

    def login(self, username: str) -> bool:
        user = UserDB.get_by_username(username)
        if user:
            self.current_user = user
            return True
        return False

    def logout(self):
        self.current_user = None

    def has_permission(self, permission: str) -> bool:
        if not self.current_user:
            return False
        role = self.current_user["role"]
        return ROLE_PERMISSIONS.get(role, {}).get(permission, False)

    def get_role_display(self) -> str:
        if not self.current_user:
            return ""
        return ROLE_DISPLAY.get(self.current_user["role"], self.current_user["role"])

    @staticmethod
    def get_all_users() -> List[Dict]:
        return UserDB.get_all()

    @staticmethod
    def get_role_display_name(role: str) -> str:
        return ROLE_DISPLAY.get(role, role)
