import os
import sys
import csv
import sqlite3
import time
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from database import (
    init_database, DB_PATH, ReagentDB, OperationDB, LedgerDB,
    ReservationDB, ReservationLogDB, ReagentLockDB, close_db,
    ImportResultDB
)
from auth import AuthManager
from business import ReagentManager, OperationError
from csv_utils import CSVManager

def reset_database():
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)
    init_database()

def test_passed(name):
    print(f"[OK] {name}")

def test_failed(name, error):
    print(f"[FAIL] {name}: {error}")

def run_preflight_tests():
    passed = 0
    failed = 0

    auth = AuthManager()
    manager = ReagentManager(auth)
    csv_mgr = CSVManager(auth)

    print("=" * 70)
    print("CSV 预检导入功能 - 回归测试")
    print("=" * 70)

    # Test 1: 预检不落库测试
    print("\n【测试 1】预检不落库测试")
    try:
        auth.login("admin")
        reset_database()

        sample_path = os.path.join(os.path.dirname(DB_PATH), "test_preview_only.csv")
        csv_mgr.create_sample_import(sample_path)

        reagent_count_before = len(ReagentDB.get_all())
        ledger_count_before = len(LedgerDB.get_all())
        operation_count_before = len(OperationDB.get_all(1000))

        preview_result = csv_mgr.preview_import(sample_path)

        assert preview_result["success_count"] == 3, f"预计新增3条，实际{preview_result['success_count']}条"
        assert preview_result["skip_count"] == 0, f"预计跳过0条，实际{preview_result['skip_count']}条"
        assert preview_result["total_rows"] == 3, f"总行数应为3，实际{preview_result['total_rows']}"

        reagent_count_after = len(ReagentDB.get_all())
        ledger_count_after = len(LedgerDB.get_all())
        operation_count_after = len(OperationDB.get_all(1000))

        assert reagent_count_before == reagent_count_after, "预检不应修改试剂表"
        assert ledger_count_before == ledger_count_after, "预检不应修改台账"
        assert operation_count_before == operation_count_after, "预检不应修改操作日志"

        import_results_after = ImportResultDB.get_all(100)
        assert len(import_results_after) == 0, f"预检不应写入 import_results 表，实际有 {len(import_results_after)} 条记录"

        test_passed("预检不落库：试剂表、台账、操作日志、导入结果表均未变化")
        passed += 1

        summary = csv_mgr.get_preview_summary(preview_result)
        assert "预计新增：3 条" in summary, "预检报告应包含预计新增信息"
        assert "预计跳过：0 条" in summary, "预检报告应包含预计跳过信息"

        test_passed("预检报告生成正确")
        passed += 1

        os.remove(sample_path)
    except AssertionError as e:
        test_failed("预检不落库", str(e) if str(e) else "断言失败")
        failed += 1
    except Exception as e:
        test_failed("预检不落库", str(e) if str(e) else "未知错误")
        failed += 1

    # Test 2: 冲突提示测试
    print("\n【测试 2】冲突提示测试（未完成预约冲突检测）")
    try:
        auth.login("admin")
        reset_database()

        reagent_id, _ = manager.create_reagent(
            "冲突测试试剂", "CONFLICT001", 50, "瓶",
            low_stock_threshold=20
        )

        auth.login("lab_staff")
        res_id, _ = manager.create_reservation(
            reagent_id, 30,
            (datetime.now() + timedelta(days=5)).strftime("%Y-%m-%d"),
            "测试预约"
        )

        auth.login("auditor")
        manager.approve_reservation(res_id, "审批通过")

        auth.login("admin")
        conflict_csv_path = os.path.join(os.path.dirname(DB_PATH), "test_conflict.csv")
        with open(conflict_csv_path, 'w', newline='', encoding='utf-8-sig') as f:
            writer = csv.writer(f)
            writer.writerow(["试剂名称", "批号", "数量", "单位", "低库存阈值"])
            writer.writerow(["冲突测试试剂", "CONFLICT002", "15", "瓶", "20"])
            writer.writerow(["其他试剂", "OTHER001", "100", "瓶", "10"])

        preview_result = csv_mgr.preview_import(conflict_csv_path)

        assert len(preview_result["conflict_batches"]) >= 1, "应检测到预约冲突"
        assert "冲突测试试剂(CONFLICT002)" in preview_result["conflict_batches"], "冲突批号应被正确识别"

        assert len(preview_result["stock_warnings"]) >= 1, "应检测到库存警告"
        stock_warning_text = " ".join(preview_result["stock_warnings"])
        assert "低于低库存阈值" in stock_warning_text or "可用库存将低于" in stock_warning_text

        assert len(preview_result["warnings"]) >= 1, "应生成警告信息"
        warning_text = " ".join(preview_result["warnings"])
        assert "存在未完成预约冲突" in warning_text, "警告信息应包含预约冲突提示"

        test_passed("冲突提示：预约冲突和库存警告检测正确")
        passed += 1

        os.remove(conflict_csv_path)
    except AssertionError as e:
        test_failed("冲突提示", str(e) if str(e) else "断言失败")
        failed += 1
    except Exception as e:
        test_failed("冲突提示", str(e) if str(e) else "未知错误")
        failed += 1

    # Test 3: 文件变化后重检测试
    print("\n【测试 3】文件变化后重检测试")
    try:
        auth.login("admin")
        reset_database()

        change_csv_path = os.path.join(os.path.dirname(DB_PATH), "test_file_change.csv")
        with open(change_csv_path, 'w', newline='', encoding='utf-8-sig') as f:
            writer = csv.writer(f)
            writer.writerow(["试剂名称", "批号", "数量", "单位"])
            writer.writerow(["变化测试试剂", "CHANGE001", "100", "瓶"])

        hash1 = csv_mgr.get_file_hash(change_csv_path)
        preview_result1 = csv_mgr.preview_import(change_csv_path)
        assert preview_result1["success_count"] == 1

        time.sleep(1.1)

        with open(change_csv_path, 'w', newline='', encoding='utf-8-sig') as f:
            writer = csv.writer(f)
            writer.writerow(["试剂名称", "批号", "数量", "单位"])
            writer.writerow(["变化测试试剂", "CHANGE001", "100", "瓶"])
            writer.writerow(["新增试剂", "CHANGE002", "50", "瓶"])

        hash2 = csv_mgr.get_file_hash(change_csv_path)
        assert hash1 != hash2, "文件修改后哈希值应变化"

        file_changed, new_hash = csv_mgr.check_file_changed(change_csv_path, hash1)
        assert file_changed == True, "应检测到文件变化"
        assert new_hash == hash2, "新哈希值应匹配"

        try:
            csv_mgr.import_reagents(change_csv_path, use_cached=True, expected_hash=hash1)
            test_failed("文件变化后导入", "应抛出文件变化异常但成功了")
            failed += 1
        except ValueError as e:
            if "文件内容已变化" in str(e):
                test_passed("文件变化检测正确：导入时检测到文件变化并抛出异常")
                passed += 1
            else:
                test_failed("文件变化后导入", f"异常信息不符：{e}")
                failed += 1

        preview_result2 = csv_mgr.preview_import(change_csv_path)
        assert preview_result2["success_count"] == 2, f"重新预检应检测到2条，实际{preview_result2['success_count']}"

        success, skipped, errors, warnings = csv_mgr.import_reagents(
            change_csv_path, use_cached=True, expected_hash=hash2
        )
        assert success == 2, f"导入应成功2条，实际{success}"

        test_passed("文件变化后重新预检和导入正常")
        passed += 1

        os.remove(change_csv_path)
    except AssertionError as e:
        test_failed("文件变化后重检", str(e) if str(e) else "断言失败")
        failed += 1
    except Exception as e:
        test_failed("文件变化后重检", str(e) if str(e) else "未知错误")
        failed += 1

    # Test 4: 无权限拒绝测试
    print("\n【测试 4】无权限拒绝测试（含写库防护验证）")
    try:
        auth.login("lab_staff")
        reset_database()

        test_csv_path = os.path.join(os.path.dirname(DB_PATH), "test_permission.csv")
        csv_mgr.create_sample_import(test_csv_path)

        import_count_before = len(ImportResultDB.get_all(100))
        reagent_count_before = len(ReagentDB.get_all())
        ledger_count_before = len(LedgerDB.get_all())
        operation_count_before = len(OperationDB.get_all(1000))

        try:
            csv_mgr.preview_import(test_csv_path)
            test_failed("实验员预检", "应抛出权限异常但成功了")
            failed += 1
        except PermissionError as e:
            if "权限不足" in str(e):
                test_passed("实验员无法预检（权限校验正确）")
                passed += 1
            else:
                test_failed("实验员预检", f"异常信息不符：{e}")
                failed += 1

        try:
            csv_mgr.import_reagents(test_csv_path)
            test_failed("实验员导入", "应抛出权限异常但成功了")
            failed += 1
        except PermissionError as e:
            if "权限不足" in str(e):
                test_passed("实验员无法导入（权限校验正确）")
                passed += 1
            else:
                test_failed("实验员导入", f"异常信息不符：{e}")
                failed += 1

        auth.login("auditor")

        try:
            csv_mgr.preview_import(test_csv_path)
            test_failed("审核员预检", "应抛出权限异常但成功了")
            failed += 1
        except PermissionError as e:
            if "权限不足" in str(e):
                test_passed("审核员无法预检（权限校验正确）")
                passed += 1
            else:
                test_failed("审核员预检", f"异常信息不符：{e}")
                failed += 1

        import_count_after = len(ImportResultDB.get_all(100))
        reagent_count_after = len(ReagentDB.get_all())
        ledger_count_after = len(LedgerDB.get_all())
        operation_count_after = len(OperationDB.get_all(1000))

        assert import_count_before == import_count_after, f"无权限用户尝试操作不应写入 import_results，变化了 {import_count_after - import_count_before} 条"
        assert reagent_count_before == reagent_count_after, "无权限用户尝试操作不应修改试剂表"
        assert ledger_count_before == ledger_count_after, "无权限用户尝试操作不应修改台账"
        assert operation_count_before == operation_count_after, "无权限用户尝试操作不应修改操作日志"

        test_passed("无权限角色预检/导入尝试均不会写库")
        passed += 1

        os.remove(test_csv_path)
    except AssertionError as e:
        test_failed("无权限拒绝", str(e) if str(e) else "断言失败")
        failed += 1
    except Exception as e:
        test_failed("无权限拒绝", str(e) if str(e) else "未知错误")
        failed += 1

    # Test 5: 跨重启记录一致性测试
    print("\n【测试 5】跨重启记录一致性测试（预检不落库，仅导入后写库）")
    try:
        auth.login("admin")
        reset_database()

        persist_csv_path = os.path.join(os.path.dirname(DB_PATH), "test_persist.csv")
        csv_mgr.create_sample_import(persist_csv_path)

        preview_result = csv_mgr.preview_import(persist_csv_path)
        preview_file_hash = preview_result["file_hash"]

        import_results_after_preview = ImportResultDB.get_all(100)
        assert len(import_results_after_preview) == 0, f"预检后 import_results 表应为空，实际有 {len(import_results_after_preview)} 条记录"
        test_passed("预检后数据库无导入记录（符合预期）")
        passed += 1

        history_after_preview = csv_mgr.get_import_history(10)
        assert len(history_after_preview) == 0, f"预检后查询导入历史应为空，实际有 {len(history_after_preview)} 条"

        close_db()
        init_database()
        auth.login("admin")
        csv_mgr_restart1 = CSVManager(auth)
        history_after_restart1 = csv_mgr_restart1.get_import_history(10)
        assert len(history_after_restart1) == 0, f"模拟重启后导入历史仍应为空，实际有 {len(history_after_restart1)} 条"
        test_passed("预检后重启界面无导入历史（符合预期）")
        passed += 1

        success, skipped, errors, warnings = csv_mgr.import_reagents(persist_csv_path)
        assert success == 3, f"导入应成功3条，实际{success}"

        history_before = csv_mgr.get_import_history(10)
        assert len(history_before) >= 1, "至少应有1条导入记录"

        import_records = [h for h in history_before if h["status"] == "imported"]
        preview_records = [h for h in history_before if h["status"] == "previewed"]
        assert len(import_records) >= 1, "应有导入记录"

        imported_record = import_records[0]
        assert imported_record["success_count"] == 3
        assert imported_record["skip_count"] == 0
        assert imported_record["operator_name"] == "系统管理员"
        assert imported_record["file_hash"] == preview_file_hash
        assert isinstance(imported_record["errors"], list)
        assert isinstance(imported_record["warnings"], list)
        assert isinstance(imported_record["conflict_batches"], list)
        assert isinstance(imported_record["stock_warnings"], list)

        record_id = imported_record["id"]
        fetched_record = ImportResultDB.get_by_id(record_id)
        assert fetched_record is not None, "按ID查询应能找到记录"
        assert fetched_record["success_count"] == 3
        assert fetched_record["file_hash"] == preview_file_hash
        assert fetched_record["status"] == "imported", "记录状态应为imported"

        direct_csv_path = os.path.join(os.path.dirname(DB_PATH), "test_direct_import.csv")
        with open(direct_csv_path, 'w', newline='', encoding='utf-8-sig') as f:
            writer = csv.writer(f)
            writer.writerow(["试剂名称", "批号", "数量", "单位"])
            writer.writerow(["直接导入试剂", "DIRECT001", "50", "瓶"])

        success2, skipped2, errors2, warnings2 = csv_mgr.import_reagents(direct_csv_path)
        assert success2 == 1

        history_with_direct = csv_mgr.get_import_history(10)
        direct_imports = [h for h in history_with_direct if "test_direct_import.csv" in h["filepath"] and h["status"] == "imported"]
        assert len(direct_imports) >= 1, "直接导入也应生成记录"
        assert direct_imports[0]["success_count"] == 1

        test_passed("直接导入和先预检后导入均能正确生成记录")
        passed += 1

        close_db()

        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) as cnt FROM import_results")
        row = cursor.fetchone()
        assert row["cnt"] >= 2, f"数据库中应至少有2条导入结果记录，实际{row['cnt']}条"
        cursor.execute("SELECT * FROM import_results WHERE status = 'imported' ORDER BY id DESC LIMIT 1")
        row = cursor.fetchone()
        assert row["success_count"] == 1
        assert row["operator_name"] == "系统管理员"
        conn.close()

        init_database()
        auth.login("admin")
        csv_mgr2 = CSVManager(auth)

        history_after = csv_mgr2.get_import_history(10)
        assert len(history_after) >= 2, f"模拟重启后仍应能查询到导入历史，实际{len(history_after)}条"

        import_records_after = [h for h in history_after if h["status"] == "imported"]
        assert len(import_records_after) >= 2, f"重启后仍应能查询到2条导入记录，实际{len(import_records_after)}条"

        first_import = [h for h in import_records_after if "test_persist.csv" in h["filepath"]][0]
        assert first_import["success_count"] == 3
        assert first_import["file_hash"] == preview_file_hash

        reagents_after = ReagentDB.get_all()
        assert len(reagents_after) == 4, f"重启后试剂数据应保持一致，实际{len(reagents_after)}条"

        ledger_after = LedgerDB.get_all({"operation_type": "import"})
        assert len(ledger_after) == 4, f"重启后台账记录应保持一致，实际{len(ledger_after)}条"

        test_passed("跨重启记录一致性：预检和导入记录持久化正确，重启后数据完整")
        passed += 1

        os.remove(persist_csv_path)
        if os.path.exists(direct_csv_path):
            os.remove(direct_csv_path)
    except AssertionError as e:
        test_failed("跨重启记录一致性", str(e) if str(e) else "断言失败")
        failed += 1
    except Exception as e:
        test_failed("跨重启记录一致性", str(e) if str(e) else "未知错误")
        failed += 1

    # Test 6: 预检缓存复用测试
    print("\n【测试 6】预检缓存复用测试")
    try:
        auth.login("admin")
        reset_database()

        cache_csv_path = os.path.join(os.path.dirname(DB_PATH), "test_cache.csv")
        csv_mgr.create_sample_import(cache_csv_path)

        preview1 = csv_mgr.preview_import(cache_csv_path)
        assert preview1.get("is_cached") == False, "首次预检不应使用缓存"
        assert preview1["success_count"] == 3

        preview2 = csv_mgr.preview_import(cache_csv_path)
        assert preview2.get("is_cached") == True, "第二次预检应使用缓存"
        assert preview2["success_count"] == 3

        success, skipped, errors, warnings = csv_mgr.import_reagents(
            cache_csv_path, use_cached=True, expected_hash=preview1["file_hash"]
        )
        assert success == 3, "使用缓存结果导入应成功"

        test_passed("预检缓存复用：相同文件第二次预检使用缓存，导入时可复用结果")
        passed += 1

        os.remove(cache_csv_path)
    except AssertionError as e:
        test_failed("预检缓存复用", str(e) if str(e) else "断言失败")
        failed += 1
    except Exception as e:
        test_failed("预检缓存复用", str(e) if str(e) else "未知错误")
        failed += 1

    # 清理
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)

    print("\n" + "=" * 70)
    print(f"测试完成：通过 {passed} 项，失败 {failed} 项")
    print("=" * 70)

    if failed == 0:
        print("\n[SUCCESS] 所有预检导入回归测试通过！")
        return True
    else:
        print(f"\n[WARNING] 有 {failed} 项测试未通过")
        return False

if __name__ == "__main__":
    success = run_preflight_tests()
    sys.exit(0 if success else 1)
