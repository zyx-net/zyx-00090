import os
import sys
import sqlite3
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from database import init_database, DB_PATH, ReagentDB, OperationDB, LedgerDB
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
        success, skipped, errors = csv_mgr.import_reagents(sample_path)
        assert success == 3
        assert skipped == 0
        test_passed(f"CSV导入成功（{success}条）")
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

        conn.close()

        assert reagent_count == 7
        assert user_count == 3
        assert op_count > 0
        assert ledger_count > 0

        test_passed(f"数据持久化验证成功：试剂{reagent_count}条，操作{op_count}条，台账{ledger_count}条，用户{user_count}条")
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
