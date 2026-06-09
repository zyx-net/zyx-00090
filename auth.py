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

STATUS_DISPLAY = {
    "pending": "待审核",
    "approved": "已通过",
    "rejected": "已拒绝",
    "completed": "已完成",
    "cancelled": "已取消",
    "reverted": "已撤销"
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
