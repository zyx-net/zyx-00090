import csv
import json
from typing import List, Dict, Tuple
from datetime import datetime

from database import (ReagentDB, OperationDB, LedgerDB,
                      ReservationDB, ReagentLockDB, ReservationLogDB)
from auth import (AuthManager, OPERATION_TYPE_DISPLAY, STATUS_DISPLAY,
                  RESERVATION_STATUS_DISPLAY)


class CSVManager:
    def __init__(self, auth: AuthManager):
        self.auth = auth

    def _check_permission(self, permission: str) -> None:
        if not self.auth.has_permission(permission):
            raise PermissionError("权限不足：当前角色无此操作权限")

    def export_reagents(self, filepath: str, filters: Dict = None) -> Tuple[int, str]:
        self._check_permission("export_csv")

        from database import ReservationDB

        reagents = ReagentDB.get_all(filters)

        headers = ["ID", "试剂名称", "批号", "总库存", "已锁定量", "可用量",
                  "单位", "过期日期", "低库存阈值", "规格", "生产厂商",
                  "储存条件", "预约摘要", "备注", "创建时间", "更新时间"]

        with open(filepath, 'w', newline='', encoding='utf-8-sig') as f:
            writer = csv.writer(f)
            writer.writerow(headers)
            for r in reagents:
                locked = r.get("locked_quantity", 0)
                available = r["quantity"] - locked
                reservation_summary = ReservationDB.get_reservation_summary_for_reagent(r["id"])

                writer.writerow([
                    r["id"],
                    r["name"],
                    r["batch_number"],
                    r["quantity"],
                    locked,
                    available,
                    r["unit"],
                    r["expiration_date"] if r["expiration_date"] else "",
                    r["low_stock_threshold"],
                    r["specification"],
                    r["manufacturer"],
                    r["storage_condition"],
                    reservation_summary,
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

    def export_reservation_logs(self, filepath: str, filters: Dict = None) -> Tuple[int, str]:
        self._check_permission("view_reservation_logs")

        logs = ReservationLogDB.get_all(filters)

        if not logs:
            return 0, "没有符合条件的预约日志，未生成导出文件"

        headers = ["操作时间", "操作人", "预约状态变化", "试剂名称", "批号",
                   "数量", "锁定量变动", "库存量变动", "备注"]

        with open(filepath, 'w', newline='', encoding='utf-8-sig') as f:
            writer = csv.writer(f)
            writer.writerow(headers)

            for log in logs:
                status_before = RESERVATION_STATUS_DISPLAY.get(
                    log.get("status_before"), log.get("status_before") or "-"
                )
                status_after = RESERVATION_STATUS_DISPLAY.get(
                    log.get("status_after"), log.get("status_after") or "-"
                )
                status_change = f"{status_before} → {status_after}"

                quantity = log.get("quantity")
                quantity_str = str(quantity) if quantity is not None else "-"

                locked_change = log.get("locked_qty_change", 0)
                if locked_change > 0:
                    locked_str = f"+{locked_change}"
                elif locked_change < 0:
                    locked_str = str(locked_change)
                else:
                    locked_str = "0"

                stock_change = log.get("stock_qty_change", 0)
                if stock_change > 0:
                    stock_str = f"+{stock_change}"
                elif stock_change < 0:
                    stock_str = str(stock_change)
                else:
                    stock_str = "0"

                writer.writerow([
                    log.get("operation_time", ""),
                    log.get("operator_name", "") or "",
                    status_change,
                    log.get("reagent_name", "") or "",
                    log.get("batch_number", "") or "",
                    quantity_str,
                    locked_str,
                    stock_str,
                    log.get("remarks", "") or ""
                ])

        return len(logs), f"成功导出 {len(logs)} 条预约日志到 {filepath}"

    def import_reagents(self, filepath: str) -> Tuple[int, int, List[str], List[str]]:
        self._check_permission("import_csv")

        success_count = 0
        skip_count = 0
        errors = []
        warnings = []

        with open(filepath, 'r', encoding='utf-8-sig') as f:
            reader = csv.DictReader(f)

            required_fields = ["试剂名称", "批号", "数量", "单位"]
            for field in required_fields:
                if field not in reader.fieldnames:
                    raise ValueError(f"CSV 文件缺少必要列：{field}")

            pending_reservations = ReservationDB.get_all({"status": "pending"})
            approved_reservations = ReservationDB.get_all({"status": "approved"})
            all_active_reservations = pending_reservations + approved_reservations

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

                    conflict_reservations = []
                    for res in all_active_reservations:
                        if res["reagent_name"] == name:
                            conflict_reservations.append(res)

                    if conflict_reservations:
                        total_reserved = sum(r["quantity"] for r in conflict_reservations)
                        same_batch_count = sum(
                            1 for r in conflict_reservations
                            if r["batch_number"] == batch_number
                        )
                        conflict_details = []
                        for r in conflict_reservations[:3]:
                            status = "待审核" if r["status"] == "pending" else "已审批"
                            batch_info = f"[{r['batch_number']}" if r["batch_number"] != batch_number else ""
                            conflict_details.append(
                                f"#{r['id']}({r.get('operator_name','')}预约{r['quantity']}{unit},{status}{batch_info})"
                            )
                        if len(conflict_reservations) > 3:
                            conflict_details.append(f"...共{len(conflict_reservations)}个")

                        batch_note = ""
                        if same_batch_count > 0:
                            batch_note = f"（其中{same_batch_count}个为同批号）"

                        warnings.append(
                            f"第 {row_num} 行：{name} ({batch_number}) 存在未完成预约冲突："
                            f"导入数量 {quantity}{unit}，该试剂已预约 {total_reserved}{unit}{batch_note}。"
                            f"冲突预约：{';'.join(conflict_details)}。"
                            f"导入后可用库存可能不足，请谨慎处理。"
                        )

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

        return success_count, skip_count, errors, warnings

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
