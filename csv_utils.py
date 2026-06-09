import csv
import json
import hashlib
import os
from typing import List, Dict, Tuple, Optional
from datetime import datetime

from database import (ReagentDB, OperationDB, LedgerDB,
                      ReservationDB, ReagentLockDB, ReservationLogDB, ImportResultDB)
from auth import (AuthManager, OPERATION_TYPE_DISPLAY, STATUS_DISPLAY,
                  RESERVATION_STATUS_DISPLAY)


class CSVManager:
    def __init__(self, auth: AuthManager):
        self.auth = auth
        self._preview_cache: Dict[str, Dict] = {}

    def _check_permission(self, permission: str) -> None:
        if not self.auth.has_permission(permission):
            raise PermissionError("权限不足：当前角色无此操作权限")

    @staticmethod
    def get_file_hash(filepath: str) -> str:
        hasher = hashlib.sha256()
        with open(filepath, 'rb') as f:
            while True:
                chunk = f.read(8192)
                if not chunk:
                    break
                hasher.update(chunk)
        file_mtime = os.path.getmtime(filepath)
        file_size = os.path.getsize(filepath)
        hasher.update(f"{file_mtime}|{file_size}".encode())
        return hasher.hexdigest()

    def _validate_row(self, row: Dict, row_num: int, all_active_reservations: List[Dict],
                      existing_reagents_cache: Dict[str, Dict]) -> Tuple[Optional[Dict], List[str], List[str], List[str], List[str]]:
        errors = []
        warnings = []
        conflict_batches = []
        stock_warnings = []

        name = row["试剂名称"].strip()
        batch_number = row["批号"].strip()
        quantity_str = row["数量"].strip()
        unit = row["单位"].strip()

        if not name or not batch_number:
            errors.append(f"第 {row_num} 行：试剂名称和批号不能为空")
            return None, errors, warnings, conflict_batches, stock_warnings

        try:
            quantity = int(quantity_str) if quantity_str else 0
        except ValueError:
            errors.append(f"第 {row_num} 行：数量必须是整数")
            return None, errors, warnings, conflict_batches, stock_warnings

        if quantity < 0:
            errors.append(f"第 {row_num} 行：数量不能为负数")
            return None, errors, warnings, conflict_batches, stock_warnings

        cache_key = f"{name}|{batch_number}"
        if cache_key in existing_reagents_cache:
            errors.append(f"第 {row_num} 行：已存在相同名称和批号的试剂，跳过")
            return None, errors, warnings, conflict_batches, stock_warnings

        existing = ReagentDB.get_by_name_and_batch(name, batch_number)
        if existing:
            existing_reagents_cache[cache_key] = existing
            errors.append(f"第 {row_num} 行：已存在相同名称和批号的试剂，跳过")
            return None, errors, warnings, conflict_batches, stock_warnings

        expiration_date = row.get("过期日期", "").strip() or None
        if expiration_date:
            try:
                datetime.strptime(expiration_date, "%Y-%m-%d")
            except ValueError:
                errors.append(f"第 {row_num} 行：过期日期格式错误，应为 YYYY-MM-DD")
                return None, errors, warnings, conflict_batches, stock_warnings

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
            conflict_batches.append(f"{name}({batch_number})")

        available_after_import = quantity
        locked_qty = 0
        for r in conflict_reservations:
            if r["status"] == "approved" and r["batch_number"] == batch_number:
                locked_qty += r["quantity"]

        if locked_qty > 0:
            available_after_import = quantity - locked_qty
            if available_after_import < 0:
                stock_warnings.append(
                    f"第 {row_num} 行：{name} ({batch_number}) 导入后可用库存将为负数！"
                    f"导入数量：{quantity}，同批号已预约锁定：{locked_qty}，可用：{available_after_import}"
                )
            elif available_after_import <= low_stock_threshold:
                stock_warnings.append(
                    f"第 {row_num} 行：{name} ({batch_number}) 导入后可用库存将低于低库存阈值！"
                    f"导入数量：{quantity}，同批号已预约锁定：{locked_qty}，可用：{available_after_import}，阈值：{low_stock_threshold}"
                )
        elif quantity <= low_stock_threshold:
            stock_warnings.append(
                f"第 {row_num} 行：{name} ({batch_number}) 导入数量低于低库存阈值！"
                f"导入数量：{quantity}，阈值：{low_stock_threshold}"
            )

        parsed_row = {
            "name": name,
            "batch_number": batch_number,
            "quantity": quantity,
            "unit": unit,
            "expiration_date": expiration_date,
            "low_stock_threshold": low_stock_threshold,
            "specification": row.get("规格", "").strip(),
            "manufacturer": row.get("生产厂商", "").strip(),
            "storage_condition": row.get("储存条件", "").strip(),
            "remarks": row.get("备注", "").strip(),
            "row_num": row_num
        }

        return parsed_row, errors, warnings, conflict_batches, stock_warnings

    def _analyze_csv(self, filepath: str) -> Tuple[str, int, int, int, List[Dict], List[str], List[str], List[str], List[str]]:
        file_hash = self.get_file_hash(filepath)

        pending_reservations = ReservationDB.get_all({"status": "pending"})
        approved_reservations = ReservationDB.get_all({"status": "approved"})
        all_active_reservations = pending_reservations + approved_reservations

        success_count = 0
        skip_count = 0
        total_rows = 0
        valid_rows: List[Dict] = []
        all_errors: List[str] = []
        all_warnings: List[str] = []
        all_conflict_batches: List[str] = []
        all_stock_warnings: List[str] = []
        existing_reagents_cache: Dict[str, Dict] = {}

        with open(filepath, 'r', encoding='utf-8-sig') as f:
            reader = csv.DictReader(f)

            required_fields = ["试剂名称", "批号", "数量", "单位"]
            for field in required_fields:
                if field not in reader.fieldnames:
                    raise ValueError(f"CSV 文件缺少必要列：{field}")

            for row_num, row in enumerate(reader, start=2):
                total_rows += 1
                parsed_row, errors, warnings, conflict_batches, stock_warnings = self._validate_row(
                    row, row_num, all_active_reservations, existing_reagents_cache
                )

                all_errors.extend(errors)
                all_warnings.extend(warnings)
                all_conflict_batches.extend(conflict_batches)
                all_stock_warnings.extend(stock_warnings)

                if parsed_row:
                    valid_rows.append(parsed_row)
                    success_count += 1
                else:
                    skip_count += 1

        return file_hash, total_rows, success_count, skip_count, valid_rows, all_errors, all_warnings, all_conflict_batches, all_stock_warnings

    def preview_import(self, filepath: str) -> Dict:
        self._check_permission("import_csv")

        if not os.path.exists(filepath):
            raise FileNotFoundError(f"文件不存在：{filepath}")

        file_hash = self.get_file_hash(filepath)

        if file_hash in self._preview_cache:
            cached = self._preview_cache[file_hash]
            return {
                "file_hash": file_hash,
                "filepath": filepath,
                "total_rows": cached["total_rows"],
                "success_count": cached["success_count"],
                "skip_count": cached["skip_count"],
                "errors": cached["errors"],
                "warnings": cached["warnings"],
                "conflict_batches": cached["conflict_batches"],
                "stock_warnings": cached["stock_warnings"],
                "is_cached": True
            }

        file_hash, total_rows, success_count, skip_count, valid_rows, errors, warnings, conflict_batches, stock_warnings = self._analyze_csv(filepath)

        result = {
            "file_hash": file_hash,
            "filepath": filepath,
            "total_rows": total_rows,
            "success_count": success_count,
            "skip_count": skip_count,
            "errors": errors,
            "warnings": warnings,
            "conflict_batches": conflict_batches,
            "stock_warnings": stock_warnings,
            "valid_rows": valid_rows,
            "is_cached": False
        }

        self._preview_cache[file_hash] = {
            "file_hash": file_hash,
            "filepath": filepath,
            "total_rows": total_rows,
            "success_count": success_count,
            "skip_count": skip_count,
            "errors": errors,
            "warnings": warnings,
            "conflict_batches": conflict_batches,
            "stock_warnings": stock_warnings,
            "valid_rows": valid_rows
        }

        if self.auth.current_user:
            ImportResultDB.create(
                filepath=filepath,
                file_hash=file_hash,
                success_count=success_count,
                skip_count=skip_count,
                total_rows=total_rows,
                errors=errors,
                warnings=warnings,
                conflict_batches=conflict_batches,
                stock_warnings=stock_warnings,
                operator_id=self.auth.current_user["id"],
                operator_name=self.auth.current_user["display_name"],
                status="previewed"
            )

        return result

    def check_file_changed(self, filepath: str, expected_hash: str) -> Tuple[bool, str]:
        if not os.path.exists(filepath):
            return True, ""
        current_hash = self.get_file_hash(filepath)
        return current_hash != expected_hash, current_hash

    def import_reagents(self, filepath: str, use_cached: bool = True, expected_hash: str = None) -> Tuple[int, int, List[str], List[str]]:
        self._check_permission("import_csv")

        if not os.path.exists(filepath):
            raise FileNotFoundError(f"文件不存在：{filepath}")

        current_hash = self.get_file_hash(filepath)
        cached_result = None

        if use_cached and expected_hash:
            if current_hash != expected_hash:
                raise ValueError(
                    "文件内容已变化，预检结果已失效。\n"
                    "请重新执行预检或确认文件未被修改。"
                )
            if expected_hash in self._preview_cache:
                cached_result = self._preview_cache[expected_hash]

        if not cached_result:
            file_hash, total_rows, success_count, skip_count, valid_rows, errors, warnings, conflict_batches, stock_warnings = self._analyze_csv(filepath)
        else:
            valid_rows = cached_result["valid_rows"]
            errors = cached_result["errors"]
            warnings = cached_result["warnings"]
            conflict_batches = cached_result["conflict_batches"]
            stock_warnings = cached_result["stock_warnings"]

        actual_success = 0
        actual_skip = len(errors)

        for row_data in valid_rows:
            try:
                name = row_data["name"]
                batch_number = row_data["batch_number"]
                quantity = row_data["quantity"]
                unit = row_data["unit"]
                expiration_date = row_data["expiration_date"]
                low_stock_threshold = row_data["low_stock_threshold"]
                specification = row_data["specification"]
                manufacturer = row_data["manufacturer"]
                storage_condition = row_data["storage_condition"]
                remarks = row_data["remarks"]

                existing = ReagentDB.get_by_name_and_batch(name, batch_number)
                if existing:
                    errors.append(f"第 {row_data['row_num']} 行：已存在相同名称和批号的试剂，跳过")
                    actual_skip += 1
                    continue

                reagent_id = ReagentDB.create(
                    name=name,
                    batch_number=batch_number,
                    quantity=quantity,
                    unit=unit,
                    expiration_date=expiration_date,
                    low_stock_threshold=low_stock_threshold,
                    specification=specification,
                    manufacturer=manufacturer,
                    storage_condition=storage_condition,
                    remarks=remarks
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

                actual_success += 1
            except Exception as e:
                errors.append(f"第 {row_data['row_num']} 行：{str(e)}")
                actual_skip += 1
                continue

        saved_result = ImportResultDB.get_by_file_hash(current_hash)
        if saved_result:
            ImportResultDB.update_status(
                saved_result["id"], "imported",
                success_count=actual_success,
                skip_count=actual_skip
            )
        else:
            ImportResultDB.create(
                filepath=filepath,
                file_hash=current_hash,
                success_count=actual_success,
                skip_count=actual_skip,
                total_rows=actual_success + actual_skip,
                errors=errors,
                warnings=warnings,
                conflict_batches=conflict_batches,
                stock_warnings=stock_warnings,
                operator_id=self.auth.current_user["id"],
                operator_name=self.auth.current_user["display_name"],
                status="imported"
            )

        if current_hash in self._preview_cache:
            del self._preview_cache[current_hash]

        return actual_success, actual_skip, errors, warnings

    def get_preview_summary(self, preview_result: Dict) -> str:
        lines = [
            "═══════════════════════════════════════════════════════════════",
            "                     📋 CSV 导入预检报告",
            "═══════════════════════════════════════════════════════════════",
            f"📁 文件路径：{preview_result['filepath']}",
            f"📝 文件校验和：{preview_result['file_hash'][:16]}...",
            f"📊 总行数：{preview_result['total_rows']}",
            "",
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
            "                     📈 导入结果统计",
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
            f"✅ 预计新增：{preview_result['success_count']} 条",
            f"❌ 预计跳过：{preview_result['skip_count']} 条",
        ]

        if preview_result.get("is_cached"):
            lines.append("ℹ️  (使用缓存的预检结果)")

        if preview_result["conflict_batches"]:
            lines.append("")
            lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
            lines.append("                     ⚠️  预约冲突警告")
            lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
            lines.append(f"以下批号存在未完成的预约（共 {len(preview_result['conflict_batches'])} 个）：")
            for batch in preview_result["conflict_batches"]:
                lines.append(f"  • {batch}")

        if preview_result["stock_warnings"]:
            lines.append("")
            lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
            lines.append("                     🚨 库存风险警告")
            lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
            lines.append(f"以下试剂导入后可能存在库存问题（共 {len(preview_result['stock_warnings'])} 条）：")
            for warning in preview_result["stock_warnings"]:
                lines.append(f"  • {warning}")

        if preview_result["warnings"]:
            lines.append("")
            lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
            lines.append("                     💡 其他警告")
            lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
            for warning in preview_result["warnings"][:10]:
                lines.append(f"  • {warning}")
            if len(preview_result["warnings"]) > 10:
                lines.append(f"  ... 还有 {len(preview_result['warnings']) - 10} 条警告")

        if preview_result["errors"]:
            lines.append("")
            lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
            lines.append("                     ❌ 错误详情（将跳过）")
            lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
            for error in preview_result["errors"][:15]:
                lines.append(f"  • {error}")
            if len(preview_result["errors"]) > 15:
                lines.append(f"  ... 还有 {len(preview_result['errors']) - 15} 条错误")

        lines.append("")
        lines.append("═══════════════════════════════════════════════════════════════")
        lines.append("  请仔细检查以上信息，确认无误后再执行正式导入。")
        lines.append("═══════════════════════════════════════════════════════════════")

        return "\n".join(lines)

    def get_import_summary(self, success_count: int, skip_count: int, errors: List[str], warnings: List[str]) -> str:
        lines = [
            "═══════════════════════════════════════════════════════════════",
            "                     ✅ CSV 导入完成报告",
            "═══════════════════════════════════════════════════════════════",
            f"📅 操作时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            f"👤 操作人：{self.auth.current_user['display_name']}",
            "",
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
            "                     📊 导入结果统计",
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
            f"✅ 成功导入：{success_count} 条",
            f"❌ 跳过：{skip_count} 条",
            f"📝 总计处理：{success_count + skip_count} 条",
        ]

        if warnings:
            lines.append("")
            lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
            lines.append(f"                     ⚠️  警告信息（{len(warnings)} 条）")
            lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
            for warning in warnings[:10]:
                lines.append(f"  • {warning}")
            if len(warnings) > 10:
                lines.append(f"  ... 还有 {len(warnings) - 10} 条警告")

        if errors:
            lines.append("")
            lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
            lines.append(f"                     ❌ 跳过原因（{len(errors)} 条）")
            lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
            for error in errors[:15]:
                lines.append(f"  • {error}")
            if len(errors) > 15:
                lines.append(f"  ... 还有 {len(errors) - 15} 条错误")

        lines.append("")
        lines.append("═══════════════════════════════════════════════════════════════")
        lines.append("  导入结果已记录到操作日志和台账，可重启后查看。")
        lines.append("═══════════════════════════════════════════════════════════════")

        return "\n".join(lines)

    def get_import_history(self, limit: int = 20) -> List[Dict]:
        self._check_permission("view_history")
        return ImportResultDB.get_all(limit)

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
