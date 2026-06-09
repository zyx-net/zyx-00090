import os
import sys
import sqlite3
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from database import (init_database, DB_PATH, ReagentDB, OperationDB, LedgerDB,
                       ReservationDB, ReservationLogDB, ReagentLockDB, close_db)
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
