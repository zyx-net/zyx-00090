import tkinter as tk
import sys
sys.path.insert(0, '.')
from app import ReagentManagementApp

def test_admin_login():
    print('测试1: 管理员登录后构建主界面...')
    root = tk.Tk()
    root.withdraw()
    try:
        app = ReagentManagementApp(root)
        app.auth.login('admin')
        app.setup_main_ui()
        assert hasattr(app, 'status_var'), 'status_var 应该已初始化'
        assert app.status_var.get() is not None, 'status_var 应该有值'
        assert len(app.status_var.get()) > 0, 'status_var 不应为空字符串'
        assert hasattr(app, 'import_status_var'), 'import_status_var 应该已初始化'
        assert hasattr(app, 'btn_preview'), 'btn_preview 应该已创建'
        assert hasattr(app, 'btn_import'), 'btn_import 应该已创建'
        assert hasattr(app, 'btn_reset_preview'), 'btn_reset_preview 应该已创建'
        print('  ✓ 管理员主界面构建成功，所有导入相关组件已初始化')
        
        tab_count = len(app.notebook.tabs())
        assert tab_count == 8, f'应该有8个标签页，实际有{tab_count}个'
        print(f'  ✓ 标签页数量正确：{tab_count}个')
        
        return app, root
    except Exception as e:
        print(f'  ✗ 失败：{type(e).__name__}: {e}')
        import traceback
        traceback.print_exc()
        root.destroy()
        return None, None

def test_import_page_accessible(app, root):
    print('\n测试2: 导入页可正常访问...')
    try:
        app.notebook.select(app.tab_import_export)
        tab_text = app.notebook.tab(app.notebook.select(), 'text')
        assert tab_text == '导入导出', f'选中的标签页应为"导入导出"，实际是"{tab_text}"'
        print('  ✓ 导入导出标签页可正常切换')
        
        import_status = app.import_status_var.get()
        assert '请选择CSV文件' in import_status, f'导入状态提示不正确：{import_status}'
        print(f'  ✓ 导入页状态提示正确：{import_status}')
        
        btn_preview_state = str(app.btn_preview.cget('state'))
        btn_import_state = str(app.btn_import.cget('state'))
        btn_reset_state = str(app.btn_reset_preview.cget('state'))
        
        assert btn_preview_state == 'disabled', f'未选择文件时预检按钮应禁用，实际是{btn_preview_state}'
        assert btn_import_state == 'disabled', f'未预检时导入按钮应禁用，实际是{btn_import_state}'
        assert btn_reset_state == 'disabled', f'无预检结果时重置按钮应禁用，实际是{btn_reset_state}'
        print('  ✓ 按钮初始状态正确（均禁用）')
        
        return True
    except Exception as e:
        print(f'  ✗ 失败：{type(e).__name__}: {e}')
        import traceback
        traceback.print_exc()
        return False

def test_lab_staff_permission_denied():
    print('\n测试3: 实验员登录后看到禁用提示...')
    root = tk.Tk()
    root.withdraw()
    try:
        app = ReagentManagementApp(root)
        app.auth.login('lab_staff')
        app.setup_main_ui()
        assert hasattr(app, 'status_var'), 'status_var 应该已初始化'
        print('  ✓ 实验员主界面构建成功')
        
        app.notebook.select(app.tab_import_export)
        
        has_perm = app.auth.has_permission('import_csv')
        assert not has_perm, '实验员不应该有导入权限'
        print('  ✓ 实验员权限校验正确（无导入权限）')
        
        assert not hasattr(app, 'btn_preview'), '无权限时不应创建预检按钮'
        assert not hasattr(app, 'btn_import'), '无权限时不应创建导入按钮'
        assert not hasattr(app, 'btn_reset_preview'), '无权限时不应创建重置按钮'
        print('  ✓ 无权限时未创建操作按钮')
        
        root.destroy()
        return True
    except Exception as e:
        print(f'  ✗ 失败：{type(e).__name__}: {e}')
        import traceback
        traceback.print_exc()
        root.destroy()
        return False

def test_auditor_permission_denied():
    print('\n测试4: 审核员登录后看到禁用提示...')
    root = tk.Tk()
    root.withdraw()
    try:
        app = ReagentManagementApp(root)
        app.auth.login('auditor')
        app.setup_main_ui()
        assert hasattr(app, 'status_var'), 'status_var 应该已初始化'
        print('  ✓ 审核员主界面构建成功')
        
        app.notebook.select(app.tab_import_export)
        
        has_perm = app.auth.has_permission('import_csv')
        assert not has_perm, '审核员不应该有导入权限'
        print('  ✓ 审核员权限校验正确（无导入权限）')
        
        assert not hasattr(app, 'btn_preview'), '无权限时不应创建预检按钮'
        assert not hasattr(app, 'btn_import'), '无权限时不应创建导入按钮'
        assert not hasattr(app, 'btn_reset_preview'), '无权限时不应创建重置按钮'
        print('  ✓ 无权限时未创建操作按钮')
        
        root.destroy()
        return True
    except Exception as e:
        print(f'  ✗ 失败：{type(e).__name__}: {e}')
        import traceback
        traceback.print_exc()
        root.destroy()
        return False

# 运行测试
print('=' * 60)
print('GUI 构建验证测试')
print('=' * 60)

passed = 0
failed = 0

app, admin_root = test_admin_login()
if app and admin_root:
    if test_import_page_accessible(app, admin_root):
        passed += 1
    else:
        failed += 1
    admin_root.destroy()
    passed += 1
else:
    failed += 1

if test_lab_staff_permission_denied():
    passed += 1
else:
    failed += 1

if test_auditor_permission_denied():
    passed += 1
else:
    failed += 1

print('\n' + '=' * 60)
print(f'测试结果：通过 {passed} 项，失败 {failed} 项')
print('=' * 60)

if failed == 0:
    print('\n[SUCCESS] 所有 GUI 构建测试通过！')
    sys.exit(0)
else:
    print(f'\n[FAILURE] 有 {failed} 项测试未通过')
    sys.exit(1)
