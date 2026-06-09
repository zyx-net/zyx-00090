"""
=================================================================
已审批预约改期 - 锁定量不翻倍修复验证脚本
=================================================================

此脚本演示了"已审批预约改期后库存锁定量重复累加"bug的修复效果。

复现场景：
  总库存 100
  → 创建预约 30，审批通过 → 锁定量 = 30，可用量 = 70  ✓
  → 对这条已审批预约改期
    [修复前] 锁定量变成 60（翻倍！），可用量变成 40  ✗ BUG！
    [修复后] 锁定量仍为 30，可用量仍为 70  ✓

"""
import os
import sys
from datetime import datetime, timedelta

from database import init_database, DB_PATH, ReagentDB, ReagentLockDB, close_db
from auth import AuthManager
from business import ReagentManager


def print_header(title):
    print("\n" + "=" * 70)
    print(f"  {title}")
    print("=" * 70)


def print_stock_status(reagent_id, step_desc):
    reagent = ReagentDB.get_by_id(reagent_id)
    total = reagent["quantity"]
    locked = reagent.get("locked_quantity", 0)
    available = ReagentLockDB.get_available_quantity(reagent_id)

    bar_total = "█" * min(total // 5, 20)
    bar_locked = "▓" * min(locked // 5, 20)
    bar_available = "░" * min(available // 5, 20)

    print(f"\n  {step_desc}")
    print(f"  {'─' * 50}")
    print(f"    总库存:  {total:3d}  {bar_total}")
    print(f"    已锁定:  {locked:3d}  {bar_locked}")
    print(f"    可用量:  {available:3d}  {bar_available}")
    print(f"    公式:    可用量 = 总库存 - 已锁定 = {total} - {locked} = {available}")

    if locked > total:
        print(f"    ⚠️  【BUG】锁定量({locked}) > 总库存({total})，数据不一致！")
    elif locked == 0 and total > 0:
        print(f"    ℹ️  无锁定，全部可用")
    else:
        print(f"    ✓  数据一致")

    return total, locked, available


def main():
    print_header("已审批预约改期 - 锁定量不翻倍修复验证")

    db_path = "demo_reschedule_fix.db"
    import database as db_module
    original_db_path = db_module.DB_PATH
    db_module.DB_PATH = db_path

    if os.path.exists(db_path):
        os.remove(db_path)

    init_database()

    auth = AuthManager()
    auth.login("admin")
    manager = ReagentManager(auth)

    try:
        print_header("第1步：创建测试试剂")
        reagent_id, _ = manager.create_reagent(
            "演示试剂-改期测试", "DEMO-RESCHEDULE-001", 100, "瓶",
            expiration_date=(datetime.now() + timedelta(days=365)).strftime("%Y-%m-%d")
        )
        total, locked, available = print_stock_status(reagent_id, "试剂初始化")
        assert total == 100
        assert locked == 0
        assert available == 100

        print_header("第2步：实验员创建预约（数量30）")
        auth.login("lab_staff")
        planned_date = (datetime.now() + timedelta(days=7)).strftime("%Y-%m-%d")
        res_id, _ = manager.create_reservation(
            reagent_id, 30, planned_date, "用户演示-创建预约"
        )
        total, locked, available = print_stock_status(reagent_id, "创建预约后（待审核）")
        assert total == 100
        assert locked == 0
        assert available == 100

        print_header("第3步：审核员审批通过")
        auth.login("auditor")
        manager.approve_reservation(res_id, "用户演示-审批通过")
        total, locked, available = print_stock_status(reagent_id, "审批通过后")
        assert total == 100
        assert locked == 30, f"审批后锁定量应为30，实际是{locked}"
        assert available == 70

        print("\n  ✅ 审批后状态正常：总库存=100，锁定=30，可用=70")

        print_header("第4步：对已审批预约进行改期（关键验证点）")
        new_date = (datetime.now() + timedelta(days=14)).strftime("%Y-%m-%d")
        log_id, msg = manager.reschedule_reservation(
            res_id, new_date, "用户演示-已审批改期"
        )
        print(f"\n  改期结果: {msg}")

        total, locked, available = print_stock_status(reagent_id, "改期后")

        print("\n" + "─" * 70)
        if locked == 60:
            print("  ❌ 【BUG 存在】改期后锁定量变成 60（翻倍了！）")
            print("     原因：改期时只给新预约增加锁定，没有释放原预约的锁定")
            print("     影响：可用量错误地变成 40，后续预约审批会错误地判断库存不足")
            return 1
        elif locked == 30:
            print("  ✅ 【BUG 已修复】改期后锁定量仍为 30（未翻倍！）")
            print("     原因：改期时先释放原预约锁定(-30)，再给新预约锁定(+30)，净变化为0")
            print("     影响：可用量保持 70，数据完全一致")
        else:
            print(f"  ❌ 锁定量异常：{locked}")
            return 1

        assert locked == 30, f"改期后锁定量应为30，实际是{locked}"
        assert available == 70, f"改期后可用量应为70，实际是{available}"

        print_header("第5步：验证改期后状态")
        from database import ReservationDB
        old_res = ReservationDB.get_by_id(res_id)
        all_res = ReservationDB.get_all()
        new_res = [r for r in all_res if r["remarks"] and f"由预约#{res_id}改期" in r["remarks"]][0]

        print(f"\n  原预约 #{res_id} 状态: {old_res['status']} (预期: rescheduled)")
        print(f"  新预约 #{new_res['id']} 状态: {new_res['status']} (预期: approved)")
        print(f"  新预约数量: {new_res['quantity']} (预期: 30)")
        print(f"  新预约日期: {new_res['planned_use_date']} (预期: {new_date})")

        assert old_res["status"] == "rescheduled"
        assert new_res["status"] == "approved"
        assert new_res["quantity"] == 30
        print("\n  ✅ 状态流转正确")

        print_header("第6步：验证改期后取消预约")
        manager.cancel_reservation(new_res["id"], "用户演示-取消改期后的预约")
        total, locked, available = print_stock_status(reagent_id, "取消预约后")
        assert total == 100
        assert locked == 0
        assert available == 100
        print("\n  ✅ 取消后锁定量正确释放为0")

        print_header("第7步：验证改期后实际领用")
        auth.login("lab_staff")
        planned_date2 = (datetime.now() + timedelta(days=7)).strftime("%Y-%m-%d")
        res2_id, _ = manager.create_reservation(
            reagent_id, 25, planned_date2, "用户演示-领用测试"
        )
        auth.login("auditor")
        manager.approve_reservation(res2_id, "审批通过")

        new_date2 = (datetime.now() + timedelta(days=21)).strftime("%Y-%m-%d")
        manager.reschedule_reservation(res2_id, new_date2, "改期后领用")

        all_res2 = ReservationDB.get_all()
        new_res2 = [r for r in all_res2 if r["remarks"] and f"由预约#{res2_id}改期" in r["remarks"]][0]

        total, locked, available = print_stock_status(reagent_id, "再次改期后")
        assert locked == 25, f"再次改期后锁定量应为25，实际是{locked}"
        print("\n  ✅ 再次改期后锁定量保持25（未翻倍）")

        manager.complete_reservation(new_res2["id"], "用户演示-实际领用")
        total, locked, available = print_stock_status(reagent_id, "实际领用后")
        assert total == 75
        assert locked == 0
        assert available == 75
        print("\n  ✅ 实际领用后：库存=75，锁定=0，可用=75")

        print_header("第8步：验证重启后数据一致性")
        import database as db_module
        close_db()
        db_module._conn = None

        import sqlite3
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute(
            "SELECT quantity, locked_quantity FROM reagents WHERE id = ?",
            (reagent_id,)
        )
        row = cursor.fetchone()
        conn.close()

        print(f"\n  直接读取数据库:")
        print(f"    总库存: {row[0]}")
        print(f"    锁定量: {row[1]}")

        db_module.DB_PATH = db_path
        init_database()
        total, locked, available = print_stock_status(reagent_id, "重启后读取")
        assert total == row[0]
        assert locked == row[1]
        assert available == total - locked
        print("\n  ✅ 重启后数据完全一致")

        print_header("第9步：验证CSV导出数据一致性")
        from csv_utils import CSVManager
        csv_mgr = CSVManager(auth)
        export_path = "demo_export_reschedule.csv"
        import csv
        count, msg = csv_mgr.export_reagents(export_path)

        with open(export_path, 'r', encoding='utf-8-sig') as f:
            reader = csv.DictReader(f)
            for row in reader:
                if row["试剂名称"] == "演示试剂-改期测试":
                    export_total = int(row["总库存"])
                    export_locked = int(row["已锁定量"])
                    export_available = int(row["可用量"])

        print(f"\n  CSV导出数据:")
        print(f"    总库存:   {export_total}")
        print(f"    已锁定量: {export_locked}")
        print(f"    可用量:   {export_available}")
        print(f"    预约摘要: {row['预约摘要']}")

        assert export_total == 75
        assert export_locked == 0
        assert export_available == 75
        assert export_available == export_total - export_locked
        print("\n  ✅ CSV导出数据与实际完全一致")

        os.remove(export_path)

        print_header("✅ 修复验证完成 - 全部通过！")
        print("""
  修复总结：
  ────────────────────────────────────────────────────────────────
  问题根因：
    已审批预约改期时，只给新预约增加锁定量(+quantity)，
    没有先释放原预约的锁定量(-quantity)，
    导致同一笔预约的数量被重复累加，锁定量翻倍。

  修复方案：
    改期逻辑调整为：
    1. 如果原预约是已审批状态 → 先释放原锁定量(-30)
    2. 原预约状态改为 rescheduled
    3. 创建新预约，状态改为 approved
    4. 给新预约锁定(+30)
    → 净变化：0，锁定量保持 30 不变

  状态流转：
    原预约：approved → rescheduled
    新预约：pending → approved

  验证场景：
    ✓ 总库存100 → 创建30预约 → 审批 → 锁定=30
    ✓ 已审批改期 → 锁定仍=30（未翻倍！）
    ✓ 改期后取消 → 锁定=0
    ✓ 改期后领用 → 库存=75，锁定=0
    ✓ 重启后 → 数据一致
    ✓ CSV导出 → 数据一致
  ────────────────────────────────────────────────────────────────
        """)

        return 0

    except AssertionError as e:
        print(f"\n❌ 验证失败: {e}")
        return 1
    except Exception as e:
        print(f"\n❌ 发生错误: {e}")
        import traceback
        traceback.print_exc()
        return 1
    finally:
        try:
            close_db()
        except:
            pass
        try:
            import database as db_module
            db_module._conn = None
            db_module.DB_PATH = original_db_path
        except:
            pass
        try:
            if os.path.exists(db_path):
                import time
                time.sleep(0.1)
                os.remove(db_path)
        except:
            pass


if __name__ == "__main__":
    exit_code = main()
    sys.exit(exit_code)
