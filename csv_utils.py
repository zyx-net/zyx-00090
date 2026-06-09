import csv
import json
import hashlib
import os
from typing import List, Dict, Tuple, Optional
from datetime import datetime

from database import (ReagentDB, OperationDB, LedgerDB,
                      ReservationDB, ReagentLockDB, ReservationLogDB, ImportResultDB,
                      ImportPlanDB, ImportPlanItemDB, ImportAuditLogDB, get_connection)
from auth import (AuthManager, OPERATION_TYPE_DISPLAY, STATUS_DISPLAY,
                  RESERVATION_STATUS_DISPLAY)


class CSVImportError(Exception):
    pass


class CSVManager:
    def __init__(self, auth: AuthManager):
        self.auth = auth
        self._preview_cache: Dict[str, Dict] = {}

    def _check_permission(self, permission: str) -> None:
        if not self.auth.has_permission(permission):
            raise PermissionError("权限不足：当前角色无此操作权限")

    @staticmethod
    def generate_batch_no() -> str:
        now = datetime.now()
        import random
        random_str = ''.join(random.choices('0123456789ABCDEF', k=6))
        return f"IMP{now.strftime('%Y%m%d%H%M%S')}{random_str}"

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

    @staticmethod
    def get_file_summary(filepath: str, file_hash: str) -> str:
        basename = os.path.basename(filepath)
        file_size = os.path.getsize(filepath)
        if file_size < 1024:
            size_str = f"{file_size}B"
        elif file_size < 1024 * 1024:
            size_str = f"{file_size/1024:.1f}KB"
        else:
            size_str = f"{file_size/1024/1024:.1f}MB"
        return f"{basename} ({size_str}, {file_hash[:16]})"

    def _validate_row(self, row: Dict, row_num: int,
                      all_active_reservations: List[Dict],
                      existing_reagents_cache: Dict[str, Dict]) -> Tuple[Optional[Dict], str, List[str], str, Optional[Dict], str, Optional[str], List[str], List[str]]:
        errors = []
        warnings = []
        conflict_batches = []
        stock_warnings = []

        name = row["试剂名称"].strip()
        batch_number = row["批号"].strip()
        quantity_str = row["数量"].strip()
        unit = row["单位"].strip()

        if not name or not batch_number:
            return None, "skip", [f"第 {row_num} 行：试剂名称和批号不能为空"], "", None, None, None, [], []

        try:
            quantity = int(quantity_str) if quantity_str else 0
        except ValueError:
            return None, "skip", [f"第 {row_num} 行：数量必须是整数"], "", None, None, None, [], []

        if quantity < 0:
            return None, "skip", [f"第 {row_num} 行：数量不能为负数"], "", None, None, None, [], []

        if not self.auth.has_permission("import_csv"):
            return None, "permission_denied", [f"第 {row_num} 行：当前角色无导入权限"], "", None, None, None, [], []

        cache_key = f"{name}|{batch_number}"
        existing = None
        conflict_type = None
        conflict_details = None

        if cache_key in existing_reagents_cache:
            existing = existing_reagents_cache[cache_key]
        else:
            existing = ReagentDB.get_by_name_and_batch(name, batch_number)
            if existing:
                existing_reagents_cache[cache_key] = existing

        skip_conflict_check = False
        if existing:
            conflict_type = "duplicate_batch"
            conflict_details = json.dumps({
                "existing_id": existing["id"],
                "existing_quantity": existing["quantity"],
                "existing_unit": existing["unit"],
                "existing_expiration": existing.get("expiration_date"),
                "import_quantity": quantity,
                "import_unit": unit
            }, ensure_ascii=False)

            action = "conflict"
            skip_conflict_check = True
        else:
            action = "new"

        expiration_date = row.get("过期日期", "").strip() or None
        if expiration_date:
            try:
                datetime.strptime(expiration_date, "%Y-%m-%d")
            except ValueError:
                return None, "skip", [f"第 {row_num} 行：过期日期格式错误，应为 YYYY-MM-DD"], "", None, None, None, [], []

        try:
            low_stock_threshold = int(row.get("低库存阈值", "10"))
        except ValueError:
            low_stock_threshold = 10

        conflict_reservations = []
        if not skip_conflict_check:
            for res in all_active_reservations:
                if res["reagent_name"] == name:
                    conflict_reservations.append(res)

        if conflict_reservations:
            total_reserved = sum(r["quantity"] for r in conflict_reservations)
            same_batch_count = sum(
                1 for r in conflict_reservations
                if r["batch_number"] == batch_number
            )
            conflict_details_list = []
            for r in conflict_reservations[:3]:
                status = "待审核" if r["status"] == "pending" else "已审批"
                batch_info = f"[{r['batch_number']}" if r["batch_number"] != batch_number else ""
                conflict_details_list.append(
                    f"#{r['id']}({r.get('operator_name','')}预约{r['quantity']}{unit},{status}{batch_info})"
                )
            if len(conflict_reservations) > 3:
                conflict_details_list.append(f"...共{len(conflict_reservations)}个")

            batch_note = ""
            if same_batch_count > 0:
                batch_note = f"（其中{same_batch_count}个为同批号）"

            warnings.append(
                f"第 {row_num} 行：{name} ({batch_number}) 存在未完成预约冲突："
                f"导入数量 {quantity}{unit}，该试剂已预约 {total_reserved}{unit}{batch_note}。"
                f"冲突预约：{';'.join(conflict_details_list)}。"
                f"导入后可用库存可能不足，请谨慎处理。"
            )
            conflict_batches.append(f"{name}({batch_number})")

        available_after_import = quantity
        locked_qty = 0
        if not skip_conflict_check:
            for r in conflict_reservations:
                if r["status"] == "approved" and r["batch_number"] == batch_number:
                    locked_qty += r["quantity"]

        if not skip_conflict_check and locked_qty > 0:
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
        elif not skip_conflict_check and quantity <= low_stock_threshold:
            stock_warnings.append(
                f"第 {row_num} 行：{name} ({batch_number}) 导入数量低于低库存阈值！"
                f"导入数量：{quantity}，阈值：{low_stock_threshold}"
            )

        snapshot_before = json.dumps(existing, ensure_ascii=False) if existing else None

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

        return parsed_row, action, warnings, "", existing, conflict_type, conflict_details, conflict_batches, stock_warnings

    def _analyze_csv_for_plan(self, filepath: str) -> Tuple[str, str, int, List[Dict], List[str], List[str], List[str], List[str]]:
        file_hash = self.get_file_hash(filepath)
        file_summary = self.get_file_summary(filepath, file_hash)

        pending_reservations = ReservationDB.get_all({"status": "pending"})
        approved_reservations = ReservationDB.get_all({"status": "approved"})
        all_active_reservations = pending_reservations + approved_reservations

        total_rows = 0
        plan_items = []
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
                result = self._validate_row(
                    row, row_num, all_active_reservations, existing_reagents_cache
                )
                parsed_row, action, warnings, errors, existing, conflict_type, conflict_details, conflict_batches, stock_warnings = result

                if errors:
                    all_errors.extend(errors)
                if warnings:
                    all_warnings.extend(warnings)
                if conflict_batches:
                    all_conflict_batches.extend(conflict_batches)
                if stock_warnings:
                    all_stock_warnings.extend(stock_warnings)

                if parsed_row:
                    plan_items.append({
                        **parsed_row,
                        "action": action,
                        "conflict_type": conflict_type,
                        "conflict_details": conflict_details,
                        "existing_reagent": existing,
                        "snapshot_before": json.dumps(existing, ensure_ascii=False) if existing else None
                    })
                else:
                    plan_items.append({
                        "row_num": row_num,
                        "action": action,
                        "name": row.get("试剂名称", "").strip(),
                        "batch_number": row.get("批号", "").strip(),
                        "quantity": 0,
                        "unit": row.get("单位", "").strip(),
                        "errors": errors,
                        "conflict_type": conflict_type,
                        "conflict_details": conflict_details
                    })

        return file_hash, file_summary, total_rows, plan_items, all_errors, all_warnings, all_conflict_batches, all_stock_warnings

    def create_import_plan(self, filepath: str) -> Dict:
        self._check_permission("import_csv")

        if not os.path.exists(filepath):
            raise FileNotFoundError(f"文件不存在：{filepath}")

        file_hash, file_summary, total_rows, plan_items, errors, warnings, conflict_batches, stock_warnings = self._analyze_csv_for_plan(filepath)

        batch_no = self.generate_batch_no()

        operator_id = self.auth.current_user["id"]
        operator_name = self.auth.current_user["display_name"]

        plan_id = ImportPlanDB.create(
            batch_no=batch_no,
            filepath=filepath,
            file_hash=file_hash,
            file_summary=file_summary,
            total_rows=total_rows,
            operator_id=operator_id,
            operator_name=operator_name
        )

        new_count = 0
        update_count = 0
        skip_count = 0
        conflict_count = 0
        permission_denied_count = 0

        for item in plan_items:
            action = item["action"]
            if action == "new":
                new_count += 1
            elif action == "update":
                update_count += 1
            elif action == "skip":
                skip_count += 1
            elif action == "conflict":
                conflict_count += 1
            elif action == "permission_denied":
                permission_denied_count += 1

            ImportPlanItemDB.create(
                plan_id=plan_id,
                row_num=item["row_num"],
                action=action,
                name=item.get("name", ""),
                batch_number=item.get("batch_number", ""),
                quantity=item.get("quantity", 0),
                unit=item.get("unit", ""),
                expiration_date=item.get("expiration_date"),
                low_stock_threshold=item.get("low_stock_threshold", 10),
                specification=item.get("specification", ""),
                manufacturer=item.get("manufacturer", ""),
                storage_condition=item.get("storage_condition", ""),
                remarks=item.get("remarks", ""),
                existing_reagent_id=item["existing_reagent"]["id"] if item.get("existing_reagent") else None,
                conflict_type=item.get("conflict_type"),
                conflict_details=item.get("conflict_details"),
                snapshot_before=item.get("snapshot_before")
            )

        ImportPlanDB.update_counts(
            plan_id=plan_id,
            new_count=new_count,
            update_count=update_count,
            skip_count=skip_count,
            conflict_count=conflict_count,
            permission_denied_count=permission_denied_count
        )

        counts_summary = json.dumps({
            "total": total_rows,
            "new": new_count,
            "update": update_count,
            "skip": skip_count,
            "conflict": conflict_count,
            "permission_denied": permission_denied_count
        }, ensure_ascii=False)

        ImportAuditLogDB.create(
            plan_id=plan_id,
            operator_id=operator_id,
            operator_name=operator_name,
            action="create_plan",
            file_summary=file_summary,
            counts_summary=counts_summary
        )

        return {
            "plan_id": plan_id,
            "batch_no": batch_no,
            "filepath": filepath,
            "file_hash": file_hash,
            "file_summary": file_summary,
            "total_rows": total_rows,
            "new_count": new_count,
            "update_count": update_count,
            "skip_count": skip_count,
            "conflict_count": conflict_count,
            "permission_denied_count": permission_denied_count,
            "status": "draft",
            "errors": errors,
            "warnings": warnings,
            "conflict_batches": conflict_batches
        }

    def get_plan_preview(self, plan_id: int) -> Optional[Dict]:
        self._check_permission("import_csv")

        plan = ImportPlanDB.get_by_id(plan_id)
        if not plan:
            return None

        items = ImportPlanItemDB.get_by_plan_id(plan_id)

        new_items = [i for i in items if i["action"] == "new"]
        update_items = [i for i in items if i["action"] == "update"]
        skip_items = [i for i in items if i["action"] == "skip"]
        conflict_items = [i for i in items if i.get("conflict_type")]
        unresolved_conflict_items = [i for i in items if i["action"] == "conflict"]
        permission_items = [i for i in items if i["action"] == "permission_denied"]

        return {
            "plan": plan,
            "items": items,
            "new_items": new_items,
            "update_items": update_items,
            "skip_items": skip_items,
            "conflict_items": conflict_items,
            "unresolved_conflict_items": unresolved_conflict_items,
            "permission_denied_items": permission_items
        }

    def resolve_conflict(self, item_id: int, resolution: str) -> bool:
        self._check_permission("import_csv")

        if resolution not in ["keep_existing", "overwrite", "skip"]:
            raise ValueError("无效的冲突处理选择")

        item = ImportPlanItemDB.get_by_id(item_id)
        if not item:
            raise ValueError("冲突记录不存在")

        if not item.get("conflict_type"):
            raise ValueError("该记录不是冲突记录")

        success = ImportPlanItemDB.update_conflict_resolution(item_id, resolution)

        if success and resolution == "overwrite":
            ImportPlanItemDB.update_action(item_id, "update")
        elif success and resolution in ["skip", "keep_existing"]:
            ImportPlanItemDB.update_action(item_id, "skip")

        return success

    def resolve_all_conflicts(self, plan_id: int, default_resolution: str = "skip") -> int:
        self._check_permission("import_csv")

        if default_resolution not in ["keep_existing", "overwrite", "skip"]:
            raise ValueError("无效的冲突处理选择")

        conflicts = ImportPlanItemDB.get_conflicts_by_plan_id(plan_id)
        count = 0

        for conflict in conflicts:
            if not conflict.get("conflict_resolution"):
                self.resolve_conflict(conflict["id"], default_resolution)
                count += 1

        return count

    def confirm_import_plan(self, plan_id: int) -> Dict:
        self._check_permission("import_csv")

        plan = ImportPlanDB.get_by_id(plan_id)
        if not plan:
            raise ValueError("导入方案不存在")

        if plan["status"] != "draft":
            raise ValueError(f"方案状态为「{plan['status']}」，只有 status 为 draft 的方案才能确认导入")

        items = ImportPlanItemDB.get_by_plan_id(plan_id)

        unresolved_conflicts = [i for i in items if i["action"] == "conflict"]
        if unresolved_conflicts:
            raise ValueError(f"还有 {len(unresolved_conflicts)} 条冲突未处理，请先选择处理方式")

        file_changed, _ = self.check_file_changed(plan["filepath"], plan["file_hash"])
        if file_changed:
            raise ValueError("源文件已修改，方案已失效，请重新创建方案")

        actual_new = 0
        actual_update = 0
        actual_skip = 0
        errors = []
        imported_reagent_ids = []

        for item in items:
            try:
                action = item["action"]

                if action in ["skip", "permission_denied"]:
                    actual_skip += 1
                    continue

                name = item["name"]
                batch_number = item["batch_number"]
                quantity = item["quantity"]
                unit = item["unit"]
                expiration_date = item.get("expiration_date")
                low_stock_threshold = item.get("low_stock_threshold", 10)
                specification = item.get("specification", "")
                manufacturer = item.get("manufacturer", "")
                storage_condition = item.get("storage_condition", "")
                remarks = item.get("remarks", "")

                if action == "new":
                    existing = ReagentDB.get_by_name_and_batch(name, batch_number)
                    if existing:
                        errors.append(f"第 {item['row_num']} 行：已存在相同名称和批号的试剂，跳过")
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
                    actual_new += 1
                    imported_reagent_ids.append(reagent_id)

                elif action == "update":
                    existing_id = item.get("existing_reagent_id")
                    if not existing_id:
                        errors.append(f"第 {item['row_num']} 行：未找到要更新的试剂记录，跳过")
                        actual_skip += 1
                        continue

                    reagent_id = existing_id
                    existing = ReagentDB.get_by_id(reagent_id)
                    if not existing:
                        errors.append(f"第 {item['row_num']} 行：要更新的试剂不存在，跳过")
                        actual_skip += 1
                        continue

                    new_quantity = existing["quantity"] + quantity

                    if not ReagentDB.update(
                        reagent_id,
                        quantity=new_quantity,
                        unit=unit,
                        expiration_date=expiration_date,
                        low_stock_threshold=low_stock_threshold,
                        specification=specification,
                        manufacturer=manufacturer,
                        storage_condition=storage_condition,
                        remarks=remarks
                    ):
                        errors.append(f"第 {item['row_num']} 行：更新试剂失败，跳过")
                        actual_skip += 1
                        continue

                    actual_update += 1
                    imported_reagent_ids.append(reagent_id)

                else:
                    actual_skip += 1
                    continue

                reagent_after = ReagentDB.get_by_id(reagent_id)
                snapshot_after = json.dumps(reagent_after, ensure_ascii=False)

                snapshot_before = item.get("snapshot_before", "")
                if isinstance(snapshot_before, dict):
                    snapshot_before = json.dumps(snapshot_before, ensure_ascii=False)

                OperationDB.create(
                    operation_type="import",
                    reagent_id=reagent_id,
                    quantity=quantity,
                    operator_id=self.auth.current_user["id"],
                    status="completed",
                    remarks=f"CSV导入（方案#{plan_id}，批次{plan['batch_no']}）",
                    revertable=0,
                    snapshot_before=snapshot_before,
                    snapshot_after=snapshot_after
                )

                LedgerDB.create(
                    reagent_id=reagent_id,
                    reagent_name=name,
                    batch_number=batch_number,
                    operation_type="import",
                    change_quantity=quantity,
                    balance_quantity=reagent_after["quantity"],
                    operator=self.auth.current_user["display_name"],
                    remarks=f"CSV导入（方案#{plan_id}）"
                )

                ImportPlanItemDB.update_after_import(
                    item_id=item["id"],
                    reagent_id=reagent_id,
                    snapshot_after=snapshot_after
                )

            except Exception as e:
                errors.append(f"第 {item['row_num']} 行：{str(e)}")
                actual_skip += 1
                continue

        ImportPlanDB.update_status(plan_id, "confirmed")

        import time
        time.sleep(1.0)

        operator_id = self.auth.current_user["id"]
        operator_name = self.auth.current_user["display_name"]

        counts_summary = json.dumps({
            "total": plan["total_rows"],
            "total_imported": actual_new + actual_update,
            "new": actual_new,
            "update": actual_update,
            "skip": actual_skip,
            "conflict": plan["conflict_count"],
            "permission_denied": plan["permission_denied_count"]
        }, ensure_ascii=False)

        conflict_items = ImportPlanItemDB.get_conflicts_by_plan_id(plan_id)
        conflict_resolutions = json.dumps([{
            "item_id": i["id"],
            "name": i["name"],
            "batch_number": i["batch_number"],
            "resolution": i.get("conflict_resolution", "未处理")
        } for i in conflict_items], ensure_ascii=False)

        ImportAuditLogDB.create(
            plan_id=plan_id,
            operator_id=operator_id,
            operator_name=operator_name,
            action="confirm_import",
            file_summary=plan["file_summary"],
            counts_summary=counts_summary,
            conflict_resolutions=conflict_resolutions
        )

        ImportResultDB.create(
            filepath=plan["filepath"],
            file_hash=plan["file_hash"],
            success_count=actual_new + actual_update,
            skip_count=actual_skip,
            total_rows=actual_new + actual_update + actual_skip,
            errors=errors,
            operator_id=operator_id,
            operator_name=operator_name,
            status="imported",
            revertable=1,
            plan_id=plan_id
        )

        ImportPlanDB.update_counts(
            plan_id=plan_id,
            new_count=actual_new,
            update_count=actual_update,
            skip_count=actual_skip
        )

        return {
            "plan_id": plan_id,
            "batch_no": plan["batch_no"],
            "new_count": actual_new,
            "update_count": actual_update,
            "skip_count": actual_skip,
            "total_imported": actual_new + actual_update,
            "errors": errors,
            "imported_reagent_ids": imported_reagent_ids
        }

    def cancel_import_plan(self, plan_id: int) -> bool:
        self._check_permission("import_csv")

        plan = ImportPlanDB.get_by_id(plan_id)
        if not plan:
            raise ValueError("导入方案不存在")

        if plan["status"] != "draft":
            raise ValueError(f"方案状态为「{plan['status']}」，无法取消")

        success = ImportPlanDB.update_status(plan_id, "cancelled")

        if success:
            ImportAuditLogDB.create(
                plan_id=plan_id,
                operator_id=self.auth.current_user["id"],
                operator_name=self.auth.current_user["display_name"],
                action="cancel_plan",
                file_summary=plan["file_summary"],
                counts_summary=json.dumps({
                    "total": plan["total_rows"],
                    "new": plan["new_count"],
                    "update": plan["update_count"],
                    "skip": plan["skip_count"],
                    "conflict": plan["conflict_count"],
                    "permission_denied": plan["permission_denied_count"]
                }, ensure_ascii=False)
            )

        return success

    def revert_last_import(self) -> Dict:
        self._check_permission("revert_import")

        last_plan = ImportPlanDB.get_last_revertable()
        if not last_plan:
            raise ValueError("没有可撤销的导入记录")

        plan_id = last_plan["id"]
        items = ImportPlanItemDB.get_by_plan_id(plan_id)
        imported_items = [i for i in items if i.get("reagent_id") and i["action"] in ["new", "update"]]

        new_deleted = 0
        updates_restored = 0

        for item in imported_items:
            reagent_id = item["reagent_id"]

            conn = get_connection()
            cursor = conn.cursor()
            try:
                if item["action"] == "new":
                    cursor.execute("DELETE FROM inventory_ledger WHERE reagent_id = ?", (reagent_id,))
                    cursor.execute("DELETE FROM operations WHERE reagent_id = ?", (reagent_id,))
                    cursor.execute("DELETE FROM reservation_logs WHERE reagent_id = ?", (reagent_id,))
                    cursor.execute("DELETE FROM reservations WHERE reagent_id = ?", (reagent_id,))
                    cursor.execute("UPDATE import_plan_items SET existing_reagent_id = NULL WHERE existing_reagent_id = ?", (reagent_id,))
                    cursor.execute("UPDATE import_plan_items SET reagent_id = NULL WHERE reagent_id = ?", (reagent_id,))
                    conn.commit()

                    ReagentDB.delete(reagent_id)
                    new_deleted += 1

                elif item["action"] == "update":
                    try:
                        snapshot_before = item.get("snapshot_before")
                        if snapshot_before:
                            if isinstance(snapshot_before, str):
                                existing_data = json.loads(snapshot_before)
                            else:
                                existing_data = snapshot_before

                            cursor.execute(
                                "DELETE FROM operations WHERE reagent_id = ? AND operation_type = 'import' AND remarks LIKE ?",
                                (reagent_id, f"%方案#{plan_id}%")
                            )
                            cursor.execute(
                                "DELETE FROM inventory_ledger WHERE reagent_id = ? AND operation_type = 'import' AND remarks LIKE ?",
                                (reagent_id, f"%方案#{plan_id}%")
                            )
                            conn.commit()

                            ReagentDB.restore(
                                reagent_id,
                                quantity=existing_data.get("quantity", 0),
                                unit=existing_data.get("unit", ""),
                                expiration_date=existing_data.get("expiration_date"),
                                low_stock_threshold=existing_data.get("low_stock_threshold", 10),
                                specification=existing_data.get("specification", ""),
                                manufacturer=existing_data.get("manufacturer", ""),
                                storage_condition=existing_data.get("storage_condition", ""),
                                remarks=existing_data.get("remarks", ""),
                                updated_at=existing_data.get("updated_at")
                            )
                            updates_restored += 1
                    except Exception:
                        pass
            finally:
                conn.close()

        ImportPlanDB.update_status(last_plan["id"], "reverted")

        import time
        time.sleep(1.0)

        results = ImportResultDB.get_all(100)
        for r in results:
            if r.get("plan_id") == last_plan["id"]:
                conn = get_connection()
                cursor = conn.cursor()
                try:
                    cursor.execute("UPDATE import_results SET reverted = 1, revertable = 0 WHERE id = ?", (r["id"],))
                    conn.commit()
                finally:
                    conn.close()
                break

        ImportAuditLogDB.create(
            plan_id=last_plan["id"],
            operator_id=self.auth.current_user["id"],
            operator_name=self.auth.current_user["display_name"],
            action="revert_import",
            file_summary=last_plan["file_summary"],
            counts_summary=json.dumps({
                "total_reverted": len(imported_items),
                "new_deleted": new_deleted,
                "updates_restored": updates_restored,
                "new_reverted": len([i for i in imported_items if i["action"] == "new"]),
                "update_reverted": len([i for i in imported_items if i["action"] == "update"])
            }, ensure_ascii=False)
        )

        return {
            "plan_id": last_plan["id"],
            "batch_no": last_plan["batch_no"],
            "reverted_count": len(imported_items),
            "new_deleted": new_deleted,
            "updates_restored": updates_restored,
            "message": f"已成功撤销导入批次 {last_plan['batch_no']}，共恢复 {len(imported_items)} 条记录"
        }

    def get_last_revertable_import(self) -> Optional[Dict]:
        self._check_permission("revert_import")
        return ImportPlanDB.get_last_revertable()

    def get_pending_drafts(self) -> List[Dict]:
        self._check_permission("import_csv")
        return ImportPlanDB.get_pending_drafts(self.auth.current_user["id"])

    def get_all_plans(self, limit: int = 100) -> List[Dict]:
        self._check_permission("view_import_audit")
        return ImportPlanDB.get_all(limit)

    def get_audit_logs(self, plan_id: int = None, limit: int = 100) -> List[Dict]:
        self._check_permission("view_import_audit")
        if plan_id:
            return ImportAuditLogDB.get_by_plan_id(plan_id)
        return ImportAuditLogDB.get_all(limit)

    def check_file_changed(self, filepath: str, expected_hash: str) -> Tuple[bool, str]:
        if not os.path.exists(filepath):
            return True, ""
        current_hash = self.get_file_hash(filepath)
        return current_hash != expected_hash, current_hash

    def get_plan_summary(self, preview_data: Dict) -> str:
        plan = preview_data["plan"]
        lines = [
            "═══════════════════════════════════════════════════════════════",
            f"                  📋 导入方案预览",
            "═══════════════════════════════════════════════════════════════",
            f"📦 批次号：{plan['batch_no']}",
            f"📁 文件：{plan['file_summary']}",
            f"📊 总行数：{plan['total_rows']}",
            f"👤 创建人：{plan['operator_name']}",
            f"🕒 创建时间：{plan['created_at']}",
            f"📌 状态：{'草稿（待确认）' if plan['status'] == 'draft' else plan['status']}",
            "",
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
            "                     📈 分类统计",
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
            f"🆕 新增：{plan['new_count']} 条",
            f"🔄 更新：{plan['update_count']} 条",
            f"⏭️  跳过：{plan['skip_count']} 条",
            f"⚠️  冲突：{plan['conflict_count']} 条",
            f"🔒 权限受限：{plan['permission_denied_count']} 条",
        ]

        if preview_data["conflict_items"]:
            lines.append("")
            lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
            lines.append("                     ⚔️  冲突明细（需处理）")
            lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
            for item in preview_data["conflict_items"][:10]:
                resolution = item.get("conflict_resolution")
                resolution_str = f"[已选择：{'保留现有' if resolution == 'keep_existing' else '覆盖' if resolution == 'overwrite' else '跳过'}]" if resolution else "[待处理]"
                lines.append(f"  第{item['row_num']}行：{item['name']} ({item['batch_number']}) {resolution_str}")
            if len(preview_data["conflict_items"]) > 10:
                lines.append(f"  ... 还有 {len(preview_data['conflict_items']) - 10} 条冲突")

        if preview_data["new_items"]:
            lines.append("")
            lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
            lines.append("                     🆕 新增明细")
            lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
            for item in preview_data["new_items"][:10]:
                lines.append(f"  第{item['row_num']}行：{item['name']} ({item['batch_number']}) +{item['quantity']}{item['unit']}")
            if len(preview_data["new_items"]) > 10:
                lines.append(f"  ... 还有 {len(preview_data['new_items']) - 10} 条新增")

        if preview_data["skip_items"]:
            lines.append("")
            lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
            lines.append("                     ⏭️  跳过明细")
            lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
            for item in preview_data["skip_items"][:10]:
                lines.append(f"  第{item['row_num']}行：{item.get('name', '未知')} ({item.get('batch_number', '')}) - 数据错误或格式无效")
            if len(preview_data["skip_items"]) > 10:
                lines.append(f"  ... 还有 {len(preview_data['skip_items']) - 10} 条跳过")

        if preview_data["permission_denied_items"]:
            lines.append("")
            lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
            lines.append("                     🔒 权限受限明细")
            lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
            for item in preview_data["permission_denied_items"][:10]:
                lines.append(f"  第{item['row_num']}行：{item.get('name', '未知')} - 当前角色无导入权限")
            if len(preview_data["permission_denied_items"]) > 10:
                lines.append(f"  ... 还有 {len(preview_data['permission_denied_items']) - 10} 条权限受限")

        lines.append("")
        lines.append("═══════════════════════════════════════════════════════════════")
        if plan["conflict_count"] > 0 and not preview_data["conflict_items"]:
            lines.append("  ⚠️  存在未处理的冲突，请先选择处理方式后再确认导入")
        elif plan["status"] == "draft":
            lines.append("  ✅ 方案就绪，请确认无误后执行导入")
        lines.append("═══════════════════════════════════════════════════════════════")

        return "\n".join(lines)

    def get_import_history(self, limit: int = 20) -> List[Dict]:
        self._check_permission("view_history")
        return ImportResultDB.get_all(limit)

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

        return result

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
                result = self._validate_row(
                    row, row_num, all_active_reservations, existing_reagents_cache
                )
                parsed_row, action, warnings, errors, existing, conflict_type, conflict_details, conflict_batches, stock_warnings = result

                all_errors.extend(errors)
                all_warnings.extend(warnings)
                if conflict_batches:
                    all_conflict_batches.extend(conflict_batches)
                if stock_warnings:
                    all_stock_warnings.extend(stock_warnings)

                if parsed_row and action == "new":
                    valid_rows.append(parsed_row)
                    success_count += 1
                else:
                    skip_count += 1

        return file_hash, total_rows, success_count, skip_count, valid_rows, all_errors, all_warnings, all_conflict_batches, all_stock_warnings

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
            skip_count = cached_result.get("skip_count", 0)

        actual_success = 0
        actual_skip = skip_count

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
            status="imported",
            revertable=0
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

        if preview_result.get("conflict_batches"):
            lines.append("")
            lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
            lines.append("                     ⚠️  预约冲突警告")
            lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
            lines.append(f"以下批号存在未完成的预约（共 {len(preview_result['conflict_batches'])} 个）：")
            for batch in preview_result["conflict_batches"]:
                lines.append(f"  • {batch}")

        if preview_result.get("stock_warnings"):
            lines.append("")
            lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
            lines.append("                     🚨 库存风险警告")
            lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
            lines.append(f"以下试剂导入后可能存在库存问题（共 {len(preview_result['stock_warnings'])} 条）：")
            for warning in preview_result["stock_warnings"]:
                lines.append(f"  • {warning}")

        if preview_result.get("warnings"):
            lines.append("")
            lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
            lines.append("                     💡 其他警告")
            lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
            for warning in preview_result["warnings"][:10]:
                lines.append(f"  • {warning}")
            if len(preview_result["warnings"]) > 10:
                lines.append(f"  ... 还有 {len(preview_result['warnings']) - 10} 条警告")

        if preview_result.get("errors"):
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
