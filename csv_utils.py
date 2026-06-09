import csv
import json
from typing import List, Dict, Tuple
from datetime import datetime

from database import ReagentDB, OperationDB, LedgerDB
from auth import AuthManager, OPERATION_TYPE_DISPLAY, STATUS_DISPLAY


class CSVManager:
    def __init__(self, auth: AuthManager):
        self.auth = auth

    def _check_permission(self, permission: str) -> None:
        if not self.auth.has_permission(permission):
            raise PermissionError("权限不足：当前角色无此操作权限")

    def export_reagents(self, filepath: str, filters: Dict = None) -> Tuple[int, str]:
        self._check_permission("export_csv")

        reagents = ReagentDB.get_all(filters)

        headers = ["ID", "试剂名称", "批号", "数量", "单位", "过期日期", "低库存阈值",
                  "规格", "生产厂商", "储存条件", "备注", "创建时间", "更新时间"]

        with open(filepath, 'w', newline='', encoding='utf-8-sig') as f:
            writer = csv.writer(f)
            writer.writerow(headers)
            for r in reagents:
                writer.writerow([
                    r["id"],
                    r["name"],
                    r["batch_number"],
                    r["quantity"],
                    r["unit"],
                    r["expiration_date"] if r["expiration_date"] else "",
                    r["low_stock_threshold"],
                    r["specification"],
                    r["manufacturer"],
                    r["storage_condition"],
                    r["remarks"],
                    r["created_at"],
                    r["updated_at"]
                ])

        return len(reagents), f"成功导出 {len(reagents)} 条试剂数据到 {filepath}"

    def export_ledger(self, filepath: str, filters: Dict = None) -> Tuple[int, str]:
        self._check_permission("export_csv")

        ledger = LedgerDB.get_all(filters)

        headers = ["ID", "试剂ID", "试剂名称", "批号", "操作类型", "变动数量", "结存数量",
                  "操作人", "审核人", "操作时间", "备注"]

        with open(filepath, 'w', newline='', encoding='utf-8-sig') as f:
            writer = csv.writer(f)
            writer.writerow(headers)
            for entry in ledger:
                op_type = OPERATION_TYPE_DISPLAY.get(entry["operation_type"], entry["operation_type"])
                writer.writerow([
                    entry["id"],
                    entry["reagent_id"],
                    entry["reagent_name"],
                    entry["batch_number"],
                    op_type,
                    entry["change_quantity"],
                    entry["balance_quantity"],
                    entry["operator"],
                    entry["reviewer"] if entry["reviewer"] else "",
                    entry["operation_time"],
                    entry["remarks"]
                ])

        return len(ledger), f"成功导出 {len(ledger)} 条台账记录到 {filepath}"

    def import_reagents(self, filepath: str) -> Tuple[int, int, List[str]]:
        self._check_permission("import_csv")

        success_count = 0
        skip_count = 0
        errors = []

        with open(filepath, 'r', encoding='utf-8-sig') as f:
            reader = csv.DictReader(f)

            required_fields = ["试剂名称", "批号", "数量", "单位"]
            for field in required_fields:
                if field not in reader.fieldnames:
                    raise ValueError(f"CSV 文件缺少必要列：{field}")

            for row_num, row in enumerate(reader, start=2):
                try:
                    name = row["试剂名称"].strip()
                    batch_number = row["批号"].strip()
                    quantity_str = row["数量"].strip()
                    unit = row["单位"].strip()

                    if not name or not batch_number:
                        errors.append(f"第 {row_num} 行：试剂名称和批号不能为空")
                        skip_count += 1
                        continue

                    try:
                        quantity = int(quantity_str) if quantity_str else 0
                    except ValueError:
                        errors.append(f"第 {row_num} 行：数量必须是整数")
                        skip_count += 1
                        continue

                    if quantity < 0:
                        errors.append(f"第 {row_num} 行：数量不能为负数")
                        skip_count += 1
                        continue

                    existing = ReagentDB.get_by_name_and_batch(name, batch_number)
                    if existing:
                        errors.append(f"第 {row_num} 行：已存在相同名称和批号的试剂，跳过")
                        skip_count += 1
                        continue

                    expiration_date = row.get("过期日期", "").strip() or None
                    if expiration_date:
                        try:
                            datetime.strptime(expiration_date, "%Y-%m-%d")
                        except ValueError:
                            errors.append(f"第 {row_num} 行：过期日期格式错误，应为 YYYY-MM-DD")
                            skip_count += 1
                            continue

                    try:
                        low_stock_threshold = int(row.get("低库存阈值", "10"))
                    except ValueError:
                        low_stock_threshold = 10

                    reagent_before = None
                    reagent_id = ReagentDB.create(
                        name=name,
                        batch_number=batch_number,
                        quantity=quantity,
                        unit=unit,
                        expiration_date=expiration_date,
                        low_stock_threshold=low_stock_threshold,
                        specification=row.get("规格", "").strip(),
                        manufacturer=row.get("生产厂商", "").strip(),
                        storage_condition=row.get("储存条件", "").strip(),
                        remarks=row.get("备注", "").strip()
                    )

                    reagent_after = ReagentDB.get_by_id(reagent_id)
                    snapshot_after = json.dumps(reagent_after, ensure_ascii=False)

                    OperationDB.create(
                        operation_type="import",
                        reagent_id=reagent_id,
                        quantity=quantity,
                        operator_id=self.auth.current_user["id"],
                        status="completed",
                        remarks=f"CSV导入",
                        revertable=0,
                        snapshot_before="",
                        snapshot_after=snapshot_after
                    )

                    LedgerDB.create(
                        reagent_id=reagent_id,
                        reagent_name=name,
                        batch_number=batch_number,
                        operation_type="import",
                        change_quantity=quantity,
                        balance_quantity=quantity,
                        operator=self.auth.current_user["display_name"],
                        remarks="CSV导入"
                    )

                    success_count += 1
                except Exception as e:
                    errors.append(f"第 {row_num} 行：{str(e)}")
                    skip_count += 1
                    continue

        return success_count, skip_count, errors

    def create_sample_import(self, filepath: str) -> str:
        sample_data = [
            {
                "试剂名称": "无水乙醇",
                "批号": "20250101",
                "数量": "100",
                "单位": "瓶",
                "过期日期": "2027-12-31",
                "低库存阈值": "10",
                "规格": "500ml",
                "生产厂商": "国药集团",
                "储存条件": "阴凉干燥处",
                "备注": "分析纯"
            },
            {
                "试剂名称": "氯化钠",
                "批号": "20250215",
                "数量": "50",
                "单位": "瓶",
                "过期日期": "2028-06-30",
                "低库存阈值": "5",
                "规格": "500g",
                "生产厂商": "西陇化工",
                "储存条件": "室温",
                "备注": "分析纯"
            },
            {
                "试剂名称": "甲醇",
                "批号": "20241201",
                "数量": "30",
                "单位": "瓶",
                "过期日期": "2026-11-30",
                "低库存阈值": "8",
                "规格": "500ml",
                "生产厂商": "默克",
                "储存条件": "阴凉处",
                "备注": "色谱纯"
            }
        ]

        headers = ["试剂名称", "批号", "数量", "单位", "过期日期",
                  "低库存阈值", "规格", "生产厂商", "储存条件", "备注"]

        with open(filepath, 'w', newline='', encoding='utf-8-sig') as f:
            writer = csv.DictWriter(f, fieldnames=headers)
            writer.writeheader()
            writer.writerows(sample_data)

        return f"样例文件已创建：{filepath}"
