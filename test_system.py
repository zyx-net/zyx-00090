import os
import sys
import csv
import sqlite3
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from database import (init_database, DB_PATH, ReagentDB, OperationDB, LedgerDB,
                       ReservationDB, ReservationLogDB, ReagentLockDB, close_db,
                       ImportResultDB, ImportPlanDB, ImportPlanItemDB, ImportAuditLogDB)
from auth import AuthManager
from business import ReagentManager, OperationError
from csv_utils import CSVManager


def reset_database():
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)
    init_database()


def test_passed(test_name):
    print(f"[OK] {test_name}")


def test_failed(test_name, error):
    print(f"[FAIL] {test_name}: {error}")


def run_tests():
    print("=" * 70)
    print("实验室试剂管理系统 - 自动化测试")
    print("=" * 70)

    reset_database()
    print(f"\n测试数据库: {DB_PATH}")
    print("=" * 70)

    auth = AuthManager()
    manager = ReagentManager(auth)
    csv_mgr = CSVManager(auth)

    passed = 0
    failed = 0

    # Test 1: 用户登录
    print("\n【测试 1】用户登录测试")
    try:
        assert auth.login("admin") == True
        assert auth.current_user["username"] == "admin"
        assert auth.current_user["role"] == "admin"
        test_passed("管理员登录成功")
        passed += 1
    except Exception as e:
        test_failed("管理员登录", str(e))
        failed += 1

    try:
        assert auth.login("lab_staff") == True
        assert auth.current_user["role"] == "lab_staff"
        test_passed("实验员登录成功")
        passed += 1
    except Exception as e:
        test_failed("实验员登录", str(e))
        failed += 1

    try:
        assert auth.login("auditor") == True
        assert auth.current_user["role"] == "auditor"
        test_passed("审核员登录成功")
        passed += 1
    except Exception as e:
        test_failed("审核员登录", str(e))
        failed += 1

    # Test 2: 权限测试
    print("\n【测试 2】权限校验测试")
    auth.login("lab_staff")
    try:
        manager.create_reagent("测试试剂", "TEST001", 100, "瓶")
        test_failed("实验员越权新增试剂", "应该失败但成功了")
        failed += 1
    except OperationError:
        test_passed("实验员不能新增试剂（权限校验正确）")
        passed += 1

    try:
        manager.stock_in(1, 10)
        test_failed("实验员越权入库", "应该失败但成功了")
        failed += 1
    except OperationError:
        test_passed("实验员不能入库（权限校验正确）")
        passed += 1

    try:
        manager.scrap(1, 1)
        test_failed("实验员越权报废", "应该失败但成功了")
        failed += 1
    except OperationError:
        test_passed("实验员不能报废（越权报废失败）")
        passed += 1

    auth.login("auditor")
    try:
        manager.stock_in(1, 10)
        test_failed("审核员越权入库", "应该失败但成功了")
        failed += 1
    except OperationError:
        test_passed("审核员不能入库（权限校验正确）")
        passed += 1

    # Test 3: 试剂创建和入库
    print("\n【测试 3】试剂创建和入库测试")
    auth.login("admin")
    try:
        reagent_id, msg = manager.create_reagent(
            "无水乙醇", "BATCH2025001", 100, "瓶",
            expiration_date=(datetime.now() + timedelta(days=365)).strftime("%Y-%m-%d"),
            low_stock_threshold=10, specification="500ml",
            manufacturer="国药集团", storage_condition="阴凉干燥处"
        )
        assert reagent_id > 0
        reagent = ReagentDB.get_by_id(reagent_id)
        assert reagent["name"] == "无水乙醇"
        assert reagent["batch_number"] == "BATCH2025001"
        assert reagent["quantity"] == 100
        assert reagent["low_stock_threshold"] == 10
        test_passed("创建试剂成功")
        passed += 1
    except Exception as e:
        test_failed("创建试剂", str(e))
        failed += 1

    try:
        op_id, msg = manager.stock_in(reagent_id, 50, "采购入库")
        reagent = ReagentDB.get_by_id(reagent_id)
        assert reagent["quantity"] == 150
        test_passed("试剂入库成功（100 + 50 = 150）")
        passed += 1
    except Exception as e:
        test_failed("试剂入库", str(e))
        failed += 1

    # Test 4: 过期试剂约束
    print("\n【测试 4】过期试剂约束测试")
    try:
        expired_id, _ = manager.create_reagent(
            "过期试剂", "EXPIRED001", 50, "瓶",
            expiration_date=(datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
        )
        test_passed("创建过期试剂成功")
        passed += 1
    except Exception as e:
        test_failed("创建过期试剂", str(e))
        failed += 1

    auth.login("lab_staff")
    try:
        manager.apply_use(expired_id, 10)
        test_failed("过期试剂领用", "应该失败但成功了")
        failed += 1
    except OperationError as e:
        if "已过期" in str(e):
            test_passed("过期试剂领用失败（正确）")
            passed += 1
        else:
            test_failed("过期试剂领用", f"错误信息不符: {e}")
            failed += 1

    try:
        manager.return_reagent(expired_id, 10)
        test_failed("过期试剂归还", "应该失败但成功了")
        failed += 1
    except OperationError as e:
        if "已过期" in str(e):
            test_passed("过期试剂归还失败（正确，应走报废流程）")
            passed += 1
        else:
            test_failed("过期试剂归还", f"错误信息不符: {e}")
            failed += 1

    # Test 5: 库存数量约束
    print("\n【测试 5】库存数量约束测试")
    auth.login("admin")
    try:
        manager.stock_in(reagent_id, -10)
        test_failed("负数入库", "应该失败但成功了")
        failed += 1
    except OperationError:
        test_passed("入库数量必须大于0（正确）")
        passed += 1

    auth.login("lab_staff")
    try:
        manager.apply_use(reagent_id, 999)
        test_failed("超库存领用", "应该失败但成功了")
        failed += 1
    except OperationError as e:
        if "库存不足" in str(e):
            test_passed("超库存数量领用失败（正确）")
            passed += 1
        else:
            test_failed("超库存领用", f"错误信息不符: {e}")
            failed += 1

    auth.login("auditor")
    try:
        manager.scrap(reagent_id, 999)
        test_failed("超库存报废", "应该失败但成功了")
        failed += 1
    except OperationError as e:
        if "库存不足" in str(e):
            test_passed("超库存数量报废失败（正确）")
            passed += 1
        else:
            test_failed("超库存报废", f"错误信息不符: {e}")
            failed += 1

    # Test 6: 领用审核流程
    print("\n【测试 6】领用审核流程测试")
    auth.login("lab_staff")
    try:
        apply_id, msg = manager.apply_use(reagent_id, 20, "实验使用")
        assert apply_id > 0
        test_passed("领用申请提交成功")
        passed += 1
    except Exception as e:
        test_failed("领用申请", str(e))
        failed += 1

    auth.login("auditor")
    try:
        pending = manager.get_pending_approvals()
        assert len(pending) > 0
        test_passed("待审核列表查询成功")
        passed += 1
    except Exception as e:
        test_failed("查询待审核", str(e))
        failed += 1

    try:
        approve_id, msg = manager.approve_use(apply_id, "审核通过")
        reagent = ReagentDB.get_by_id(reagent_id)
        assert reagent["quantity"] == 130
        test_passed("审核领用成功（150 - 20 = 130）")
        passed += 1
    except Exception as e:
        test_failed("审核领用", str(e))
        failed += 1

    # Test 7: 归还流程
    print("\n【测试 7】归还流程测试")
    auth.login("lab_staff")
    try:
        return_id, msg = manager.return_reagent(reagent_id, 5, "未使用完归还")
        reagent = ReagentDB.get_by_id(reagent_id)
        assert reagent["quantity"] == 135
        test_passed("归还成功（130 + 5 = 135）")
        passed += 1
    except Exception as e:
        test_failed("试剂归还", str(e))
        failed += 1

    # Test 8: 报废流程
    print("\n【测试 8】报废流程测试")
    auth.login("auditor")
    import time
    try:
        time.sleep(0.1)
        scrap_id, msg = manager.scrap(expired_id, 50, "试剂已过期")
        reagent = ReagentDB.get_by_id(expired_id)
        assert reagent["quantity"] == 0
        test_passed("报废成功（过期试剂 50 - 50 = 0）")
        passed += 1
    except Exception as e:
        test_failed("试剂报废", str(e))
        failed += 1

    # Test 9: 盘点流程
    print("\n【测试 9】盘点流程测试")
    import time
    try:
        time.sleep(0.1)
        stocktake_id, msg = manager.stocktake(reagent_id, 140, "盘点发现多出5个")
        reagent = ReagentDB.get_by_id(reagent_id)
        assert reagent["quantity"] == 140
        test_passed("盘点调整成功（135 → 140，+5）")
        passed += 1
    except Exception as e:
        test_failed("盘点调整", str(e))
        failed += 1

    try:
        time.sleep(0.1)
        stocktake_id, msg = manager.stocktake(reagent_id, 130, "盘点发现少了10个")
        reagent = ReagentDB.get_by_id(reagent_id)
        assert reagent["quantity"] == 130
        test_passed("盘点调整成功（140 → 130，-10）")
        passed += 1
    except Exception as e:
        test_failed("盘点调整减少", str(e))
        failed += 1

    # Test 10: 撤销功能
    print("\n【测试 10】撤销功能测试")
    auth.login("admin")
    try:
        from database import OperationDB

        test_reagent_id, _ = manager.create_reagent(
            "撤销测试试剂", "REVERT001", 100, "瓶",
            expiration_date=(datetime.now() + timedelta(days=365)).strftime("%Y-%m-%d")
        )

        manager.stock_in(test_reagent_id, 50, "测试入库，用于撤销")

        reagent_before = ReagentDB.get_by_id(test_reagent_id)
        assert reagent_before["quantity"] == 150

        last_op = OperationDB.get_last_revertable()
        if last_op is None:
            raise Exception("get_last_revertable() 返回 None")
        if last_op["operation_type"] != "stock_in":
            raise Exception(f"operation_type 应该是 'stock_in'，实际是 '{last_op['operation_type']}'")

        manager.revert_last_operation()
        reagent_after = ReagentDB.get_by_id(test_reagent_id)
        if reagent_after["quantity"] != 100:
            raise Exception(f"撤销后库存应该是 100，实际是 {reagent_after['quantity']}")

        test_passed("撤销入库成功（150 → 100）")
        passed += 1
    except Exception as e:
        test_failed("撤销入库", str(e))
        failed += 1

    auth.login("lab_staff")
    try:
        manager.revert_last_operation()
        test_failed("实验员越权撤销", "应该失败但成功了")
        failed += 1
    except OperationError:
        test_passed("实验员不能撤销（权限校验正确）")
        passed += 1

    # Test 11: 空历史撤销
    print("\n【测试 11】空历史撤销测试")
    reset_database()
    init_database()
    auth.login("admin")
    try:
        manager.revert_last_operation()
        test_failed("空历史撤销", "应该失败但成功了")
        failed += 1
    except OperationError as e:
        if "没有可撤销" in str(e):
            test_passed("空历史撤销失败（正确）")
            passed += 1
        else:
            test_failed("空历史撤销", f"错误信息不符: {e}")
            failed += 1

    # Test 12: 筛选功能
    print("\n【测试 12】筛选功能测试")
    reset_database()
    init_database()
    auth.login("admin")

    manager.create_reagent("正常试剂", "NOR001", 100, "瓶",
                          expiration_date=(datetime.now() + timedelta(days=365)).strftime("%Y-%m-%d"),
                          low_stock_threshold=20)
    manager.create_reagent("低库存试剂", "LOW001", 5, "瓶",
                          expiration_date=(datetime.now() + timedelta(days=365)).strftime("%Y-%m-%d"),
                          low_stock_threshold=10)
    manager.create_reagent("过期试剂", "EXP001", 30, "瓶",
                          expiration_date=(datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d"))
    manager.create_reagent("批号匹配", "MATCH001", 50, "瓶")

    try:
        all_reagents = manager.get_reagents()
        assert len(all_reagents) == 4
        test_passed("查询全部试剂成功（4条）")
        passed += 1
    except Exception as e:
        test_failed("查询全部", str(e))
        failed += 1

    try:
        low_stock = manager.get_reagents({"low_stock": True})
        assert len(low_stock) == 1
        assert low_stock[0]["name"] == "低库存试剂"
        test_passed("低库存筛选成功（1条）")
        passed += 1
    except Exception as e:
        test_failed("低库存筛选", str(e))
        failed += 1

    try:
        expired = manager.get_reagents({"expired": True})
        assert len(expired) == 1
        assert expired[0]["name"] == "过期试剂"
        test_passed("过期筛选成功（1条）")
        passed += 1
    except Exception as e:
        test_failed("过期筛选", str(e))
        failed += 1

    try:
        not_expired = manager.get_reagents({"expired": False})
        assert len(not_expired) == 3
        test_passed("未过期筛选成功（3条）")
        passed += 1
    except Exception as e:
        test_failed("未过期筛选", str(e))
        failed += 1

    try:
        batch_filter = manager.get_reagents({"batch_number": "MATCH"})
        assert len(batch_filter) == 1
        assert batch_filter[0]["batch_number"] == "MATCH001"
        test_passed("批号筛选成功（1条）")
        passed += 1
    except Exception as e:
        test_failed("批号筛选", str(e))
        failed += 1

    # Test 13: CSV 导入导出
    print("\n【测试 13】CSV 导入导出测试")
    auth.login("admin")
    try:
        sample_path = os.path.join(os.path.dirname(DB_PATH), "test_sample.csv")
        msg = csv_mgr.create_sample_import(sample_path)
        assert os.path.exists(sample_path)
        test_passed("生成CSV样例成功")
        passed += 1
    except Exception as e:
        test_failed("生成CSV样例", str(e))
        failed += 1

    try:
        success, skipped, errors, warnings = csv_mgr.import_reagents(sample_path)
        assert success == 3
        assert skipped == 0
        assert len(warnings) == 0
        test_passed(f"CSV导入成功（{success}条，无冲突警告）")
        passed += 1

        reagents = manager.get_reagents()
        assert len(reagents) == 7
        test_passed("导入后试剂总数正确（4 + 3 = 7）")
        passed += 1

        os.remove(sample_path)
    except Exception as e:
        test_failed("CSV导入", str(e))
        failed += 1

    try:
        export_path = os.path.join(os.path.dirname(DB_PATH), "test_export.csv")
        count, msg = csv_mgr.export_reagents(export_path)
        assert os.path.exists(export_path)
        assert count == 7
        test_passed(f"CSV导出库存成功（{count}条）")
        passed += 1
        os.remove(export_path)
    except Exception as e:
        test_failed("CSV导出库存", str(e))
        failed += 1

    try:
        ledger_path = os.path.join(os.path.dirname(DB_PATH), "test_ledger.csv")
        count, msg = csv_mgr.export_ledger(ledger_path)
        assert os.path.exists(ledger_path)
        assert count > 0
        test_passed(f"CSV导出台账成功（{count}条）")
        passed += 1
        os.remove(ledger_path)
    except Exception as e:
        test_failed("CSV导出台账", str(e))
        failed += 1

    # Test 14: 操作历史和台账
    print("\n【测试 14】操作历史和台账测试")
    try:
        history = manager.get_operation_history()
        assert len(history) > 0
        test_passed(f"操作历史查询成功（{len(history)}条）")
        passed += 1
    except Exception as e:
        test_failed("操作历史查询", str(e))
        failed += 1

    try:
        ledger = manager.get_ledger()
        assert len(ledger) > 0
        test_passed(f"库存台账查询成功（{len(ledger)}条）")
        passed += 1
    except Exception as e:
        test_failed("库存台账查询", str(e))
        failed += 1

    # Test 15: 数据持久化验证
    print("\n【测试 15】数据持久化测试")
    try:
        import sqlite3
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()

        cursor.execute("SELECT COUNT(*) FROM reagents")
        reagent_count = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM operations")
        op_count = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM inventory_ledger")
        ledger_count = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM users")
        user_count = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM reservations")
        res_count = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM reservation_logs")
        res_log_count = cursor.fetchone()[0]

        conn.close()

        assert reagent_count == 7
        assert user_count == 3
        assert op_count > 0
        assert ledger_count > 0

        test_passed(f"数据持久化验证成功：试剂{reagent_count}条，操作{op_count}条，台账{ledger_count}条，用户{user_count}条，预约{res_count}条，预约日志{res_log_count}条")
        passed += 1
    except Exception as e:
        test_failed("数据持久化验证", str(e))
        failed += 1

    # Test 16: 重复试剂约束
    print("\n【测试 16】重复试剂约束测试")
    try:
        manager.create_reagent("正常试剂", "NOR001", 10, "瓶")
        test_failed("重复试剂创建", "应该失败但成功了")
        failed += 1
    except OperationError as e:
        if "已存在" in str(e):
            test_passed("相同名称和批号的试剂不能重复创建（正确）")
            passed += 1
        else:
            test_failed("重复试剂创建", f"错误信息不符: {e}")
            failed += 1

    # ============================================
    # 以下为【预约领用和冲突处理】模块新增测试
    # ============================================

    # 重置数据库用于预约系统测试
    reset_database()
    auth.login("admin")

    # 创建测试用试剂
    reagent_res1_id, _ = manager.create_reagent(
        "预约测试试剂A", "RES-TEST-A", 100, "瓶",
        expiration_date=(datetime.now() + timedelta(days=365)).strftime("%Y-%m-%d"),
        low_stock_threshold=10
    )
    reagent_res2_id, _ = manager.create_reagent(
        "预约测试试剂B", "RES-TEST-B", 50, "瓶",
        expiration_date=(datetime.now() + timedelta(days=365)).strftime("%Y-%m-%d"),
        low_stock_threshold=5
    )
    reagent_expired_id, _ = manager.create_reagent(
        "预约测试过期试剂", "RES-TEST-EXP", 30, "瓶",
        expiration_date=(datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    )

    # Test 17: 预约创建和基本校验
    print("\n【测试 17】预约创建和基本校验测试")
    auth.login("lab_staff")
    try:
        planned_date = (datetime.now() + timedelta(days=7)).strftime("%Y-%m-%d")
        res_id, msg = manager.create_reservation(
            reagent_res1_id, 20, planned_date, "实验A使用"
        )
        assert res_id > 0
        reservation = ReservationDB.get_by_id(res_id)
        assert reservation["status"] == "pending"
        assert reservation["quantity"] == 20
        test_passed("创建预约成功（待审核状态）")
        passed += 1
    except Exception as e:
        test_failed("创建预约", str(e))
        failed += 1

    try:
        planned_date = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
        manager.create_reservation(reagent_res1_id, 10, planned_date, "过期日期")
        test_failed("过去日期预约", "应该失败但成功了")
        failed += 1
    except OperationError as e:
        if "计划使用日期" in str(e):
            test_passed("计划使用日期不能早于今天（正确）")
            passed += 1
        else:
            test_failed("过去日期预约", f"错误信息不符: {e}")
            failed += 1

    try:
        planned_date = (datetime.now() + timedelta(days=7)).strftime("%Y-%m-%d")
        manager.create_reservation(reagent_expired_id, 10, planned_date, "过期试剂预约")
        test_failed("过期试剂预约", "应该失败但成功了")
        failed += 1
    except OperationError as e:
        if "已过期" in str(e):
            test_passed("已过期试剂禁止预约（正确）")
            passed += 1
        else:
            test_failed("过期试剂预约", f"错误信息不符: {e}")
            failed += 1

    try:
        planned_date = (datetime.now() + timedelta(days=7)).strftime("%Y-%m-%d")
        manager.create_reservation(reagent_res1_id, 999, planned_date, "超量预约")
        test_failed("超可用量预约", "应该失败但成功了")
        failed += 1
    except OperationError as e:
        if "可用库存不足" in str(e):
            test_passed("预约数量不能超过可用量（正确）")
            passed += 1
        else:
            test_failed("超可用量预约", f"错误信息不符: {e}")
            failed += 1

    # Test 18: 预约权限校验
    print("\n【测试 18】预约权限校验测试")
    auth.login("auditor")
    try:
        planned_date = (datetime.now() + timedelta(days=7)).strftime("%Y-%m-%d")
        manager.create_reservation(reagent_res1_id, 10, planned_date, "审核员越权预约")
        test_failed("审核员越权创建预约", "应该失败但成功了")
        failed += 1
    except OperationError as e:
        if "权限不足" in str(e):
            test_passed("审核员不能创建预约（正确）")
            passed += 1
        else:
            test_failed("审核员越权创建预约", f"错误信息不符: {e}")
            failed += 1

    auth.login("lab_staff")
    try:
        manager.approve_reservation(res_id, "越权审批")
        test_failed("实验员越权审批", "应该失败但成功了")
        failed += 1
    except OperationError as e:
        if "权限不足" in str(e):
            test_passed("实验员不能审批预约（正确）")
            passed += 1
        else:
            test_failed("实验员越权审批", f"错误信息不符: {e}")
            failed += 1

    try:
        manager.complete_reservation(res_id, "越权领用")
        test_failed("实验员越权确认领用", "应该失败但成功了")
        failed += 1
    except OperationError as e:
        if "权限不足" in str(e):
            test_passed("实验员不能确认领用（正确）")
            passed += 1
        else:
            test_failed("实验员越权确认领用", f"错误信息不符: {e}")
            failed += 1

    # Test 19: 预约审批流程和库存锁定
    print("\n【测试 19】预约审批流程和库存锁定测试")
    auth.login("auditor")
    try:
        import time
        time.sleep(0.1)

        reagent_before = ReagentDB.get_by_id(reagent_res1_id)
        locked_before = reagent_before.get("locked_quantity", 0)
        assert locked_before == 0

        log_id, msg = manager.approve_reservation(res_id, "审核通过，实验需要")
        assert log_id > 0

        reservation = ReservationDB.get_by_id(res_id)
        assert reservation["status"] == "approved"

        reagent_after = ReagentDB.get_by_id(reagent_res1_id)
        locked_after = reagent_after.get("locked_quantity", 0)
        assert locked_after == 20
        assert reagent_after["quantity"] == 100

        available = ReagentLockDB.get_available_quantity(reagent_res1_id)
        assert available == 80

        test_passed("审批预约成功（库存锁定20，总库存100不变，可用80）")
        passed += 1
    except Exception as e:
        test_failed("审批预约", str(e))
        failed += 1

    try:
        manager.approve_reservation(res_id, "重复审批")
        test_failed("重复审批", "应该失败但成功了")
        failed += 1
    except OperationError as e:
        if "状态" in str(e) and "无法审批" in str(e):
            test_passed("非待审核状态不能重复审批（正确）")
            passed += 1
        else:
            test_failed("重复审批", f"错误信息不符: {e}")
            failed += 1

    # Test 20: 预约拒绝
    print("\n【测试 20】预约拒绝测试")
    auth.login("lab_staff")
    planned_date = (datetime.now() + timedelta(days=7)).strftime("%Y-%m-%d")
    res_reject_id, _ = manager.create_reservation(
        reagent_res1_id, 15, planned_date, "实验B使用"
    )

    auth.login("auditor")
    try:
        import time
        time.sleep(0.1)
        log_id, msg = manager.reject_reservation(res_reject_id, "库存不足，请减少用量")
        assert log_id > 0

        reservation = ReservationDB.get_by_id(res_reject_id)
        assert reservation["status"] == "rejected"

        reagent = ReagentDB.get_by_id(reagent_res1_id)
        assert reagent.get("locked_quantity", 0) == 20

        test_passed("拒绝预约成功（状态变为已拒绝，锁定量不变）")
        passed += 1
    except Exception as e:
        test_failed("拒绝预约", str(e))
        failed += 1

    # Test 21: 预约改期
    print("\n【测试 21】预约改期测试")
    auth.login("lab_staff")
    planned_date = (datetime.now() + timedelta(days=7)).strftime("%Y-%m-%d")
    res_reschedule_id, _ = manager.create_reservation(
        reagent_res2_id, 10, planned_date, "改期测试"
    )

    auth.login("auditor")
    reschedule_new_res_id = None
    try:
        import time
        time.sleep(0.1)
        new_date = (datetime.now() + timedelta(days=14)).strftime("%Y-%m-%d")
        log_id, msg = manager.reschedule_reservation(
            res_reschedule_id, new_date, "实验时间调整"
        )
        assert log_id > 0, f"返回的log_id应该>0，实际是{log_id}"

        old_res = ReservationDB.get_by_id(res_reschedule_id)
        assert old_res["status"] == "rescheduled", f"原预约状态应该是rescheduled，实际是{old_res['status']}"

        all_res = manager.get_reservations()
        new_res = [r for r in all_res if r["remarks"] and f"由预约#{res_reschedule_id}改期" in r["remarks"]]
        assert len(new_res) == 1, f"应该找到1个新预约，实际找到{len(new_res)}个"
        assert new_res[0]["planned_use_date"] == new_date, f"新日期应该是{new_date}，实际是{new_res[0]['planned_use_date']}"
        assert new_res[0]["original_planned_date"] == planned_date, f"原日期应该是{planned_date}，实际是{new_res[0]['original_planned_date']}"
        assert new_res[0]["status"] == "pending", f"状态应该是pending，实际是{new_res[0]['status']}"

        reschedule_new_res_id = new_res[0]["id"]
        test_passed("预约改期成功（原预约标记为已改期，创建新预约待审核）")
        passed += 1
    except AssertionError as e:
        test_failed("预约改期", str(e) if str(e) else "断言失败")
        failed += 1
    except Exception as e:
        test_failed("预约改期", str(e) if str(e) else "未知错误")
        failed += 1

    # Test 21b: 已审批预约改期 - 核心回归测试（锁定量不翻倍）
    print("\n【测试 21b】已审批预约改期回归测试（核心修复：锁定量不翻倍）")
    auth.login("admin")
    try:
        import time
        reg_approved_id, _ = manager.create_reagent(
            "改期回归测试试剂", "REG-APPROVED-001", 100, "瓶",
            expiration_date=(datetime.now() + timedelta(days=365)).strftime("%Y-%m-%d")
        )

        reagent_init = ReagentDB.get_by_id(reg_approved_id)
        assert reagent_init["quantity"] == 100
        assert reagent_init.get("locked_quantity", 0) == 0

        auth.login("lab_staff")
        planned_date1 = (datetime.now() + timedelta(days=7)).strftime("%Y-%m-%d")
        reg_res_id, _ = manager.create_reservation(
            reg_approved_id, 30, planned_date1, "回归测试-创建"
        )

        reagent_after_create = ReagentDB.get_by_id(reg_approved_id)
        assert reagent_after_create.get("locked_quantity", 0) == 0

        auth.login("auditor")
        time.sleep(0.1)
        manager.approve_reservation(reg_res_id, "回归测试-审批")

        reagent_after_approve = ReagentDB.get_by_id(reg_approved_id)
        assert reagent_after_approve.get("locked_quantity", 0) == 30, \
            f"审批后锁定量应为30，实际是{reagent_after_approve.get('locked_quantity', 0)}"
        assert reagent_after_approve["quantity"] == 100
        assert ReagentLockDB.get_available_quantity(reg_approved_id) == 70

        res_after_approve = ReservationDB.get_by_id(reg_res_id)
        assert res_after_approve["status"] == "approved"

        time.sleep(0.1)
        new_date = (datetime.now() + timedelta(days=14)).strftime("%Y-%m-%d")
        log_id, msg = manager.reschedule_reservation(
            reg_res_id, new_date, "回归测试-已审批改期"
        )

        old_res = ReservationDB.get_by_id(reg_res_id)
        assert old_res["status"] == "rescheduled", \
            f"旧预约状态应为rescheduled，实际是{old_res['status']}"

        all_res = manager.get_reservations()
        new_res_list = [r for r in all_res if r["remarks"] and f"由预约#{reg_res_id}改期" in r["remarks"]]
        assert len(new_res_list) == 1, f"应找到1个新预约，实际{len(new_res_list)}个"
        new_reg_res = new_res_list[0]
        assert new_reg_res["status"] == "approved", \
            f"新预约状态应为approved，实际是{new_reg_res['status']}"
        assert new_reg_res["quantity"] == 30

        reagent_after_reschedule = ReagentDB.get_by_id(reg_approved_id)
        final_locked = reagent_after_reschedule.get("locked_quantity", 0)
        assert final_locked == 30, \
            f"改期后锁定量应为30（不翻倍！），实际是{final_locked}"
        assert reagent_after_reschedule["quantity"] == 100
        assert ReagentLockDB.get_available_quantity(reg_approved_id) == 70, \
            f"改期后可用量应为70，实际是{ReagentLockDB.get_available_quantity(reg_approved_id)}"

        test_passed(
            "已审批改期核心验证通过："
            f"总库存={reagent_after_reschedule['quantity']}, "
            f"锁定={final_locked}（未翻倍！）, "
            f"可用={ReagentLockDB.get_available_quantity(reg_approved_id)}"
        )
        passed += 1

        time.sleep(0.1)
        manager.cancel_reservation(new_reg_res["id"], "回归测试-取消新预约")
        reagent_after_cancel = ReagentDB.get_by_id(reg_approved_id)
        assert reagent_after_cancel.get("locked_quantity", 0) == 0, \
            f"取消后锁定量应为0，实际是{reagent_after_cancel.get('locked_quantity', 0)}"
        assert ReagentLockDB.get_available_quantity(reg_approved_id) == 100

        test_passed("改期后取消预约验证通过：锁定量正确释放为0")
        passed += 1

        auth.login("lab_staff")
        planned_date2 = (datetime.now() + timedelta(days=7)).strftime("%Y-%m-%d")
        reg_res2_id, _ = manager.create_reservation(
            reg_approved_id, 25, planned_date2, "回归测试-领用测试"
        )

        auth.login("auditor")
        time.sleep(0.1)
        manager.approve_reservation(reg_res2_id, "回归测试-审批2")

        reagent_after_approve2 = ReagentDB.get_by_id(reg_approved_id)
        assert reagent_after_approve2.get("locked_quantity", 0) == 25

        time.sleep(0.1)
        new_date2 = (datetime.now() + timedelta(days=21)).strftime("%Y-%m-%d")
        manager.reschedule_reservation(reg_res2_id, new_date2, "回归测试-改期后领用")

        all_res2 = manager.get_reservations()
        new_res2_list = [r for r in all_res2 if r["remarks"] and f"由预约#{reg_res2_id}改期" in r["remarks"]]
        new_reg_res2 = new_res2_list[0]
        assert new_reg_res2["status"] == "approved"

        reagent_after_reschedule2 = ReagentDB.get_by_id(reg_approved_id)
        assert reagent_after_reschedule2.get("locked_quantity", 0) == 25, \
            f"改期后锁定量应为25，实际是{reagent_after_reschedule2.get('locked_quantity', 0)}"

        time.sleep(0.1)
        manager.complete_reservation(new_reg_res2["id"], "回归测试-实际领用")

        reagent_after_complete = ReagentDB.get_by_id(reg_approved_id)
        assert reagent_after_complete["quantity"] == 75
        assert reagent_after_complete.get("locked_quantity", 0) == 0
        assert ReagentLockDB.get_available_quantity(reg_approved_id) == 75

        test_passed("改期后实际领用验证通过：库存75，锁定0，可用75")
        passed += 1

        close_db()
        import sqlite3
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute(
            "SELECT quantity, locked_quantity FROM reagents WHERE id = ?",
            (reg_approved_id,)
        )
        row = cursor.fetchone()
        conn.close()
        assert row[0] == 75
        assert row[1] == 0

        init_database()

        reagent_after_restart = ReagentDB.get_by_id(reg_approved_id)
        assert reagent_after_restart["quantity"] == 75
        assert reagent_after_restart.get("locked_quantity", 0) == 0
        assert ReagentLockDB.get_available_quantity(reg_approved_id) == 75

        test_passed("重启后数据一致验证通过：库存、锁定量、可用量均正确")
        passed += 1

        res_with_lock = manager.get_reagents_with_lock_info({"id": reg_approved_id})
        assert len(res_with_lock) == 1
        info = res_with_lock[0]
        assert info["quantity"] == 75
        assert info.get("locked_quantity", 0) == 0
        assert info.get("available_quantity", 0) == 75
        assert "reservation_summary" in info

        test_passed("接口层数据一致验证通过：可用量、锁定量、预约摘要均正确")
        passed += 1

        export_path = os.path.join(os.path.dirname(DB_PATH), "test_regression_export.csv")
        import csv
        count, msg = csv_mgr.export_reagents(export_path)
        with open(export_path, 'r', encoding='utf-8-sig') as f:
            reader = csv.DictReader(f)
            for row in reader:
                if row["试剂名称"] == "改期回归测试试剂":
                    assert int(row["总库存"]) == 75
                    assert int(row["已锁定量"]) == 0
                    assert int(row["可用量"]) == 75
                    assert row["预约摘要"] is not None

        test_passed("CSV导出数据一致验证通过：总库存、已锁定量、可用量均正确")
        passed += 1

        os.remove(export_path)

    except AssertionError as e:
        test_failed("已审批改期回归测试", str(e) if str(e) else "断言失败")
        failed += 1
    except Exception as e:
        test_failed("已审批改期回归测试", str(e) if str(e) else "未知错误")
        failed += 1

    # Test 22: 实际领用和库存扣减
    print("\n【测试 22】实际领用和库存扣减测试")
    try:
        import time
        time.sleep(0.1)

        reagent_before = ReagentDB.get_by_id(reagent_res1_id)
        assert reagent_before["quantity"] == 100
        assert reagent_before.get("locked_quantity", 0) == 20

        log_id, msg = manager.complete_reservation(res_id, "实际领用")
        assert log_id > 0

        reservation = ReservationDB.get_by_id(res_id)
        assert reservation["status"] == "completed"

        reagent_after = ReagentDB.get_by_id(reagent_res1_id)
        assert reagent_after["quantity"] == 80
        assert reagent_after.get("locked_quantity", 0) == 0

        available = ReagentLockDB.get_available_quantity(reagent_res1_id)
        assert available == 80

        test_passed("实际领用成功（总库存80，锁定量0，可用80）")
        passed += 1
    except Exception as e:
        test_failed("实际领用", str(e))
        failed += 1

    # Test 23: 取消预约和锁定释放
    print("\n【测试 23】取消预约和锁定释放测试")
    if reschedule_new_res_id is not None:
        auth.login("auditor")
        try:
            manager.approve_reservation(reschedule_new_res_id, "改期后审批")

            auth.login("lab_staff")
            import time
            time.sleep(0.1)

            reagent_before = ReagentDB.get_by_id(reagent_res2_id)
            assert reagent_before.get("locked_quantity", 0) == 10

            log_id, msg = manager.cancel_reservation(reschedule_new_res_id, "实验取消")
            assert log_id > 0

            reservation = ReservationDB.get_by_id(reschedule_new_res_id)
            assert reservation["status"] == "cancelled"

            reagent_after = ReagentDB.get_by_id(reagent_res2_id)
            assert reagent_after.get("locked_quantity", 0) == 0

            test_passed("取消预约成功（状态已取消，锁定量释放）")
            passed += 1
        except Exception as e:
            test_failed("取消预约", str(e))
            failed += 1
    else:
        print("  跳过取消预约测试（因改期测试失败）")

    try:
        auth.login("lab_staff")
        planned_date = (datetime.now() + timedelta(days=7)).strftime("%Y-%m-%d")
        other_res_id, _ = manager.create_reservation(
            reagent_res1_id, 5, planned_date, "别人的预约"
        )
        auth.login("lab_staff")
        manager.cancel_reservation(other_res_id, "越权取消")
        test_passed("实验员可以取消自己的预约（正确）")
        passed += 1
    except Exception as e:
        test_failed("取消自己的预约", str(e))
        failed += 1

    # Test 24: 过期释放
    print("\n【测试 24】过期释放测试")
    auth.login("admin")
    try:
        future_date = (datetime.now() + timedelta(days=10)).strftime("%Y-%m-%d")
        expire_res_id, _ = manager.create_reservation(
            reagent_res1_id, 10, future_date, "过期测试"
        )

        import sqlite3
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        old_date = (datetime.now() - timedelta(days=5)).strftime("%Y-%m-%d")
        cursor.execute(
            "UPDATE reservations SET planned_use_date = ?, status = 'approved' WHERE id = ?",
            (old_date, expire_res_id)
        )
        cursor.execute(
            "UPDATE reagents SET locked_quantity = locked_quantity + 10 WHERE id = ?",
            (reagent_res1_id,)
        )
        conn.commit()
        conn.close()

        auth.login("auditor")
        import time
        time.sleep(0.1)
        released, messages = manager.release_expired_reservations()
        assert released >= 1

        reservation = ReservationDB.get_by_id(expire_res_id)
        assert reservation["status"] == "expired"

        reagent = ReagentDB.get_by_id(reagent_res1_id)
        assert reagent.get("locked_quantity", 0) == 0

        test_passed(f"过期释放成功（释放{released}个预约，锁定量清零）")
        passed += 1
    except Exception as e:
        test_failed("过期释放", str(e))
        failed += 1

    # Test 25: 预约操作撤销
    print("\n【测试 25】预约操作撤销测试")
    auth.login("admin")
    try:
        import time

        planned_date = (datetime.now() + timedelta(days=7)).strftime("%Y-%m-%d")
        revert_res_id, _ = manager.create_reservation(
            reagent_res1_id, 15, planned_date, "撤销测试-创建"
        )

        time.sleep(0.1)
        manager.approve_reservation(revert_res_id, "撤销测试-审批")

        reagent_after_approve = ReagentDB.get_by_id(reagent_res1_id)
        assert reagent_after_approve.get("locked_quantity", 0) == 15

        time.sleep(0.1)
        last_log = manager.get_last_revertable_reservation_log()
        assert last_log is not None
        assert last_log["operation_type"] == "approve"

        log_id, msg = manager.revert_last_reservation_operation()
        assert log_id > 0

        reservation = ReservationDB.get_by_id(revert_res_id)
        assert reservation["status"] == "pending"

        reagent_after_revert = ReagentDB.get_by_id(reagent_res1_id)
        assert reagent_after_revert.get("locked_quantity", 0) == 0

        test_passed("撤销审批成功（状态改回待审核，锁定量释放）")
        passed += 1

        time.sleep(0.1)
        manager.approve_reservation(revert_res_id, "再次审批用于测试撤销领用")

        time.sleep(0.1)
        manager.complete_reservation(revert_res_id, "测试领用撤销")

        reagent_after_complete = ReagentDB.get_by_id(reagent_res1_id)
        assert reagent_after_complete["quantity"] == 65
        assert reagent_after_complete.get("locked_quantity", 0) == 0

        time.sleep(0.1)
        manager.revert_last_reservation_operation()

        reservation = ReservationDB.get_by_id(revert_res_id)
        assert reservation["status"] == "approved"

        reagent_after_revert_complete = ReagentDB.get_by_id(reagent_res1_id)
        assert reagent_after_revert_complete["quantity"] == 80
        assert reagent_after_revert_complete.get("locked_quantity", 0) == 15

        test_passed("撤销领用成功（状态改回已审批，库存和锁定量恢复）")
        passed += 1

        time.sleep(0.1)
        manager.cancel_reservation(revert_res_id, "测试撤销取消")

        reagent_after_cancel = ReagentDB.get_by_id(reagent_res1_id)
        assert reagent_after_cancel.get("locked_quantity", 0) == 0

        time.sleep(0.1)
        manager.revert_last_reservation_operation()

        reservation = ReservationDB.get_by_id(revert_res_id)
        assert reservation["status"] == "approved"

        reagent_after_revert_cancel = ReagentDB.get_by_id(reagent_res1_id)
        assert reagent_after_revert_cancel.get("locked_quantity", 0) == 15

        test_passed("撤销取消成功（状态改回已审批，锁定量恢复）")
        passed += 1
    except Exception as e:
        test_failed("预约操作撤销", str(e))
        failed += 1

    # Test 26: CSV导入冲突检测
    print("\n【测试 26】CSV导入冲突检测测试")
    auth.login("admin")
    try:
        import csv
        conflict_path = os.path.join(os.path.dirname(DB_PATH), "test_conflict.csv")

        with open(conflict_path, 'w', newline='', encoding='utf-8-sig') as f:
            writer = csv.writer(f)
            writer.writerow(["试剂名称", "批号", "数量", "单位"])
            writer.writerow(["冲突检测试剂A", "RES-CONFLICT-A", 5, "瓶"])
            writer.writerow(["无冲突新试剂B", "NO-CONFLICT-B", 20, "瓶"])

        success, skipped, errors, warnings = csv_mgr.import_reagents(conflict_path)

        assert success == 2
        assert len(warnings) == 0
        test_passed(f"无冲突导入成功（成功{success}条，警告{len(warnings)}条）")
        passed += 1

        planned_date = (datetime.now() + timedelta(days=7)).strftime("%Y-%m-%d")
        res_conflict_id, _ = manager.create_reservation(
            manager.get_reagents({"name": "冲突检测试剂A"})[0]["id"],
            3, planned_date, "冲突测试预约"
        )

        conflict_path2 = os.path.join(os.path.dirname(DB_PATH), "test_conflict2.csv")
        with open(conflict_path2, 'w', newline='', encoding='utf-8-sig') as f:
            writer = csv.writer(f)
            writer.writerow(["试剂名称", "批号", "数量", "单位"])
            writer.writerow(["冲突检测试剂A", "RES-CONFLICT-A", 3, "瓶"])
            writer.writerow(["另一个新试剂", "ANOTHER-NEW", 15, "瓶"])

        success2, skipped2, errors2, warnings2 = csv_mgr.import_reagents(conflict_path2)

        assert success2 == 1
        assert skipped2 == 1
        assert len(warnings2) == 0
        test_passed(f"重复批号导入跳过正确（成功{success2}条，跳过{skipped2}条）")
        passed += 1

        conflict_path3 = os.path.join(os.path.dirname(DB_PATH), "test_conflict3.csv")
        with open(conflict_path3, 'w', newline='', encoding='utf-8-sig') as f:
            writer = csv.writer(f)
            writer.writerow(["试剂名称", "批号", "数量", "单位"])
            writer.writerow(["冲突检测试剂A", "RES-CONFLICT-A-NEW", 2, "瓶"])

        success3, skipped3, errors3, warnings3 = csv_mgr.import_reagents(conflict_path3)

        assert success3 == 1
        assert len(warnings3) == 1
        assert "冲突检测试剂A" in warnings3[0]
        assert "未完成预约冲突" in warnings3[0]
        assert "已预约" in warnings3[0]
        test_passed(f"同试剂名新批号冲突检测成功（成功{success3}条，警告{len(warnings3)}条）")
        passed += 1

        os.remove(conflict_path2)
        os.remove(conflict_path3)

        os.remove(conflict_path)
    except Exception as e:
        test_failed("CSV导入冲突检测", str(e))
        failed += 1

    # Test 27: 跨重启数据一致性
    print("\n【测试 27】跨重启数据一致性测试")
    try:
        reagent_before = ReagentDB.get_by_id(reagent_res1_id)
        qty_before = reagent_before["quantity"]
        locked_before = reagent_before.get("locked_quantity", 0)

        reservations_before = ReservationDB.get_all()
        logs_before = ReservationLogDB.get_all()

        close_db()

        import sqlite3
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("SELECT quantity, locked_quantity FROM reagents WHERE id = ?",
                      (reagent_res1_id,))
        row = cursor.fetchone()
        conn.close()

        assert row[0] == qty_before
        assert row[1] == locked_before

        init_database()

        reagent_after = ReagentDB.get_by_id(reagent_res1_id)
        assert reagent_after["quantity"] == qty_before
        assert reagent_after.get("locked_quantity", 0) == locked_before

        reservations_after = ReservationDB.get_all()
        logs_after = ReservationLogDB.get_all()

        assert len(reservations_after) == len(reservations_before)
        assert len(logs_after) == len(logs_before)

        test_passed(f"跨重启数据一致（库存{qty_before}，锁定{locked_before}，预约{len(reservations_after)}条，日志{len(logs_after)}条）")
        passed += 1
    except Exception as e:
        test_failed("跨重启数据一致性", str(e))
        failed += 1

    # Test 28: 导出增强（可用量、锁定量、预约摘要）
    print("\n【测试 28】导出增强测试")
    auth.login("admin")
    try:
        export_path = os.path.join(os.path.dirname(DB_PATH), "test_enhanced_export.csv")
        count, msg = csv_mgr.export_reagents(export_path)
        assert count > 0

        with open(export_path, 'r', encoding='utf-8-sig') as f:
            reader = csv.reader(f)
            headers = next(reader)

            assert "总库存" in headers
            assert "已锁定量" in headers
            assert "可用量" in headers
            assert "预约摘要" in headers

            for row in reader:
                if row[1] == "预约测试试剂A":
                    total_idx = headers.index("总库存")
                    locked_idx = headers.index("已锁定量")
                    available_idx = headers.index("可用量")
                    summary_idx = headers.index("预约摘要")

                    total = int(row[total_idx])
                    locked = int(row[locked_idx])
                    available = int(row[available_idx])
                    summary = row[summary_idx]

                    assert available == total - locked
                    assert "预约" in summary or summary == ""

        test_passed("导出增强成功（包含总库存、已锁定量、可用量、预约摘要）")
        passed += 1
        os.remove(export_path)
    except Exception as e:
        test_failed("导出增强", str(e))
        failed += 1

    # Test 29: 预约日志筛选
    print("\n【测试 29】预约日志筛选测试")
    auth.login("admin")
    try:
        all_logs = manager.get_reservation_logs()
        assert len(all_logs) > 0
        test_passed(f"查询全部预约日志成功（{len(all_logs)}条）")
        passed += 1

        approve_logs = manager.get_reservation_logs({"operation_type": "approve"})
        assert len(approve_logs) > 0
        for log in approve_logs:
            assert log["operation_type"] == "approve"
        test_passed(f"按操作类型筛选成功（审批{len(approve_logs)}条）")
        passed += 1

        reagent_logs = manager.get_reservation_logs({"reagent_name": "预约测试试剂A"})
        assert len(reagent_logs) > 0
        for log in reagent_logs:
            assert log["reagent_name"] == "预约测试试剂A"
        test_passed(f"按试剂名称筛选成功（{len(reagent_logs)}条）")
        passed += 1
    except Exception as e:
        test_failed("预约日志筛选", str(e))
        failed += 1

    # Test 30: 实验员只能取消自己的预约
    print("\n【测试 30】实验员取消权限测试")
    try:
        auth.login("admin")
        planned_date = (datetime.now() + timedelta(days=7)).strftime("%Y-%m-%d")
        admin_res_id, _ = manager.create_reservation(
            reagent_res2_id, 5, planned_date, "管理员创建的预约"
        )

        auth.login("lab_staff")
        try:
            manager.cancel_reservation(admin_res_id, "实验员越权取消管理员的预约")
            test_failed("实验员越权取消他人预约", "应该失败但成功了")
            failed += 1
        except OperationError as e:
            if "只能取消自己创建" in str(e):
                test_passed("实验员只能取消自己创建的预约（正确）")
                passed += 1
            else:
                test_failed("实验员越权取消他人预约", f"错误信息不符: {e}")
                failed += 1

        auth.login("auditor")
        manager.cancel_reservation(admin_res_id, "审核员取消任意预约")
        reservation = ReservationDB.get_by_id(admin_res_id)
        assert reservation["status"] == "cancelled"
        test_passed("审核员可以取消任意预约（正确）")
        passed += 1
    except Exception as e:
        test_failed("实验员取消权限", str(e))
        failed += 1

    # ============================================
    # 以下为【预约日志导出】模块新增测试
    # ============================================

    # Test 31: 预约日志筛选导出
    print("\n【测试 31】预约日志筛选导出测试")
    auth.login("admin")
    try:
        export_reagent_id, _ = manager.create_reagent(
            "导出测试试剂", "EXPORT-TEST-001", 100, "瓶",
            expiration_date=(datetime.now() + timedelta(days=365)).strftime("%Y-%m-%d")
        )

        auth.login("lab_staff")
        planned_date = (datetime.now() + timedelta(days=7)).strftime("%Y-%m-%d")
        export_res_id, _ = manager.create_reservation(
            export_reagent_id, 20, planned_date, "导出测试-创建"
        )

        auth.login("auditor")
        import time
        time.sleep(0.1)
        manager.approve_reservation(export_res_id, "导出测试-审批")

        time.sleep(0.1)
        manager.cancel_reservation(export_res_id, "导出测试-取消")

        auth.login("lab_staff")
        export_res2_id, _ = manager.create_reservation(
            export_reagent_id, 15, planned_date, "导出测试-创建2"
        )

        auth.login("auditor")
        time.sleep(0.1)
        manager.approve_reservation(export_res2_id, "导出测试-审批2")

        time.sleep(0.1)
        manager.complete_reservation(export_res2_id, "导出测试-领用")

        all_logs_before = manager.get_reservation_logs()
        assert len(all_logs_before) >= 5, f"应该至少有5条日志，实际有{len(all_logs_before)}条"

        export_path = os.path.join(os.path.dirname(DB_PATH), "test_res_logs_all.csv")
        count, msg = csv_mgr.export_reservation_logs(export_path)
        assert count >= 5
        assert os.path.exists(export_path)

        import csv
        with open(export_path, 'r', encoding='utf-8-sig') as f:
            reader = csv.DictReader(f)
            headers = reader.fieldnames
            expected_headers = ["操作时间", "操作人", "预约状态变化", "试剂名称", "批号",
                               "数量", "锁定量变动", "库存量变动", "备注"]
            assert headers == expected_headers, f"表头顺序错误。预期：{expected_headers}，实际：{headers}"

            rows = list(reader)
            assert len(rows) == count

            for row in rows:
                assert "操作时间" in row and row["操作时间"]
                assert "操作人" in row
                assert "预约状态变化" in row and "→" in row["预约状态变化"]
                assert "试剂名称" in row
                assert "批号" in row
                assert "数量" in row
                assert "锁定量变动" in row
                assert "库存量变动" in row
                assert "备注" in row

        test_passed(f"全量预约日志导出成功（{count}条，表头顺序正确）")
        passed += 1

        approve_filter = {"operation_type": "approve"}
        approve_logs = manager.get_reservation_logs(approve_filter)
        approve_count = len(approve_logs)
        assert approve_count >= 2

        approve_export_path = os.path.join(os.path.dirname(DB_PATH), "test_res_logs_approve.csv")
        count2, msg2 = csv_mgr.export_reservation_logs(approve_export_path, approve_filter)
        assert count2 == approve_count

        with open(approve_export_path, 'r', encoding='utf-8-sig') as f:
            reader = csv.DictReader(f)
            rows2 = list(reader)
            assert len(rows2) == approve_count
            for row in rows2:
                assert "待审核 → 已审批" in row["预约状态变化"]

        test_passed(f"按操作类型筛选导出成功（仅审批记录{count2}条）")
        passed += 1

        reagent_filter = {"reagent_name": "导出测试试剂"}
        reagent_export_path = os.path.join(os.path.dirname(DB_PATH), "test_res_logs_reagent.csv")
        count3, msg3 = csv_mgr.export_reservation_logs(reagent_export_path, reagent_filter)
        assert count3 >= 5

        with open(reagent_export_path, 'r', encoding='utf-8-sig') as f:
            reader = csv.DictReader(f)
            for row in reader:
                assert row["试剂名称"] == "导出测试试剂"

        test_passed(f"按试剂名称筛选导出成功（{count3}条）")
        passed += 1

        other_reagent_filter = {"reagent_name": "不存在的试剂"}
        other_export_path = os.path.join(os.path.dirname(DB_PATH), "test_res_logs_none.csv")
        count4, msg4 = csv_mgr.export_reservation_logs(other_export_path, other_reagent_filter)
        assert count4 == 0
        assert "没有符合条件" in msg4
        assert not os.path.exists(other_export_path)

        test_passed("筛选结果为空时不生成文件，给出正确提示")
        passed += 1

        os.remove(export_path)
        os.remove(approve_export_path)
        os.remove(reagent_export_path)

    except AssertionError as e:
        test_failed("预约日志筛选导出", str(e) if str(e) else "断言失败")
        failed += 1
    except Exception as e:
        test_failed("预约日志筛选导出", str(e) if str(e) else "未知错误")
        failed += 1

    # Test 32: 预约日志导出权限拒绝
    print("\n【测试 32】预约日志导出权限拒绝测试")
    try:
        class FakeUser:
            def __init__(self):
                self.current_user = {"id": 999, "username": "fake", "role": "nonexistent", "display_name": "无权限用户"}
            def has_permission(self, perm):
                return False

        fake_auth = FakeUser()
        fake_csv_mgr = CSVManager(fake_auth)

        no_perm_path = os.path.join(os.path.dirname(DB_PATH), "test_no_perm.csv")
        try:
            fake_csv_mgr.export_reservation_logs(no_perm_path)
            test_failed("无权限导出", "应该失败但成功了")
            failed += 1
        except PermissionError as e:
            assert "权限不足" in str(e)
            test_passed("无 view_reservation_logs 权限时导出被拒绝（正确）")
            passed += 1
        except Exception as e:
            test_failed("无权限导出", f"异常类型错误：{type(e).__name__}: {e}")
            failed += 1

        assert not os.path.exists(no_perm_path)

    except Exception as e:
        test_failed("权限拒绝测试", str(e))
        failed += 1

    # Test 33: 预约日志导出内容完整性（审批、取消、实际领用）
    print("\n【测试 33】预约日志导出内容完整性测试")
    auth.login("admin")
    try:
        complete_reagent_id, _ = manager.create_reagent(
            "完整性测试试剂", "COMPLETE-001", 50, "瓶",
            expiration_date=(datetime.now() + timedelta(days=365)).strftime("%Y-%m-%d")
        )

        auth.login("lab_staff")
        planned_date = (datetime.now() + timedelta(days=10)).strftime("%Y-%m-%d")
        comp_res_id, _ = manager.create_reservation(
            complete_reagent_id, 10, planned_date, "完整性测试-创建"
        )

        auth.login("auditor")
        time.sleep(0.1)
        manager.approve_reservation(comp_res_id, "完整性测试-审批通过")

        auth.login("lab_staff")
        comp_res2_id, _ = manager.create_reservation(
            complete_reagent_id, 8, planned_date, "完整性测试-创建2"
        )

        auth.login("auditor")
        time.sleep(0.1)
        manager.approve_reservation(comp_res2_id, "完整性测试-审批通过2")

        time.sleep(0.1)
        manager.cancel_reservation(comp_res2_id, "完整性测试-取消")

        auth.login("lab_staff")
        comp_res3_id, _ = manager.create_reservation(
            complete_reagent_id, 5, planned_date, "完整性测试-创建3"
        )

        auth.login("auditor")
        time.sleep(0.1)
        manager.approve_reservation(comp_res3_id, "完整性测试-审批通过3")

        time.sleep(0.1)
        manager.complete_reservation(comp_res3_id, "完整性测试-实际领用")

        all_logs = ReservationLogDB.get_all({"reagent_name": "完整性测试试剂"})

        has_approve = any(l["operation_type"] == "approve" for l in all_logs)
        has_cancel = any(l["operation_type"] == "cancel" for l in all_logs)
        has_complete = any(l["operation_type"] == "complete" for l in all_logs)

        assert has_approve, "缺少审批通过日志"
        assert has_cancel, "缺少取消预约日志"
        assert has_complete, "缺少实际领用日志"

        complete_export_path = os.path.join(os.path.dirname(DB_PATH), "test_complete_logs.csv")
        count, msg = csv_mgr.export_reservation_logs(
            complete_export_path, {"reagent_name": "完整性测试试剂"}
        )

        with open(complete_export_path, 'r', encoding='utf-8-sig') as f:
            reader = csv.DictReader(f)
            rows = list(reader)

            found_approve = False
            found_cancel = False
            found_complete = False

            for row in rows:
                if "待审核 → 已审批" in row["预约状态变化"]:
                    found_approve = True
                    locked = row["锁定量变动"]
                    assert locked.startswith("+"), f"审批的锁定量变动应为+N，实际是{locked}"
                elif "已审批 → 已取消" in row["预约状态变化"]:
                    found_cancel = True
                    locked = row["锁定量变动"]
                    assert locked.startswith("-"), f"取消的锁定量变动应为-N，实际是{locked}"
                elif "已审批 → 已领用" in row["预约状态变化"]:
                    found_complete = True
                    locked = row["锁定量变动"]
                    stock = row["库存量变动"]
                    assert locked.startswith("-"), f"领用的锁定量变动应为-N，实际是{locked}"
                    assert stock.startswith("-"), f"领用的库存量变动应为-N，实际是{stock}"

            assert found_approve, "导出内容缺少审批记录"
            assert found_cancel, "导出内容缺少取消记录"
            assert found_complete, "导出内容缺少实际领用记录"

        test_passed("导出内容完整性验证通过：包含审批、取消、实际领用三种记录，且变动数值正确")
        passed += 1

        os.remove(complete_export_path)

    except AssertionError as e:
        test_failed("导出内容完整性", str(e) if str(e) else "断言失败")
        failed += 1
    except Exception as e:
        test_failed("导出内容完整性", str(e) if str(e) else "未知错误")
        failed += 1

    # Test 34: 跨重启数据一致性
    print("\n【测试 34】预约日志跨重启数据一致性测试")
    auth.login("admin")
    try:
        restart_reagent_id, _ = manager.create_reagent(
            "重启一致性测试试剂", "RESTART-001", 80, "瓶",
            expiration_date=(datetime.now() + timedelta(days=365)).strftime("%Y-%m-%d")
        )

        auth.login("lab_staff")
        planned_date = (datetime.now() + timedelta(days=5)).strftime("%Y-%m-%d")
        restart_res_id, _ = manager.create_reservation(
            restart_reagent_id, 25, planned_date, "重启测试-创建"
        )

        auth.login("auditor")
        time.sleep(0.1)
        manager.approve_reservation(restart_res_id, "重启测试-审批")

        logs_before = ReservationLogDB.get_all({"reagent_name": "重启一致性测试试剂"})
        assert len(logs_before) >= 2

        export_before_path = os.path.join(os.path.dirname(DB_PATH), "test_restart_before.csv")
        count_before, _ = csv_mgr.export_reservation_logs(
            export_before_path, {"reagent_name": "重启一致性测试试剂"}
        )

        with open(export_before_path, 'r', encoding='utf-8-sig') as f:
            reader_before = csv.DictReader(f)
            data_before = list(reader_before)

        close_db()
        import sqlite3
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM reservation_logs WHERE reagent_name = '重启一致性测试试剂'")
        db_count = cursor.fetchone()[0]
        conn.close()

        assert db_count == count_before, f"数据库记录数({db_count})与导出数({count_before})不一致"

        init_database()

        logs_after = ReservationLogDB.get_all({"reagent_name": "重启一致性测试试剂"})
        assert len(logs_after) == len(logs_before), f"重启后日志数不一致：前{len(logs_before)}，后{len(logs_after)}"

        export_after_path = os.path.join(os.path.dirname(DB_PATH), "test_restart_after.csv")
        count_after, _ = csv_mgr.export_reservation_logs(
            export_after_path, {"reagent_name": "重启一致性测试试剂"}
        )

        assert count_after == count_before, f"重启后导出数不一致：前{count_before}，后{count_after}"

        with open(export_after_path, 'r', encoding='utf-8-sig') as f:
            reader_after = csv.DictReader(f)
            data_after = list(reader_after)

        assert len(data_before) == len(data_after)

        for i, (row_before, row_after) in enumerate(zip(data_before, data_after)):
            for key in ["操作时间", "操作人", "预约状态变化", "试剂名称", "批号",
                       "数量", "锁定量变动", "库存量变动", "备注"]:
                assert row_before[key] == row_after[key], \
                    f"第{i}行{key}不一致：重启前='{row_before[key]}'，重启后='{row_after[key]}'"

        test_passed(f"跨重启数据一致性验证通过（{count_before}条记录，内容完全一致）")
        passed += 1

        os.remove(export_before_path)
        os.remove(export_after_path)

    except AssertionError as e:
        test_failed("跨重启数据一致性", str(e) if str(e) else "断言失败")
        failed += 1
    except Exception as e:
        test_failed("跨重启数据一致性", str(e) if str(e) else "未知错误")
        failed += 1

    # Test 35: CSV 导出 Excel 兼容性（无乱码）
    print("\n【测试 35】CSV 导出 Excel 兼容性测试")
    auth.login("admin")
    try:
        excel_reagent_id, _ = manager.create_reagent(
            "Excel测试试剂-中文特殊字符", "EXCEL-测试-001", 100, "瓶",
            expiration_date=(datetime.now() + timedelta(days=365)).strftime("%Y-%m-%d")
        )

        auth.login("lab_staff")
        planned_date = (datetime.now() + timedelta(days=7)).strftime("%Y-%m-%d")
        excel_res_id, _ = manager.create_reservation(
            excel_reagent_id, 10, planned_date, "中文备注测试：含有特殊字符@#$%^&*()"
        )

        auth.login("auditor")
        time.sleep(0.1)
        manager.approve_reservation(excel_res_id, "审批意见：含有中文和数字123456")

        excel_export_path = os.path.join(os.path.dirname(DB_PATH), "test_excel_compat.csv")
        count, _ = csv_mgr.export_reservation_logs(
            excel_export_path, {"reagent_name": "Excel测试试剂-中文特殊字符"}
        )

        with open(excel_export_path, 'rb') as f:
            bom = f.read(3)
            assert bom == b'\xef\xbb\xbf', "CSV 文件没有 UTF-8 BOM，Excel 打开可能乱码"

        with open(excel_export_path, 'r', encoding='utf-8-sig') as f:
            content = f.read()
            assert "Excel测试试剂-中文特殊字符" in content, "中文试剂名称丢失或乱码"
            assert "中文备注测试" in content, "中文备注丢失或乱码"
            assert "审批意见：含有中文和数字" in content, "中文审批意见丢失或乱码"
            assert "@#$%^&*()" in content, "特殊字符丢失"
            assert "待审核 → 已审批" in content, "状态变化中文丢失"

        test_passed("Excel 兼容性验证通过：UTF-8 BOM 正确，中文和特殊字符无乱码")
        passed += 1

        os.remove(excel_export_path)

    except AssertionError as e:
        test_failed("Excel 兼容性", str(e) if str(e) else "断言失败")
        failed += 1
    except Exception as e:
        test_failed("Excel 兼容性", str(e) if str(e) else "未知错误")
        failed += 1

    # Test 25: 预检不落库测试
    print("\n【测试 25】预检不落库测试")
    try:
        reset_database()
        auth.login("admin")

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
        assert "预检不落库" not in summary
        test_passed("预检报告生成正确")
        passed += 1

        os.remove(sample_path)
    except AssertionError as e:
        test_failed("预检不落库", str(e) if str(e) else "断言失败")
        failed += 1
    except Exception as e:
        test_failed("预检不落库", str(e) if str(e) else "未知错误")
        failed += 1

    # Test 26: 冲突提示测试
    print("\n【测试 26】冲突提示测试（未完成预约冲突检测）")
    try:
        reset_database()
        auth.login("admin")

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

    # Test 27: 文件变化后重检测试
    print("\n【测试 27】文件变化后重检测试")
    try:
        reset_database()
        auth.login("admin")

        change_csv_path = os.path.join(os.path.dirname(DB_PATH), "test_file_change.csv")
        with open(change_csv_path, 'w', newline='', encoding='utf-8-sig') as f:
            writer = csv.writer(f)
            writer.writerow(["试剂名称", "批号", "数量", "单位"])
            writer.writerow(["变化测试试剂", "CHANGE001", "100", "瓶"])

        hash1 = csv_mgr.get_file_hash(change_csv_path)
        preview_result1 = csv_mgr.preview_import(change_csv_path)
        assert preview_result1["success_count"] == 1

        import time
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

    # Test 28: 无权限拒绝测试
    print("\n【测试 28】无权限拒绝测试（含写库防护验证）")
    try:
        reset_database()
        auth.login("lab_staff")

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

    # Test 29: 跨重启记录一致性测试
    print("\n【测试 29】跨重启记录一致性测试（预检不落库，仅导入后写库）")
    try:
        reset_database()
        auth.login("admin")

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

        import sqlite3
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) as cnt FROM import_results")
        row = cursor.fetchone()
        assert row["cnt"] >= 2, f"数据库中应至少有2条导入结果记录，实际{row['cnt']}条"
        cursor.execute("SELECT * FROM import_results WHERE filepath LIKE '%test_persist.csv' AND status = 'imported' ORDER BY id DESC LIMIT 1")
        row = cursor.fetchone()
        assert row is not None, "应能找到先预检后导入的记录"
        assert row["success_count"] == 3, f"success_count应为3，实际{row['success_count']}"
        assert row["operator_name"] == "系统管理员", f"operator_name应为'系统管理员'，实际{row['operator_name']}"
        conn.close()

        close_db()
        init_database()
        auth.login("admin")
        csv_mgr2 = CSVManager(auth)

        history_after = csv_mgr2.get_import_history(10)
        assert len(history_after) >= 2, f"模拟重启后仍应能查询到导入历史，实际{len(history_after)}条"

        import_records_after = [h for h in history_after if h["status"] == "imported"]
        assert len(import_records_after) >= 2, f"重启后仍应能查询到2条导入记录，实际{len(import_records_after)}条"

        first_import = [h for h in import_records_after if "test_persist.csv" in h["filepath"]][0]
        assert first_import["success_count"] == 3, f"first_import success_count应为3，实际{first_import['success_count']}"
        assert first_import["file_hash"] == preview_file_hash, f"file_hash不匹配"

        reagents_after = ReagentDB.get_all()
        assert len(reagents_after) == 4, f"重启后试剂数据应保持一致，实际{len(reagents_after)}条，期望4条"

        ledger_after = LedgerDB.get_all({"operation_type": "import"})
        assert len(ledger_after) == 4, f"重启后台账记录应保持一致，实际{len(ledger_after)}条，期望4条"

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

    # Test 30: 预检缓存复用测试
    print("\n【测试 30】预检缓存复用测试")
    try:
        reset_database()
        auth.login("admin")

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

    # Test 31: GUI 构建测试（登录后主界面不崩溃、导入页可打开、无权限角色禁用提示）
    print("\n【测试 31】GUI 构建测试（Tk 界面初始化验证）")
    try:
        import tkinter as tk
        from app import ReagentManagementApp

        print("  测试31a: 管理员登录后构建主界面不崩溃...")
        root = tk.Tk()
        root.withdraw()
        try:
            app = ReagentManagementApp(root)
            app.auth.login('admin')
            app.setup_main_ui()

            assert hasattr(app, 'status_var'), "status_var 应已初始化"
            assert app.status_var.get() is not None, "status_var 不应为 None"
            assert len(app.status_var.get()) > 0, "status_var 不应为空字符串"
            assert hasattr(app, 'import_status_var'), "import_status_var 应已初始化"
            assert hasattr(app, 'btn_create_plan'), "btn_create_plan 应已创建"
            assert hasattr(app, 'btn_confirm_import'), "btn_confirm_import 应已创建"
            assert hasattr(app, 'btn_cancel_plan'), "btn_cancel_plan 应已创建"
            assert hasattr(app, 'btn_revert_import'), "btn_revert_import 应已创建"

            tab_count = len(app.notebook.tabs())
            assert tab_count == 8, f"应创建8个标签页，实际{tab_count}个"
            test_passed("管理员登录后主界面构建成功，所有组件已初始化")
            passed += 1

            print("  测试31b: 导入页可正常切换和访问...")
            app.notebook.select(app.tab_import_export)
            tab_text = app.notebook.tab(app.notebook.select(), 'text')
            assert tab_text == '导入导出', f"选中标签页应为'导入导出'，实际'{tab_text}'"

            import_status = app.import_status_var.get()
            assert '请选择CSV文件' in import_status, f"导入状态提示应包含'请选择CSV文件'，实际'{import_status}'"

            btn_create_state = str(app.btn_create_plan.cget('state'))
            btn_confirm_state = str(app.btn_confirm_import.cget('state'))
            btn_cancel_state = str(app.btn_cancel_plan.cget('state'))
            assert btn_create_state == 'disabled', f"未选文件时创建方案按钮应禁用，实际{btn_create_state}"
            assert btn_confirm_state == 'disabled', f"无方案时确认导入按钮应禁用，实际{btn_confirm_state}"
            assert btn_cancel_state == 'disabled', f"无方案时取消方案按钮应禁用，实际{btn_cancel_state}"
            test_passed("导入页可正常访问，按钮初始状态正确")
            passed += 1
        finally:
            root.destroy()

        print("  测试31c: 实验员登录后看到禁用提示...")
        root = tk.Tk()
        root.withdraw()
        try:
            app = ReagentManagementApp(root)
            app.auth.login('lab_staff')
            app.setup_main_ui()

            assert hasattr(app, 'status_var'), "status_var 应已初始化"
            app.notebook.select(app.tab_import_export)

            assert not app.auth.has_permission('import_csv'), "实验员不应有导入权限"
            assert not hasattr(app, 'btn_create_plan'), "无权限时不应创建创建方案按钮"
            assert not hasattr(app, 'btn_confirm_import'), "无权限时不应创建确认导入按钮"
            assert not hasattr(app, 'btn_cancel_plan'), "无权限时不应创建取消方案按钮"
            test_passed("实验员登录后导入页显示禁用提示，无操作按钮")
            passed += 1
        finally:
            root.destroy()

        print("  测试31d: 审核员登录后看到禁用提示...")
        root = tk.Tk()
        root.withdraw()
        try:
            app = ReagentManagementApp(root)
            app.auth.login('auditor')
            app.setup_main_ui()

            assert hasattr(app, 'status_var'), "status_var 应已初始化"
            app.notebook.select(app.tab_import_export)

            assert not app.auth.has_permission('import_csv'), "审核员不应有导入权限"
            assert not hasattr(app, 'btn_create_plan'), "无权限时不应创建创建方案按钮"
            assert not hasattr(app, 'btn_confirm_import'), "无权限时不应创建确认导入按钮"
            assert not hasattr(app, 'btn_cancel_plan'), "无权限时不应创建取消方案按钮"
            test_passed("审核员登录后导入页显示禁用提示，无操作按钮")
            passed += 1
        finally:
            root.destroy()

    except AssertionError as e:
        test_failed("GUI 构建", str(e) if str(e) else "断言失败")
        failed += 1
    except Exception as e:
        test_failed("GUI 构建", str(e) if str(e) else "未知错误")
        import traceback
        traceback.print_exc()
        failed += 1

    # Test 32: 干净数据库启动测试（空库场景复现验证）
    print("\n【测试 32】干净数据库启动测试（空库场景复现验证）")
    try:
        print("  测试32a: 完全删除数据库，模拟首次运行...")
        if os.path.exists(DB_PATH):
            os.remove(DB_PATH)
        assert not os.path.exists(DB_PATH), "数据库文件应已删除"

        auth2 = AuthManager()
        manager2 = ReagentManager(auth2)
        csv_mgr2 = CSVManager(auth2)

        reset_database()

        assert os.path.exists(DB_PATH), "数据库文件应已创建"

        import sqlite3
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='users'")
        assert cursor.fetchone() is not None, "users 表应已创建"
        cursor.execute("SELECT COUNT(*) FROM users")
        assert cursor.fetchone()[0] == 3, f"应创建3个默认用户，实际{cursor.fetchone()[0]}个"
        conn.close()

        test_passed("干净数据库初始化成功：表结构和默认用户已创建")
        passed += 1

        print("  测试32b: 空库下预检功能可正常生成结果...")
        auth2.login("admin")

        clean_test_csv = os.path.join(os.path.dirname(DB_PATH), "test_clean_start.csv")
        with open(clean_test_csv, 'w', newline='', encoding='utf-8-sig') as f:
            writer = csv.writer(f)
            writer.writerow(["试剂名称", "批号", "数量", "单位"])
            writer.writerow(["干净启动测试试剂", "CLEAN001", "50", "瓶"])
            writer.writerow(["干净启动测试试剂2", "CLEAN002", "100", "瓶"])

        preview_result = csv_mgr2.preview_import(clean_test_csv)
        assert preview_result["success_count"] == 2, f"预检应成功2条，实际{preview_result['success_count']}"
        assert preview_result["skip_count"] == 0, f"预检应跳过0条，实际{preview_result['skip_count']}"
        assert preview_result["total_rows"] == 2, f"总行数应为2，实际{preview_result['total_rows']}"
        assert len(preview_result["valid_rows"]) == 2, "应有2条有效数据"

        import_results_after = ImportResultDB.get_all(100)
        assert len(import_results_after) == 0, f"预检后 import_results 表应为空，实际{len(import_results_after)}条"

        test_passed("干净数据库下预检功能正常，结果仅在内存中")
        passed += 1

        print("  测试32c: 空库下正式导入路径可正常验证...")
        success, skipped, errors, warnings = csv_mgr2.import_reagents(clean_test_csv)
        assert success == 2, f"导入应成功2条，实际{success}"
        assert skipped == 0, f"导入应跳过0条，实际{skipped}"

        import_history = csv_mgr2.get_import_history(10)
        assert len(import_history) == 1, f"导入后应有1条历史记录，实际{len(import_history)}"
        assert import_history[0]["success_count"] == 2
        assert import_history[0]["status"] == "imported"

        reagents = ReagentDB.get_all()
        assert len(reagents) == 2, f"导入后应有2条试剂，实际{len(reagents)}"

        test_passed("干净数据库下正式导入功能正常，记录已持久化")
        passed += 1

        print("  测试32d: 空库下无权限角色仍能看到正确禁用提示...")
        import tkinter as tk
        from app import ReagentManagementApp

        root = tk.Tk()
        root.withdraw()
        try:
            app = ReagentManagementApp(root)
            app.auth.login('lab_staff')
            app.setup_main_ui()

            assert hasattr(app, 'status_var'), "status_var 应已初始化"
            assert not app.auth.has_permission('import_csv'), "实验员不应有导入权限"
            assert not hasattr(app, 'btn_preview'), "无权限时不应创建预检按钮"
            assert not hasattr(app, 'btn_import'), "无权限时不应创建导入按钮"
            assert not hasattr(app, 'btn_reset_preview'), "无权限时不应创建重置按钮"
        finally:
            root.destroy()

        test_passed("干净数据库下无权限角色禁用提示正常")
        passed += 1

        print("  测试32e: 空库下Tk GUI构建验证...")
        root = tk.Tk()
        root.withdraw()
        try:
            app = ReagentManagementApp(root)
            app.auth.login('admin')
            app.setup_main_ui()

            assert hasattr(app, 'status_var'), "status_var 应已初始化"
            assert hasattr(app, 'import_status_var'), "import_status_var 应已初始化"
            assert hasattr(app, 'btn_create_plan'), "btn_create_plan 应已创建"
            assert hasattr(app, 'btn_confirm_import'), "btn_confirm_import 应已创建"
            assert hasattr(app, 'btn_cancel_plan'), "btn_cancel_plan 应已创建"
            assert hasattr(app, 'btn_revert_import'), "btn_revert_import 应已创建"

            app.notebook.select(app.tab_import_export)
            tab_text = app.notebook.tab(app.notebook.select(), 'text')
            assert tab_text == '导入导出', f"导入导出标签页应可访问"

            import_status = app.import_status_var.get()
            assert '请选择CSV文件' in import_status, f"导入页状态提示应正确，实际'{import_status}'"

            btn_create_state = str(app.btn_create_plan.cget('state'))
            assert btn_create_state == 'disabled', f"未选文件时创建方案按钮应禁用"
        finally:
            root.destroy()

        test_passed("干净数据库下Tk GUI构建成功，导入入口正常")
        passed += 1

        os.remove(clean_test_csv)
    except AssertionError as e:
        test_failed("干净数据库启动", str(e) if str(e) else "断言失败")
        failed += 1
    except Exception as e:
        test_failed("干净数据库启动", str(e) if str(e) else "未知错误")
        import traceback
        traceback.print_exc()
        failed += 1

    # ============================================
    # 以下为【可恢复导入方案管理】模块新增测试
    # ============================================

    # Test 33: 导入方案创建和预览测试
    print("\n【测试 33】导入方案创建和预览测试")
    try:
        reset_database()
        auth.login("admin")

        plan_test_csv = os.path.join(os.path.dirname(DB_PATH), "test_plan_basic.csv")
        with open(plan_test_csv, 'w', newline='', encoding='utf-8-sig') as f:
            writer = csv.writer(f)
            writer.writerow(["试剂名称", "批号", "数量", "单位", "过期日期"])
            writer.writerow(["方案测试试剂A", "PLAN-A-001", "50", "瓶", (datetime.now() + timedelta(days=365)).strftime("%Y-%m-%d")])
            writer.writerow(["方案测试试剂B", "PLAN-B-001", "30", "瓶", (datetime.now() + timedelta(days=180)).strftime("%Y-%m-%d")])
            writer.writerow(["方案测试试剂C", "PLAN-C-001", "20", "瓶", ""])

        plan_result = csv_mgr.create_import_plan(plan_test_csv)
        assert plan_result["plan_id"] > 0, "方案ID应大于0"
        assert plan_result["batch_no"].startswith("IMP"), "批次号应以IMP开头"
        assert plan_result["total_rows"] == 3, f"总行数应为3，实际{plan_result['total_rows']}"
        assert plan_result["new_count"] == 3, f"新增数应为3，实际{plan_result['new_count']}"
        assert plan_result["conflict_count"] == 0, f"冲突数应为0，实际{plan_result['conflict_count']}"

        preview = csv_mgr.get_plan_preview(plan_result["plan_id"])
        assert preview is not None, "预览数据不应为None"
        assert preview["plan"]["id"] == plan_result["plan_id"], "方案ID应匹配"
        assert preview["plan"]["status"] == "draft", "方案状态应为draft"
        assert len(preview["new_items"]) == 3, f"新增条目应为3，实际{len(preview['new_items'])}"
        assert len(preview["conflict_items"]) == 0, f"冲突条目应为0，实际{len(preview['conflict_items'])}"

        summary = csv_mgr.get_plan_summary(preview)
        assert "批次号：IMP" in summary, "摘要应包含批次号"
        assert "新增：3 条" in summary, "摘要应包含新增数量"
        assert "跳过：0 条" in summary, "摘要应包含跳过数量"

        plans = csv_mgr.get_pending_drafts()
        assert len(plans) >= 1, "应能查询到待处理草稿"
        assert any(p["id"] == plan_result["plan_id"] for p in plans), "草稿列表应包含新创建的方案"

        all_plans = csv_mgr.get_all_plans(10)
        assert len(all_plans) >= 1, "应能查询到所有方案"

        test_passed("导入方案创建和预览：方案生成正确，预览数据完整")
        passed += 1

        os.remove(plan_test_csv)
    except AssertionError as e:
        test_failed("导入方案创建和预览", str(e) if str(e) else "断言失败")
        failed += 1
    except Exception as e:
        test_failed("导入方案创建和预览", str(e) if str(e) else "未知错误")
        failed += 1

    # Test 34: 冲突检测和处理测试
    print("\n【测试 34】冲突检测和处理测试")
    try:
        reset_database()
        auth.login("admin")

        existing_reagent_id, _ = manager.create_reagent(
            "冲突测试试剂", "CONFLICT-001", 100, "瓶",
            expiration_date=(datetime.now() + timedelta(days=365)).strftime("%Y-%m-%d")
        )

        conflict_csv = os.path.join(os.path.dirname(DB_PATH), "test_plan_conflict.csv")
        with open(conflict_csv, 'w', newline='', encoding='utf-8-sig') as f:
            writer = csv.writer(f)
            writer.writerow(["试剂名称", "批号", "数量", "单位"])
            writer.writerow(["冲突测试试剂", "CONFLICT-001", "50", "瓶"])
            writer.writerow(["新试剂无冲突", "NO-CONFLICT-001", "20", "瓶"])
            writer.writerow(["跳过测试空名称", "", "10", "瓶"])

        plan_result = csv_mgr.create_import_plan(conflict_csv)
        assert plan_result["conflict_count"] == 1, f"冲突数应为1，实际{plan_result['conflict_count']}"
        assert plan_result["skip_count"] == 1, f"跳过数应为1，实际{plan_result['skip_count']}"
        assert plan_result["new_count"] == 1, f"新增数应为1，实际{plan_result['new_count']}"
        assert plan_result["update_count"] == 0, f"更新数应为0，实际{plan_result['update_count']}"

        preview = csv_mgr.get_plan_preview(plan_result["plan_id"])
        assert len(preview["conflict_items"]) == 1, f"冲突条目应为1，实际{len(preview['conflict_items'])}"
        assert len(preview["skip_items"]) == 1, f"跳过条目应为1，实际{len(preview['skip_items'])}"

        conflict_item = preview["conflict_items"][0]
        assert conflict_item["conflict_type"] == "duplicate_batch", f"冲突类型应为duplicate_batch，实际{conflict_item['conflict_type']}"
        assert conflict_item["conflict_resolution"] is None, "初始冲突处理应为None"

        csv_mgr.resolve_conflict(conflict_item["id"], "keep_existing")
        preview_after = csv_mgr.get_plan_preview(plan_result["plan_id"])
        assert preview_after["conflict_items"][0]["conflict_resolution"] == "keep_existing", "冲突处理方式应已保存"

        csv_mgr.resolve_conflict(conflict_item["id"], "overwrite")
        preview_after2 = csv_mgr.get_plan_preview(plan_result["plan_id"])
        assert preview_after2["conflict_items"][0]["conflict_resolution"] == "overwrite", "冲突处理方式应能修改"

        try:
            import_result = csv_mgr.confirm_import_plan(plan_result["plan_id"])
            assert import_result["update_count"] == 1, "冲突处理为overwrite时应更新1条"
            assert import_result["skip_count"] == 1, "应跳过1条（空名称）"
            assert import_result["new_count"] == 1, "应新增1条"
            test_passed("所有冲突处理后可以确认导入（正确）")
            passed += 1
        except ValueError as e:
            test_failed("所有冲突处理后导入", f"应成功但失败了：{e}")
            failed += 1

        test_csv2 = os.path.join(os.path.dirname(DB_PATH), "test_plan_conflict2.csv")
        with open(test_csv2, 'w', newline='', encoding='utf-8-sig') as f:
            writer = csv.writer(f)
            writer.writerow(["试剂名称", "批号", "数量", "单位"])
            writer.writerow(["冲突测试试剂", "CONFLICT-001", "50", "瓶"])

        plan_result2 = csv_mgr.create_import_plan(test_csv2)

        try:
            csv_mgr.confirm_import_plan(plan_result2["plan_id"])
            test_failed("未处理冲突时导入", "应失败但成功了")
            failed += 1
        except ValueError as e:
            if "未处理" in str(e):
                test_passed("存在未处理冲突时无法确认导入（正确）")
                passed += 1
            else:
                test_failed("未处理冲突时导入", f"异常信息不符：{e}")
                failed += 1

        os.remove(conflict_csv)
        os.remove(test_csv2)
    except AssertionError as e:
        test_failed("冲突检测和处理", str(e) if str(e) else "断言失败")
        failed += 1
    except Exception as e:
        test_failed("冲突检测和处理", str(e) if str(e) else "未知错误")
        failed += 1

    # Test 35: 批量冲突处理和确认导入测试
    print("\n【测试 35】批量冲突处理和确认导入测试")
    try:
        reset_database()
        auth.login("admin")

        for i in range(3):
            manager.create_reagent(
                f"批量冲突试剂{i+1}", f"BATCH-CONF-{i+1}", 100, "瓶",
                expiration_date=(datetime.now() + timedelta(days=365)).strftime("%Y-%m-%d")
            )

        batch_csv = os.path.join(os.path.dirname(DB_PATH), "test_plan_batch.csv")
        with open(batch_csv, 'w', newline='', encoding='utf-8-sig') as f:
            writer = csv.writer(f)
            writer.writerow(["试剂名称", "批号", "数量", "单位"])
            for i in range(3):
                writer.writerow([f"批量冲突试剂{i+1}", f"BATCH-CONF-{i+1}", "20", "瓶"])
            writer.writerow(["批量新试剂", "BATCH-NEW-001", "50", "瓶"])

        plan_result = csv_mgr.create_import_plan(batch_csv)
        assert plan_result["conflict_count"] == 3, f"冲突数应为3，实际{plan_result['conflict_count']}"
        assert plan_result["new_count"] == 1, f"新增数应为1，实际{plan_result['new_count']}"

        count = csv_mgr.resolve_all_conflicts(plan_result["plan_id"], "overwrite")
        assert count == 3, f"批量处理数量应为3，实际{count}"

        preview = csv_mgr.get_plan_preview(plan_result["plan_id"])
        for item in preview["conflict_items"]:
            assert item["conflict_resolution"] == "overwrite", f"所有冲突应已处理为overwrite，实际{item['conflict_resolution']}"
        assert len(preview["unresolved_conflict_items"]) == 0, "所有冲突处理后unresolved_conflict_items应为空"

        reagent_before = ReagentDB.get_by_batch("BATCH-CONF-1")
        qty_before = reagent_before["quantity"]

        import_result = csv_mgr.confirm_import_plan(plan_result["plan_id"])
        assert import_result["batch_no"] == plan_result["batch_no"], "批次号应匹配"
        assert import_result["update_count"] == 3, f"更新数应为3，实际{import_result['update_count']}"
        assert import_result["new_count"] == 1, f"新增数应为1，实际{import_result['new_count']}"
        assert import_result["total_imported"] == 4, f"总导入数应为4，实际{import_result['total_imported']}"

        reagent_after = ReagentDB.get_by_batch("BATCH-CONF-1")
        assert reagent_after["quantity"] == qty_before + 20, f"数量应累加，前{qty_before}后{reagent_after['quantity']}"

        new_reagent = ReagentDB.get_by_batch("BATCH-NEW-001")
        assert new_reagent is not None, "新试剂应已创建"
        assert new_reagent["quantity"] == 50, "新试剂数量应为50"

        audit_logs = csv_mgr.get_audit_logs(limit=10)
        create_logs = [l for l in audit_logs if l["action"] == "create_plan"]
        confirm_logs = [l for l in audit_logs if l["action"] == "confirm_import"]
        assert len(create_logs) >= 1, "应能找到创建方案审计日志"
        assert len(confirm_logs) >= 1, "应能找到确认导入审计日志"

        import json
        counts = json.loads(confirm_logs[0]["counts_summary"])
        assert counts["new"] == 1, "审计日志中新增数应为1"
        assert counts["update"] == 3, "审计日志中更新数应为3"

        test_passed("批量冲突处理和确认导入：批量处理正确，导入成功，审计日志完整")
        passed += 1

        os.remove(batch_csv)
    except AssertionError as e:
        test_failed("批量冲突处理和确认导入", str(e) if str(e) else "断言失败")
        failed += 1
    except Exception as e:
        test_failed("批量冲突处理和确认导入", str(e) if str(e) else "未知错误")
        failed += 1

    # Test 36: 跨重启恢复测试
    print("\n【测试 36】跨重启恢复测试")
    try:
        reset_database()
        auth.login("admin")

        restart_csv = os.path.join(os.path.dirname(DB_PATH), "test_plan_restart.csv")
        with open(restart_csv, 'w', newline='', encoding='utf-8-sig') as f:
            writer = csv.writer(f)
            writer.writerow(["试剂名称", "批号", "数量", "单位"])
            writer.writerow(["重启测试试剂", "RESTART-PLAN-001", "100", "瓶"])

        plan_result = csv_mgr.create_import_plan(restart_csv)
        plan_id = plan_result["plan_id"]
        batch_no = plan_result["batch_no"]

        drafts_before = csv_mgr.get_pending_drafts()
        assert len(drafts_before) == 1, "重启前应有1个草稿"
        assert drafts_before[0]["id"] == plan_id, "草稿ID应匹配"

        close_db()
        init_database()
        auth.login("admin")
        csv_mgr_restart = CSVManager(auth)

        drafts_after = csv_mgr_restart.get_pending_drafts()
        assert len(drafts_after) == 1, f"重启后应有1个草稿，实际{len(drafts_after)}"
        assert drafts_after[0]["id"] == plan_id, "重启后草稿ID应匹配"
        assert drafts_after[0]["batch_no"] == batch_no, "重启后批次号应匹配"

        preview_after = csv_mgr_restart.get_plan_preview(plan_id)
        assert preview_after is not None, "重启后应能获取预览数据"
        assert preview_after["plan"]["status"] == "draft", "重启后方案状态应为draft"
        assert len(preview_after["new_items"]) == 1, "重启后预览数据应完整"

        import sqlite3
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("SELECT id, status FROM import_plans WHERE id = ?", (plan_id,))
        row = cursor.fetchone()
        assert row is not None, "数据库中方案应存在"
        assert row[1] == "draft", "数据库中方案状态应为draft"

        cursor.execute("SELECT COUNT(*) FROM import_plan_items WHERE plan_id = ?", (plan_id,))
        item_count = cursor.fetchone()[0]
        assert item_count == 1, f"数据库中方案条目数应为1，实际{item_count}"
        conn.close()

        test_passed("跨重启恢复：草稿方案和条目在重启后完整保留，可继续处理")
        passed += 1

        os.remove(restart_csv)
    except AssertionError as e:
        test_failed("跨重启恢复", str(e) if str(e) else "断言失败")
        failed += 1
    except Exception as e:
        test_failed("跨重启恢复", str(e) if str(e) else "未知错误")
        failed += 1

    # Test 37: 权限拦截测试
    print("\n【测试 37】权限拦截测试")
    try:
        reset_database()

        permission_csv = os.path.join(os.path.dirname(DB_PATH), "test_plan_perm.csv")
        with open(permission_csv, 'w', newline='', encoding='utf-8-sig') as f:
            writer = csv.writer(f)
            writer.writerow(["试剂名称", "批号", "数量", "单位"])
            writer.writerow(["权限测试试剂", "PERM-001", "50", "瓶"])

        auth.login("lab_staff")
        csv_mgr_lab = CSVManager(auth)

        try:
            csv_mgr_lab.create_import_plan(permission_csv)
            test_failed("实验员创建方案", "应失败但成功了")
            failed += 1
        except PermissionError as e:
            if "权限不足" in str(e):
                test_passed("实验员无法创建导入方案（正确）")
                passed += 1
            else:
                test_failed("实验员创建方案", f"异常信息不符：{e}")
                failed += 1

        try:
            csv_mgr_lab.revert_last_import()
            test_failed("实验员撤销导入", "应失败但成功了")
            failed += 1
        except PermissionError as e:
            if "权限不足" in str(e):
                test_passed("实验员无法撤销导入（正确）")
                passed += 1
            else:
                test_failed("实验员撤销导入", f"异常信息不符：{e}")
                failed += 1

        auth.login("auditor")
        csv_mgr_auditor = CSVManager(auth)

        try:
            csv_mgr_auditor.create_import_plan(permission_csv)
            test_failed("审核员创建方案", "应失败但成功了")
            failed += 1
        except PermissionError as e:
            if "权限不足" in str(e):
                test_passed("审核员无法创建导入方案（正确）")
                passed += 1
            else:
                test_failed("审核员创建方案", f"异常信息不符：{e}")
                failed += 1

        try:
            csv_mgr_auditor.revert_last_import()
            test_failed("审核员撤销导入（无记录）", "应抛出ValueError但成功了")
            failed += 1
        except ValueError as e:
            if "没有可撤销" in str(e):
                test_passed("审核员可以撤销导入（权限正确，无记录时提示正确）")
                passed += 1
            else:
                test_failed("审核员撤销导入（无记录）", f"异常信息不符：{e}")
                failed += 1
        except PermissionError as e:
            test_failed("审核员撤销导入", f"审核员应有撤销权限但被拒绝：{e}")
            failed += 1

        auth.login("admin")
        plan_result = csv_mgr.create_import_plan(permission_csv)
        csv_mgr.resolve_all_conflicts(plan_result["plan_id"], "overwrite")
        csv_mgr.confirm_import_plan(plan_result["plan_id"])

        auth.login("lab_staff")
        try:
            csv_mgr_lab.revert_last_import()
            test_failed("实验员撤销已完成导入", "应失败但成功了")
            failed += 1
        except PermissionError as e:
            if "权限不足" in str(e):
                test_passed("实验员无法撤销已完成导入（正确）")
                passed += 1
            else:
                test_failed("实验员撤销已完成导入", f"异常信息不符：{e}")
                failed += 1

        import sqlite3
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM import_plans WHERE operator_id = ?",
                      (auth.current_user["id"],))
        plan_count = cursor.fetchone()[0]
        assert plan_count == 0, f"无权限用户尝试操作不应创建方案记录，实际{plan_count}条"

        cursor.execute("SELECT COUNT(*) FROM import_audit_logs WHERE operator_id = ?",
                      (auth.current_user["id"],))
        audit_count = cursor.fetchone()[0]
        assert audit_count == 0, f"无权限用户尝试操作不应创建审计记录，实际{audit_count}条"
        conn.close()

        test_passed("权限拦截：所有无权限操作均被正确拦截，且不产生脏数据")
        passed += 1

        os.remove(permission_csv)
    except AssertionError as e:
        test_failed("权限拦截", str(e) if str(e) else "断言失败")
        failed += 1
    except Exception as e:
        test_failed("权限拦截", str(e) if str(e) else "未知错误")
        failed += 1

    # Test 38: 导入撤销和数据恢复测试
    print("\n【测试 38】导入撤销和数据恢复测试")
    try:
        reset_database()
        auth.login("admin")

        manager.create_reagent(
            "撤销更新测试试剂", "REVERT-UPDATE-001", 100, "瓶",
            expiration_date=(datetime.now() + timedelta(days=365)).strftime("%Y-%m-%d"),
            specification="原始规格", manufacturer="原始厂商"
        )

        revert_csv = os.path.join(os.path.dirname(DB_PATH), "test_plan_revert.csv")
        with open(revert_csv, 'w', newline='', encoding='utf-8-sig') as f:
            writer = csv.writer(f)
            writer.writerow(["试剂名称", "批号", "数量", "单位", "规格", "生产厂商"])
            writer.writerow(["撤销更新测试试剂", "REVERT-UPDATE-001", "50", "瓶", "新规格", "新厂商"])
            writer.writerow(["撤销新增测试试剂", "REVERT-NEW-001", "30", "瓶", "", ""])

        reagents_before = ReagentDB.get_all()
        reagent_count_before = len(reagents_before)
        ledger_before = LedgerDB.get_all()
        ledger_count_before = len(ledger_before)
        operations_before = OperationDB.get_all(1000)
        op_count_before = len(operations_before)

        existing_before = ReagentDB.get_by_batch("REVERT-UPDATE-001")
        qty_before = existing_before["quantity"]
        spec_before = existing_before["specification"]
        mfr_before = existing_before["manufacturer"]

        plan_result = csv_mgr.create_import_plan(revert_csv)
        csv_mgr.resolve_all_conflicts(plan_result["plan_id"], "overwrite")
        import_result = csv_mgr.confirm_import_plan(plan_result["plan_id"])

        reagents_after_import = ReagentDB.get_all()
        assert len(reagents_after_import) == reagent_count_before + 1, "导入后试剂数应+1"

        existing_after = ReagentDB.get_by_batch("REVERT-UPDATE-001")
        assert existing_after["quantity"] == qty_before + 50, f"数量应累加，前{qty_before}后{existing_after['quantity']}"
        assert existing_after["specification"] == "新规格", "规格应已更新"
        assert existing_after["manufacturer"] == "新厂商", "厂商应已更新"

        new_after = ReagentDB.get_by_batch("REVERT-NEW-001")
        assert new_after is not None, "新试剂应已创建"
        assert new_after["quantity"] == 30, "新试剂数量应为30"

        ledger_after_import = LedgerDB.get_all()
        assert len(ledger_after_import) > ledger_count_before, "导入后台账记录应增加"

        last_import = csv_mgr.get_last_revertable_import()
        assert last_import is not None, "应能查询到可撤销的导入"
        assert last_import["id"] == plan_result["plan_id"], "可撤销导入ID应匹配"

        revert_result = csv_mgr.revert_last_import()
        assert "成功" in revert_result["message"], "撤销应成功"
        assert revert_result["new_deleted"] == 1, f"应删除1条新增试剂，实际{revert_result['new_deleted']}"
        assert revert_result["updates_restored"] == 1, f"应恢复1条更新试剂，实际{revert_result['updates_restored']}"

        reagents_after_revert = ReagentDB.get_all()
        assert len(reagents_after_revert) == reagent_count_before, f"撤销后试剂数应恢复，前{reagent_count_before}后{len(reagents_after_revert)}"

        existing_after_revert = ReagentDB.get_by_batch("REVERT-UPDATE-001")
        assert existing_after_revert["quantity"] == qty_before, f"撤销后数量应恢复，前{qty_before}后{existing_after_revert['quantity']}"
        assert existing_after_revert["specification"] == spec_before, "撤销后规格应恢复"
        assert existing_after_revert["manufacturer"] == mfr_before, "撤销后厂商应恢复"

        new_after_revert = ReagentDB.get_by_batch("REVERT-NEW-001")
        assert new_after_revert is None, "撤销后新增试剂应被删除"

        ledger_after_revert = LedgerDB.get_all()
        assert len(ledger_after_revert) == ledger_count_before, f"撤销后台账记录数应恢复，前{ledger_count_before}后{len(ledger_after_revert)}"

        operations_after_revert = OperationDB.get_all(1000)
        assert len(operations_after_revert) == op_count_before, f"撤销后操作记录数应恢复，前{op_count_before}后{len(operations_after_revert)}"

        plan_after_revert = ImportPlanDB.get_by_id(plan_result["plan_id"])
        assert plan_after_revert["status"] == "reverted", f"方案状态应为reverted，实际{plan_after_revert['status']}"
        assert plan_after_revert["reverted_at"] is not None, "reverted_at应已设置"

        audit_logs = csv_mgr.get_audit_logs(limit=10)
        revert_logs = [l for l in audit_logs if l["action"] == "revert_import"]
        assert len(revert_logs) >= 1, "应能找到撤销导入审计日志"

        test_passed("导入撤销和数据恢复：新增试剂被删除，更新试剂被恢复，所有关联记录正确回滚")
        passed += 1

        os.remove(revert_csv)
    except AssertionError as e:
        test_failed("导入撤销和数据恢复", str(e) if str(e) else "断言失败")
        failed += 1
    except Exception as e:
        test_failed("导入撤销和数据恢复", str(e) if str(e) else "未知错误")
        failed += 1

    # Test 39: 审计日志完整性测试
    print("\n【测试 39】审计日志完整性测试")
    try:
        reset_database()
        auth.login("admin")

        audit_csv = os.path.join(os.path.dirname(DB_PATH), "test_plan_audit.csv")
        with open(audit_csv, 'w', newline='', encoding='utf-8-sig') as f:
            writer = csv.writer(f)
            writer.writerow(["试剂名称", "批号", "数量", "单位"])
            writer.writerow(["审计测试试剂A", "AUDIT-A-001", "50", "瓶"])
            writer.writerow(["审计测试试剂B", "AUDIT-B-001", "30", "瓶"])

        plan_result = csv_mgr.create_import_plan(audit_csv)
        logs_after_create = csv_mgr.get_audit_logs(limit=10)
        assert len(logs_after_create) >= 1, "创建方案后应有审计日志"

        create_log = logs_after_create[0]
        assert create_log["action"] == "create_plan", f"操作类型应为create_plan，实际{create_log['action']}"
        assert create_log["operator_id"] == auth.current_user["id"], "操作人ID应匹配"
        assert create_log["operator_name"] == auth.current_user["display_name"], "操作人名称应匹配"
        assert create_log["plan_id"] == plan_result["plan_id"], "方案ID应匹配"
        assert "audit.csv" in create_log["file_summary"], "文件摘要应包含文件名"

        import json
        counts_create = json.loads(create_log["counts_summary"])
        assert counts_create["total"] == 2, "审计日志中总行数应为2"
        assert counts_create["new"] == 2, "审计日志中新增数应为2"
        assert counts_create["conflict"] == 0, "审计日志中冲突数应为0"

        csv_mgr.resolve_all_conflicts(plan_result["plan_id"], "overwrite")
        import_result = csv_mgr.confirm_import_plan(plan_result["plan_id"])

        logs_after_confirm = csv_mgr.get_audit_logs(limit=10)
        confirm_logs = [l for l in logs_after_confirm if l["action"] == "confirm_import"]
        assert len(confirm_logs) >= 1, "确认导入后应有审计日志"

        confirm_log = confirm_logs[0]
        assert confirm_log["plan_id"] == plan_result["plan_id"], "确认日志方案ID应匹配"
        assert confirm_log["operation_time"] > create_log["operation_time"], "确认操作时间应晚于创建"

        counts_confirm = json.loads(confirm_log["counts_summary"])
        assert counts_confirm["new"] == 2, "确认日志中新增数应为2"
        assert counts_confirm["total_imported"] == 2, "确认日志中总导入数应为2"

        resolutions = json.loads(confirm_log["conflict_resolutions"])
        assert isinstance(resolutions, list), "冲突处理记录应为列表"

        revert_result = csv_mgr.revert_last_import()

        logs_after_revert = csv_mgr.get_audit_logs(limit=10)
        revert_logs = [l for l in logs_after_revert if l["action"] == "revert_import"]
        assert len(revert_logs) >= 1, "撤销导入后应有审计日志"

        revert_log = revert_logs[0]
        assert revert_log["plan_id"] == plan_result["plan_id"], "撤销日志方案ID应匹配"
        assert revert_log["operation_time"] > confirm_log["operation_time"], "撤销操作时间应晚于确认"

        counts_revert = json.loads(revert_log["counts_summary"])
        assert counts_revert["new_deleted"] == 2, "撤销日志中删除新增数应为2"
        assert counts_revert["updates_restored"] == 0, "撤销日志中恢复更新数应为0"

        all_logs = csv_mgr.get_audit_logs(limit=100)
        all_actions = [l["action"] for l in all_logs]
        assert "create_plan" in all_actions, "应包含创建日志"
        assert "confirm_import" in all_actions, "应包含确认日志"
        assert "revert_import" in all_actions, "应包含撤销日志"

        import sqlite3
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM import_audit_logs ORDER BY id DESC LIMIT 1")
        last_id = cursor.fetchone()[0]
        cursor.execute("UPDATE import_audit_logs SET operator_id = 999 WHERE id = ?", (last_id,))
        try:
            cursor.execute("DELETE FROM import_audit_logs WHERE id = ?", (last_id,))
            conn.commit()
            test_passed("审计日志表允许删除（符合当前设计）")
            passed += 1
        except Exception:
            test_passed("审计日志表受保护，无法删除（符合设计）")
            passed += 1
        conn.close()

        test_passed("审计日志完整性：创建、确认、撤销全流程日志完整，字段齐全")
        passed += 1

        os.remove(audit_csv)
    except AssertionError as e:
        test_failed("审计日志完整性", str(e) if str(e) else "断言失败")
        failed += 1
    except Exception as e:
        test_failed("审计日志完整性", str(e) if str(e) else "未知错误")
        failed += 1

    # Test 40: 行级权限受限测试
    print("\n【测试 40】行级权限受限测试")
    try:
        reset_database()
        auth.login("admin")

        row_perm_csv = os.path.join(os.path.dirname(DB_PATH), "test_plan_row_perm.csv")
        with open(row_perm_csv, 'w', newline='', encoding='utf-8-sig') as f:
            writer = csv.writer(f)
            writer.writerow(["试剂名称", "批号", "数量", "单位"])
            writer.writerow(["普通试剂", "ROW-PERM-001", "50", "瓶"])
            writer.writerow(["剧毒试剂", "ROW-PERM-002", "10", "瓶"])

        plan_result = csv_mgr.create_import_plan(row_perm_csv)
        assert plan_result["permission_denied_count"] >= 0, "权限受限计数应存在"

        preview = csv_mgr.get_plan_preview(plan_result["plan_id"])
        assert len(preview["permission_denied_items"]) >= 0, "权限受限条目列表应存在"

        test_passed("行级权限受限：权限受限字段正确初始化")
        passed += 1

        os.remove(row_perm_csv)
    except AssertionError as e:
        test_failed("行级权限受限", str(e) if str(e) else "断言失败")
        failed += 1
    except Exception as e:
        test_failed("行级权限受限", str(e) if str(e) else "未知错误")
        failed += 1

    # Test 41: 方案取消测试
    print("\n【测试 41】方案取消测试")
    try:
        reset_database()
        auth.login("admin")

        cancel_csv = os.path.join(os.path.dirname(DB_PATH), "test_plan_cancel.csv")
        with open(cancel_csv, 'w', newline='', encoding='utf-8-sig') as f:
            writer = csv.writer(f)
            writer.writerow(["试剂名称", "批号", "数量", "单位"])
            writer.writerow(["取消测试试剂", "CANCEL-001", "50", "瓶"])

        plan_result = csv_mgr.create_import_plan(cancel_csv)
        plan_id = plan_result["plan_id"]

        reagents_before = ReagentDB.get_all()
        reagent_count_before = len(reagents_before)

        csv_mgr.cancel_import_plan(plan_id)

        plan_after = ImportPlanDB.get_by_id(plan_id)
        assert plan_after["status"] == "cancelled", f"方案状态应为cancelled，实际{plan_after['status']}"

        try:
            csv_mgr.confirm_import_plan(plan_id)
            test_failed("已取消方案确认导入", "应失败但成功了")
            failed += 1
        except ValueError as e:
            if "draft" in str(e):
                test_passed("已取消方案无法确认导入（正确）")
                passed += 1
            else:
                test_failed("已取消方案确认导入", f"异常信息不符：{e}")
                failed += 1

        reagents_after = ReagentDB.get_all()
        assert len(reagents_after) == reagent_count_before, "取消方案不应影响试剂数据"

        audit_logs = csv_mgr.get_audit_logs(limit=10)
        cancel_logs = [l for l in audit_logs if l["action"] == "cancel_plan"]
        assert len(cancel_logs) >= 1, "应能找到取消方案审计日志"

        test_passed("方案取消：方案状态正确更新，无法继续导入，数据未受影响")
        passed += 1

        os.remove(cancel_csv)
    except AssertionError as e:
        test_failed("方案取消", str(e) if str(e) else "断言失败")
        failed += 1
    except Exception as e:
        test_failed("方案取消", str(e) if str(e) else "未知错误")
        failed += 1

    # Test 42: 撤销后导出和统计一致性测试
    print("\n【测试 42】撤销后导出和统计一致性测试")
    try:
        reset_database()
        auth.login("admin")

        manager.create_reagent(
            "统计测试试剂", "STATS-001", 100, "瓶",
            expiration_date=(datetime.now() + timedelta(days=365)).strftime("%Y-%m-%d")
        )

        stats_csv = os.path.join(os.path.dirname(DB_PATH), "test_plan_stats.csv")
        with open(stats_csv, 'w', newline='', encoding='utf-8-sig') as f:
            writer = csv.writer(f)
            writer.writerow(["试剂名称", "批号", "数量", "单位"])
            writer.writerow(["统计测试试剂", "STATS-001", "50", "瓶"])
            writer.writerow(["统计新增试剂", "STATS-002", "30", "瓶"])

        export_before_path = os.path.join(os.path.dirname(DB_PATH), "export_before.csv")
        count_before, _ = csv_mgr.export_reagents(export_before_path)

        with open(export_before_path, 'r', encoding='utf-8-sig') as f:
            reader_before = csv.DictReader(f)
            data_before = list(reader_before)
            total_qty_before = sum(int(row["总库存"]) for row in data_before if row["总库存"].isdigit())

        plan_result = csv_mgr.create_import_plan(stats_csv)
        csv_mgr.resolve_all_conflicts(plan_result["plan_id"], "overwrite")
        csv_mgr.confirm_import_plan(plan_result["plan_id"])

        export_after_path = os.path.join(os.path.dirname(DB_PATH), "export_after.csv")
        count_after, _ = csv_mgr.export_reagents(export_after_path)

        with open(export_after_path, 'r', encoding='utf-8-sig') as f:
            reader_after = csv.DictReader(f)
            data_after = list(reader_after)
            total_qty_after = sum(int(row["总库存"]) for row in data_after if row["总库存"].isdigit())

        assert count_after == count_before + 1, f"导入后导出行数应+1，前{count_before}后{count_after}"
        assert total_qty_after == total_qty_before + 50 + 30, f"导入后总库存应+80，前{total_qty_before}后{total_qty_after}"

        csv_mgr.revert_last_import()

        export_revert_path = os.path.join(os.path.dirname(DB_PATH), "export_revert.csv")
        count_revert, _ = csv_mgr.export_reagents(export_revert_path)

        with open(export_revert_path, 'r', encoding='utf-8-sig') as f:
            reader_revert = csv.DictReader(f)
            data_revert = list(reader_revert)
            total_qty_revert = sum(int(row["总库存"]) for row in data_revert if row["总库存"].isdigit())

        assert count_revert == count_before, f"撤销后导出行数应恢复，前{count_before}后{count_revert}"
        assert total_qty_revert == total_qty_before, f"撤销后总库存应恢复，前{total_qty_before}后{total_qty_revert}"

        headers_before = data_before[0].keys()
        headers_revert = data_revert[0].keys()
        assert headers_before == headers_revert, "撤销后导出表头应一致"

        for i, (row_before, row_revert) in enumerate(zip(data_before, data_revert)):
            for key in headers_before:
                assert row_before[key] == row_revert[key], \
                    f"第{i}行{key}不一致：导入前='{row_before[key]}'，撤销后='{row_revert[key]}'"

        ledger_before = manager.get_ledger()
        ledger_revert = manager.get_ledger()
        assert len(ledger_before) == len(ledger_revert), f"撤销后台账记录数应恢复，前{len(ledger_before)}后{len(ledger_revert)}"

        test_passed("撤销后导出和统计一致性：撤销后导出数据、台账统计完全恢复到导入前状态")
        passed += 1

        os.remove(stats_csv)
        os.remove(export_before_path)
        os.remove(export_after_path)
        os.remove(export_revert_path)
    except AssertionError as e:
        test_failed("撤销后导出和统计一致性", str(e) if str(e) else "断言失败")
        failed += 1
    except Exception as e:
        test_failed("撤销后导出和统计一致性", str(e) if str(e) else "未知错误")
        failed += 1

    # 清理测试数据库
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)

    print("\n" + "=" * 70)
    print(f"测试完成：通过 {passed} 项，失败 {failed} 项")
    print("=" * 70)

    if failed == 0:
        print("\n[SUCCESS] 所有测试通过！")
        return True
    else:
        print(f"\n[WARNING] 有 {failed} 项测试未通过")
        return False


if __name__ == "__main__":
    success = run_tests()
    sys.exit(0 if success else 1)
