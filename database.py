import sqlite3
import os
from datetime import datetime
from typing import List, Dict, Optional, Tuple

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "reagent_management.db")


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_database():
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            role TEXT NOT NULL CHECK(role IN ('admin', 'lab_staff', 'auditor')),
            display_name TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS reagents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            batch_number TEXT NOT NULL,
            quantity INTEGER NOT NULL DEFAULT 0,
            locked_quantity INTEGER NOT NULL DEFAULT 0,
            unit TEXT NOT NULL,
            expiration_date TEXT,
            low_stock_threshold INTEGER NOT NULL DEFAULT 10,
            specification TEXT,
            manufacturer TEXT,
            storage_condition TEXT,
            remarks TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(name, batch_number)
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS operations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            operation_type TEXT NOT NULL CHECK(operation_type IN (
                'stock_in', 'apply_use', 'approve_use', 'reject_use',
                'return', 'scrap', 'stocktake', 'import'
            )),
            reagent_id INTEGER,
            quantity INTEGER,
            operator_id INTEGER NOT NULL,
            reviewer_id INTEGER,
            status TEXT NOT NULL CHECK(status IN (
                'pending', 'approved', 'rejected', 'completed', 'cancelled', 'reverted'
            )),
            operation_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            remarks TEXT,
            revertable INTEGER DEFAULT 1,
            snapshot_before TEXT,
            snapshot_after TEXT,
            FOREIGN KEY (reagent_id) REFERENCES reagents(id),
            FOREIGN KEY (operator_id) REFERENCES users(id),
            FOREIGN KEY (reviewer_id) REFERENCES users(id)
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS inventory_ledger (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            reagent_id INTEGER NOT NULL,
            reagent_name TEXT NOT NULL,
            batch_number TEXT NOT NULL,
            operation_type TEXT NOT NULL,
            change_quantity INTEGER NOT NULL,
            balance_quantity INTEGER NOT NULL,
            operator TEXT NOT NULL,
            reviewer TEXT,
            operation_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            remarks TEXT,
            FOREIGN KEY (reagent_id) REFERENCES reagents(id)
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS app_config (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS reservations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            reagent_id INTEGER NOT NULL,
            reagent_name TEXT NOT NULL,
            batch_number TEXT NOT NULL,
            quantity INTEGER NOT NULL,
            planned_use_date TEXT NOT NULL,
            operator_id INTEGER NOT NULL,
            reviewer_id INTEGER,
            status TEXT NOT NULL CHECK(status IN (
                'pending', 'approved', 'rejected', 'cancelled',
                'completed', 'expired', 'rescheduled'
            )),
            remarks TEXT,
            review_remarks TEXT,
            original_planned_date TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (reagent_id) REFERENCES reagents(id),
            FOREIGN KEY (operator_id) REFERENCES users(id),
            FOREIGN KEY (reviewer_id) REFERENCES users(id)
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS reservation_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            reservation_id INTEGER,
            operation_type TEXT NOT NULL CHECK(operation_type IN (
                'create', 'approve', 'reject', 'cancel', 'complete',
                'expire_release', 'reschedule', 'reschedule_release', 'revert'
            )),
            reagent_id INTEGER,
            reagent_name TEXT,
            batch_number TEXT,
            quantity INTEGER,
            operator_id INTEGER,
            operator_name TEXT,
            reviewer_id INTEGER,
            reviewer_name TEXT,
            status_before TEXT,
            status_after TEXT,
            locked_qty_change INTEGER DEFAULT 0,
            stock_qty_change INTEGER DEFAULT 0,
            remarks TEXT,
            operation_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            revertable INTEGER DEFAULT 0,
            snapshot_before TEXT,
            snapshot_after TEXT,
            FOREIGN KEY (reservation_id) REFERENCES reservations(id),
            FOREIGN KEY (reagent_id) REFERENCES reagents(id)
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS import_results (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            filepath TEXT NOT NULL,
            file_hash TEXT NOT NULL,
            success_count INTEGER NOT NULL DEFAULT 0,
            skip_count INTEGER NOT NULL DEFAULT 0,
            total_rows INTEGER NOT NULL DEFAULT 0,
            errors TEXT,
            warnings TEXT,
            conflict_batches TEXT,
            stock_warnings TEXT,
            operator_id INTEGER NOT NULL,
            operator_name TEXT NOT NULL,
            status TEXT NOT NULL CHECK(status IN ('previewed', 'imported', 'cancelled')),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (operator_id) REFERENCES users(id)
        )
    """)

    cursor.execute("PRAGMA table_info(reagents)")
    columns = [col[1] for col in cursor.fetchall()]
    if 'locked_quantity' not in columns:
        cursor.execute("ALTER TABLE reagents ADD COLUMN locked_quantity INTEGER NOT NULL DEFAULT 0")

    cursor.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='reservation_logs'")
    row = cursor.fetchone()
    if row and 'reschedule_release' not in row[0]:
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS reservation_logs_new (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                reservation_id INTEGER,
                operation_type TEXT NOT NULL CHECK(operation_type IN (
                    'create', 'approve', 'reject', 'cancel', 'complete',
                    'expire_release', 'reschedule', 'reschedule_release', 'revert'
                )),
                reagent_id INTEGER,
                reagent_name TEXT,
                batch_number TEXT,
                quantity INTEGER,
                operator_id INTEGER,
                operator_name TEXT,
                reviewer_id INTEGER,
                reviewer_name TEXT,
                status_before TEXT,
                status_after TEXT,
                locked_qty_change INTEGER DEFAULT 0,
                stock_qty_change INTEGER DEFAULT 0,
                remarks TEXT,
                operation_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                revertable INTEGER DEFAULT 0,
                snapshot_before TEXT,
                snapshot_after TEXT,
                FOREIGN KEY (reservation_id) REFERENCES reservations(id),
                FOREIGN KEY (reagent_id) REFERENCES reagents(id)
            )
        """)
        cursor.execute("""
            INSERT INTO reservation_logs_new SELECT * FROM reservation_logs
        """)
        cursor.execute("DROP TABLE reservation_logs")
        cursor.execute("ALTER TABLE reservation_logs_new RENAME TO reservation_logs")

    cursor.execute("SELECT COUNT(*) FROM users")
    if cursor.fetchone()[0] == 0:
        default_users = [
            ("admin", "admin", "系统管理员"),
            ("lab_staff", "lab_staff", "实验员张工"),
            ("auditor", "auditor", "审核员李工")
        ]
        cursor.executemany(
            "INSERT INTO users (username, role, display_name) VALUES (?, ?, ?)",
            default_users
        )

    cursor.execute("SELECT COUNT(*) FROM app_config WHERE key = 'initialized'")
    if cursor.fetchone()[0] == 0:
        cursor.execute(
            "INSERT INTO app_config (key, value) VALUES (?, ?)",
            ("initialized", "true")
        )

    conn.commit()
    conn.close()


class ReagentDB:
    @staticmethod
    def create(name: str, batch_number: str, quantity: int, unit: str,
               expiration_date: str = None, low_stock_threshold: int = 10,
               specification: str = "", manufacturer: str = "",
               storage_condition: str = "", remarks: str = "") -> int:
        conn = get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("""
                INSERT INTO reagents (name, batch_number, quantity, unit, expiration_date,
                                     low_stock_threshold, specification, manufacturer,
                                     storage_condition, remarks)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (name, batch_number, quantity, unit, expiration_date,
                  low_stock_threshold, specification, manufacturer,
                  storage_condition, remarks))
            conn.commit()
            return cursor.lastrowid
        finally:
            conn.close()

    @staticmethod
    def get_all(filters: Dict = None) -> List[Dict]:
        conn = get_connection()
        cursor = conn.cursor()
        query = "SELECT * FROM reagents WHERE 1=1"
        params = []

        if filters:
            if filters.get("id"):
                query += " AND id = ?"
                params.append(filters["id"])
            if filters.get("batch_number"):
                query += " AND batch_number LIKE ?"
                params.append(f"%{filters['batch_number']}%")
            if filters.get("expired") is True:
                query += " AND expiration_date IS NOT NULL AND expiration_date < ?"
                params.append(datetime.now().strftime("%Y-%m-%d"))
            if filters.get("expired") is False:
                query += " AND (expiration_date IS NULL OR expiration_date >= ?)"
                params.append(datetime.now().strftime("%Y-%m-%d"))
            if filters.get("low_stock"):
                query += " AND quantity <= low_stock_threshold"
            if filters.get("name"):
                query += " AND name LIKE ?"
                params.append(f"%{filters['name']}%")

        query += " ORDER BY updated_at DESC"
        cursor.execute(query, params)
        rows = cursor.fetchall()
        conn.close()
        return [dict(row) for row in rows]

    @staticmethod
    def get_by_id(reagent_id: int) -> Optional[Dict]:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM reagents WHERE id = ?", (reagent_id,))
        row = cursor.fetchone()
        conn.close()
        return dict(row) if row else None

    @staticmethod
    def get_by_name_and_batch(name: str, batch_number: str) -> Optional[Dict]:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM reagents WHERE name = ? AND batch_number = ?",
                       (name, batch_number))
        row = cursor.fetchone()
        conn.close()
        return dict(row) if row else None

    @staticmethod
    def update_quantity(reagent_id: int, quantity_change: int) -> bool:
        conn = get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("""
                UPDATE reagents
                SET quantity = quantity + ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ? AND quantity + ? >= 0
            """, (quantity_change, reagent_id, quantity_change))
            conn.commit()
            return cursor.rowcount > 0
        finally:
            conn.close()

    @staticmethod
    def update(reagent_id: int, **kwargs) -> bool:
        conn = get_connection()
        cursor = conn.cursor()
        try:
            fields = []
            params = []
            for key, value in kwargs.items():
                if key in ["name", "batch_number", "quantity", "unit", "expiration_date",
                           "low_stock_threshold", "specification", "manufacturer",
                           "storage_condition", "remarks"]:
                    fields.append(f"{key} = ?")
                    params.append(value)
            if fields:
                fields.append("updated_at = CURRENT_TIMESTAMP")
                params.append(reagent_id)
                cursor.execute(f"UPDATE reagents SET {', '.join(fields)} WHERE id = ?", params)
                conn.commit()
                return cursor.rowcount > 0
            return False
        finally:
            conn.close()

    @staticmethod
    def delete(reagent_id: int) -> bool:
        conn = get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("DELETE FROM reagents WHERE id = ?", (reagent_id,))
            conn.commit()
            return cursor.rowcount > 0
        finally:
            conn.close()

    @staticmethod
    def is_expired(reagent_id: int) -> bool:
        reagent = ReagentDB.get_by_id(reagent_id)
        if not reagent or not reagent["expiration_date"]:
            return False
        return reagent["expiration_date"] < datetime.now().strftime("%Y-%m-%d")


class OperationDB:
    @staticmethod
    def create(operation_type: str, reagent_id: int = None, quantity: int = None,
               operator_id: int = None, reviewer_id: int = None,
               status: str = "pending", remarks: str = "",
               revertable: int = 1, snapshot_before: str = "",
               snapshot_after: str = "") -> int:
        conn = get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("""
                INSERT INTO operations (operation_type, reagent_id, quantity, operator_id,
                                       reviewer_id, status, remarks, revertable,
                                       snapshot_before, snapshot_after)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (operation_type, reagent_id, quantity, operator_id, reviewer_id,
                  status, remarks, revertable, snapshot_before, snapshot_after))
            conn.commit()
            return cursor.lastrowid
        finally:
            conn.close()

    @staticmethod
    def get_all(limit: int = 100) -> List[Dict]:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT o.*, u1.display_name as operator_name, u2.display_name as reviewer_name,
                   r.name as reagent_name, r.batch_number
            FROM operations o
            LEFT JOIN users u1 ON o.operator_id = u1.id
            LEFT JOIN users u2 ON o.reviewer_id = u2.id
            LEFT JOIN reagents r ON o.reagent_id = r.id
            ORDER BY o.operation_time DESC
            LIMIT ?
        """, (limit,))
        rows = cursor.fetchall()
        conn.close()
        return [dict(row) for row in rows]

    @staticmethod
    def get_by_id(operation_id: int) -> Optional[Dict]:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT o.*, u1.display_name as operator_name, u2.display_name as reviewer_name,
                   r.name as reagent_name, r.batch_number
            FROM operations o
            LEFT JOIN users u1 ON o.operator_id = u1.id
            LEFT JOIN users u2 ON o.reviewer_id = u2.id
            LEFT JOIN reagents r ON o.reagent_id = r.id
            WHERE o.id = ?
        """, (operation_id,))
        row = cursor.fetchone()
        conn.close()
        return dict(row) if row else None

    @staticmethod
    def get_pending_approvals() -> List[Dict]:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT o.*, u1.display_name as operator_name,
                   r.name as reagent_name, r.batch_number, r.quantity as current_quantity
            FROM operations o
            LEFT JOIN users u1 ON o.operator_id = u1.id
            LEFT JOIN reagents r ON o.reagent_id = r.id
            WHERE o.operation_type = 'apply_use' AND o.status = 'pending'
            ORDER BY o.operation_time DESC
        """)
        rows = cursor.fetchall()
        conn.close()
        return [dict(row) for row in rows]

    @staticmethod
    def update_status(operation_id: int, status: str, reviewer_id: int = None,
                      remarks: str = None) -> bool:
        conn = get_connection()
        cursor = conn.cursor()
        try:
            fields = ["status = ?"]
            params = [status]
            if reviewer_id:
                fields.append("reviewer_id = ?")
                params.append(reviewer_id)
            if remarks:
                fields.append("remarks = ?")
                params.append(remarks)
            params.append(operation_id)
            cursor.execute(
                f"UPDATE operations SET {', '.join(fields)} WHERE id = ?",
                params
            )
            conn.commit()
            return cursor.rowcount > 0
        finally:
            conn.close()

    @staticmethod
    def mark_reverted(operation_id: int) -> bool:
        conn = get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("""
                UPDATE operations SET status = 'reverted', revertable = 0
                WHERE id = ?
            """, (operation_id,))
            conn.commit()
            return cursor.rowcount > 0
        finally:
            conn.close()

    @staticmethod
    def get_last_revertable() -> Optional[Dict]:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT o.*, u1.display_name as operator_name, u2.display_name as reviewer_name,
                   r.name as reagent_name, r.batch_number
            FROM operations o
            LEFT JOIN users u1 ON o.operator_id = u1.id
            LEFT JOIN users u2 ON o.reviewer_id = u2.id
            LEFT JOIN reagents r ON o.reagent_id = r.id
            WHERE o.revertable = 1 AND o.status IN ('completed', 'approved')
              AND o.operation_type IN ('stock_in', 'approve_use', 'return', 'scrap', 'stocktake')
            ORDER BY o.operation_time DESC, o.id DESC
            LIMIT 1
        """)
        row = cursor.fetchone()
        conn.close()
        return dict(row) if row else None


class UserDB:
    @staticmethod
    def get_all() -> List[Dict]:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM users ORDER BY id")
        rows = cursor.fetchall()
        conn.close()
        return [dict(row) for row in rows]

    @staticmethod
    def get_by_username(username: str) -> Optional[Dict]:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM users WHERE username = ?", (username,))
        row = cursor.fetchone()
        conn.close()
        return dict(row) if row else None

    @staticmethod
    def get_by_id(user_id: int) -> Optional[Dict]:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM users WHERE id = ?", (user_id,))
        row = cursor.fetchone()
        conn.close()
        return dict(row) if row else None


class LedgerDB:
    @staticmethod
    def create(reagent_id: int, reagent_name: str, batch_number: str,
               operation_type: str, change_quantity: int, balance_quantity: int,
               operator: str, reviewer: str = None, remarks: str = "") -> int:
        conn = get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("""
                INSERT INTO inventory_ledger (reagent_id, reagent_name, batch_number,
                                             operation_type, change_quantity, balance_quantity,
                                             operator, reviewer, remarks)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (reagent_id, reagent_name, batch_number, operation_type,
                  change_quantity, balance_quantity, operator, reviewer, remarks))
            conn.commit()
            return cursor.lastrowid
        finally:
            conn.close()

    @staticmethod
    def get_all(filters: Dict = None) -> List[Dict]:
        conn = get_connection()
        cursor = conn.cursor()
        query = "SELECT * FROM inventory_ledger WHERE 1=1"
        params = []

        if filters:
            if filters.get("reagent_name"):
                query += " AND reagent_name LIKE ?"
                params.append(f"%{filters['reagent_name']}%")
            if filters.get("batch_number"):
                query += " AND batch_number LIKE ?"
                params.append(f"%{filters['batch_number']}%")
            if filters.get("operation_type"):
                query += " AND operation_type = ?"
                params.append(filters["operation_type"])
            if filters.get("start_date"):
                query += " AND DATE(operation_time) >= ?"
                params.append(filters["start_date"])
            if filters.get("end_date"):
                query += " AND DATE(operation_time) <= ?"
                params.append(filters["end_date"])

        query += " ORDER BY operation_time DESC"
        cursor.execute(query, params)
        rows = cursor.fetchall()
        conn.close()
        return [dict(row) for row in rows]

    @staticmethod
    def delete_last_for_reagent(reagent_id: int, operation_type: str) -> bool:
        conn = get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("""
                DELETE FROM inventory_ledger
                WHERE id = (
                    SELECT id FROM inventory_ledger
                    WHERE reagent_id = ? AND operation_type = ?
                    ORDER BY operation_time DESC
                    LIMIT 1
                )
            """, (reagent_id, operation_type))
            conn.commit()
            return cursor.rowcount > 0
        finally:
            conn.close()


class ReagentLockDB:
    @staticmethod
    def update_locked_quantity(reagent_id: int, locked_change: int) -> bool:
        conn = get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("""
                UPDATE reagents
                SET locked_quantity = locked_quantity + ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ? AND locked_quantity + ? >= 0
                  AND quantity >= locked_quantity + ?
            """, (locked_change, reagent_id, locked_change, locked_change))
            conn.commit()
            return cursor.rowcount > 0
        finally:
            conn.close()

    @staticmethod
    def get_available_quantity(reagent_id: int) -> int:
        reagent = ReagentDB.get_by_id(reagent_id)
        if not reagent:
            return 0
        return reagent["quantity"] - reagent.get("locked_quantity", 0)

    @staticmethod
    def get_total_locked_for_reagent(reagent_id: int) -> int:
        conn = get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("""
                SELECT COALESCE(SUM(quantity), 0)
                FROM reservations
                WHERE reagent_id = ? AND status = 'approved'
            """, (reagent_id,))
            result = cursor.fetchone()
            return result[0] if result else 0
        finally:
            conn.close()


class ReservationDB:
    @staticmethod
    def create(reagent_id: int, reagent_name: str, batch_number: str,
               quantity: int, planned_use_date: str, operator_id: int,
               remarks: str = "", original_planned_date: str = None) -> int:
        conn = get_connection()
        cursor = conn.cursor()
        try:
            orig_date = original_planned_date if original_planned_date else planned_use_date
            cursor.execute("""
                INSERT INTO reservations (
                    reagent_id, reagent_name, batch_number, quantity,
                    planned_use_date, operator_id, status, remarks,
                    original_planned_date
                ) VALUES (?, ?, ?, ?, ?, ?, 'pending', ?, ?)
            """, (reagent_id, reagent_name, batch_number, quantity,
                  planned_use_date, operator_id, remarks, orig_date))
            conn.commit()
            return cursor.lastrowid
        finally:
            conn.close()

    @staticmethod
    def get_by_id(reservation_id: int) -> Optional[Dict]:
        conn = get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("""
                SELECT r.*, u1.display_name as operator_name,
                       u2.display_name as reviewer_name,
                       re.quantity as current_stock,
                       re.locked_quantity as current_locked
                FROM reservations r
                LEFT JOIN users u1 ON r.operator_id = u1.id
                LEFT JOIN users u2 ON r.reviewer_id = u2.id
                LEFT JOIN reagents re ON r.reagent_id = re.id
                WHERE r.id = ?
            """, (reservation_id,))
            row = cursor.fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    @staticmethod
    def get_all(filters: Dict = None) -> List[Dict]:
        conn = get_connection()
        cursor = conn.cursor()
        query = """
            SELECT r.*, u1.display_name as operator_name,
                   u2.display_name as reviewer_name,
                   re.quantity as current_stock,
                   re.locked_quantity as current_locked,
                   re.unit as unit
            FROM reservations r
            LEFT JOIN users u1 ON r.operator_id = u1.id
            LEFT JOIN users u2 ON r.reviewer_id = u2.id
            LEFT JOIN reagents re ON r.reagent_id = re.id
            WHERE 1=1
        """
        params = []

        if filters:
            if filters.get("reagent_name"):
                query += " AND r.reagent_name LIKE ?"
                params.append(f"%{filters['reagent_name']}%")
            if filters.get("batch_number"):
                query += " AND r.batch_number LIKE ?"
                params.append(f"%{filters['batch_number']}%")
            if filters.get("status"):
                query += " AND r.status = ?"
                params.append(filters["status"])
            if filters.get("operator_id"):
                query += " AND r.operator_id = ?"
                params.append(filters["operator_id"])
            if filters.get("start_date"):
                query += " AND DATE(r.created_at) >= ?"
                params.append(filters["start_date"])
            if filters.get("end_date"):
                query += " AND DATE(r.created_at) <= ?"
                params.append(filters["end_date"])
            if filters.get("planned_start_date"):
                query += " AND DATE(r.planned_use_date) >= ?"
                params.append(filters["planned_start_date"])
            if filters.get("planned_end_date"):
                query += " AND DATE(r.planned_use_date) <= ?"
                params.append(filters["planned_end_date"])

        query += " ORDER BY r.created_at DESC"
        cursor.execute(query, params)
        rows = cursor.fetchall()
        conn.close()
        return [dict(row) for row in rows]

    @staticmethod
    def get_pending_approvals() -> List[Dict]:
        return ReservationDB.get_all({"status": "pending"})

    @staticmethod
    def update_status(reservation_id: int, status: str,
                      reviewer_id: int = None, review_remarks: str = None,
                      planned_use_date: str = None) -> bool:
        conn = get_connection()
        cursor = conn.cursor()
        try:
            fields = ["status = ?", "updated_at = CURRENT_TIMESTAMP"]
            params = [status]

            if reviewer_id:
                fields.append("reviewer_id = ?")
                params.append(reviewer_id)
            if review_remarks:
                fields.append("review_remarks = ?")
                params.append(review_remarks)
            if planned_use_date:
                fields.append("planned_use_date = ?")
                params.append(planned_use_date)

            params.append(reservation_id)
            cursor.execute(
                f"UPDATE reservations SET {', '.join(fields)} WHERE id = ?",
                params
            )
            conn.commit()
            return cursor.rowcount > 0
        finally:
            conn.close()

    @staticmethod
    def get_active_reservations_for_reagent(reagent_id: int) -> List[Dict]:
        return ReservationDB.get_all({
            "status": "approved",
            "reagent_id": reagent_id
        })

    @staticmethod
    def get_expired_reservations() -> List[Dict]:
        conn = get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("""
                SELECT r.*, u1.display_name as operator_name,
                       u2.display_name as reviewer_name,
                       re.quantity as current_stock,
                       re.locked_quantity as current_locked,
                       re.unit as unit
                FROM reservations r
                LEFT JOIN users u1 ON r.operator_id = u1.id
                LEFT JOIN users u2 ON r.reviewer_id = u2.id
                LEFT JOIN reagents re ON r.reagent_id = re.id
                WHERE r.status = 'approved'
                  AND DATE(r.planned_use_date) < DATE('now')
                ORDER BY r.planned_use_date ASC
            """)
            rows = cursor.fetchall()
            conn.close()
            return [dict(row) for row in rows]
        finally:
            conn.close()

    @staticmethod
    def get_reservation_summary_for_reagent(reagent_id: int) -> str:
        active = ReservationDB.get_active_reservations_for_reagent(reagent_id)
        if not active:
            return ""
        summaries = []
        for res in active[:3]:
            summaries.append(
                f"{res['operator_name']}预约{res['quantity']}"
                f"({res['planned_use_date']})"
            )
        result = ";".join(summaries)
        if len(active) > 3:
            result += f"等{len(active)}个预约"
        return result


class ReservationLogDB:
    @staticmethod
    def create(operation_type: str, reservation_id: int = None,
               reagent_id: int = None, reagent_name: str = None,
               batch_number: str = None, quantity: int = None,
               operator_id: int = None, operator_name: str = None,
               reviewer_id: int = None, reviewer_name: str = None,
               status_before: str = None, status_after: str = None,
               locked_qty_change: int = 0, stock_qty_change: int = 0,
               remarks: str = "", revertable: int = 0,
               snapshot_before: str = "", snapshot_after: str = "") -> int:
        conn = get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("""
                INSERT INTO reservation_logs (
                    operation_type, reservation_id, reagent_id, reagent_name,
                    batch_number, quantity, operator_id, operator_name,
                    reviewer_id, reviewer_name, status_before, status_after,
                    locked_qty_change, stock_qty_change, remarks,
                    revertable, snapshot_before, snapshot_after
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (operation_type, reservation_id, reagent_id, reagent_name,
                  batch_number, quantity, operator_id, operator_name,
                  reviewer_id, reviewer_name, status_before, status_after,
                  locked_qty_change, stock_qty_change, remarks,
                  revertable, snapshot_before, snapshot_after))
            conn.commit()
            return cursor.lastrowid
        finally:
            conn.close()

    @staticmethod
    def get_all(filters: Dict = None) -> List[Dict]:
        conn = get_connection()
        cursor = conn.cursor()
        query = "SELECT * FROM reservation_logs WHERE 1=1"
        params = []

        if filters:
            if filters.get("reservation_id"):
                query += " AND reservation_id = ?"
                params.append(filters["reservation_id"])
            if filters.get("reagent_name"):
                query += " AND reagent_name LIKE ?"
                params.append(f"%{filters['reagent_name']}%")
            if filters.get("batch_number"):
                query += " AND batch_number LIKE ?"
                params.append(f"%{filters['batch_number']}%")
            if filters.get("operation_type"):
                query += " AND operation_type = ?"
                params.append(filters["operation_type"])
            if filters.get("operator_name"):
                query += " AND operator_name LIKE ?"
                params.append(f"%{filters['operator_name']}%")
            if filters.get("start_date"):
                query += " AND DATE(operation_time) >= ?"
                params.append(filters["start_date"])
            if filters.get("end_date"):
                query += " AND DATE(operation_time) <= ?"
                params.append(filters["end_date"])

        query += " ORDER BY operation_time DESC"
        cursor.execute(query, params)
        rows = cursor.fetchall()
        conn.close()
        return [dict(row) for row in rows]

    @staticmethod
    def get_last_revertable() -> Optional[Dict]:
        conn = get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("""
                SELECT * FROM reservation_logs
                WHERE revertable = 1
                ORDER BY operation_time DESC, id DESC
                LIMIT 1
            """)
            row = cursor.fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    @staticmethod
    def mark_reverted(log_id: int) -> bool:
        conn = get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("""
                UPDATE reservation_logs
                SET revertable = 0, operation_type = 'revert'
                WHERE id = ?
            """, (log_id,))
            conn.commit()
            return cursor.rowcount > 0
        finally:
            conn.close()


class ImportResultDB:
    @staticmethod
    def create(filepath: str, file_hash: str, success_count: int, skip_count: int,
               total_rows: int, errors: List[str] = None, warnings: List[str] = None,
               conflict_batches: List[str] = None, stock_warnings: List[str] = None,
               operator_id: int = None, operator_name: str = "",
               status: str = "previewed") -> int:
        import json
        conn = get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("""
                INSERT INTO import_results (
                    filepath, file_hash, success_count, skip_count, total_rows,
                    errors, warnings, conflict_batches, stock_warnings,
                    operator_id, operator_name, status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                filepath, file_hash, success_count, skip_count, total_rows,
                json.dumps(errors or [], ensure_ascii=False),
                json.dumps(warnings or [], ensure_ascii=False),
                json.dumps(conflict_batches or [], ensure_ascii=False),
                json.dumps(stock_warnings or [], ensure_ascii=False),
                operator_id, operator_name, status
            ))
            conn.commit()
            return cursor.lastrowid
        finally:
            conn.close()

    @staticmethod
    def get_by_id(result_id: int) -> Optional[Dict]:
        import json
        conn = get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("SELECT * FROM import_results WHERE id = ?", (result_id,))
            row = cursor.fetchone()
            if row:
                result = dict(row)
                for key in ['errors', 'warnings', 'conflict_batches', 'stock_warnings']:
                    if result.get(key):
                        result[key] = json.loads(result[key])
                return result
            return None
        finally:
            conn.close()

    @staticmethod
    def get_by_file_hash(file_hash: str) -> Optional[Dict]:
        import json
        conn = get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("""
                SELECT * FROM import_results
                WHERE file_hash = ? AND status IN ('previewed', 'imported')
                ORDER BY created_at DESC
                LIMIT 1
            """, (file_hash,))
            row = cursor.fetchone()
            if row:
                result = dict(row)
                for key in ['errors', 'warnings', 'conflict_batches', 'stock_warnings']:
                    if result.get(key):
                        result[key] = json.loads(result[key])
                return result
            return None
        finally:
            conn.close()

    @staticmethod
    def update_status(result_id: int, status: str, success_count: int = None,
                      skip_count: int = None) -> bool:
        conn = get_connection()
        cursor = conn.cursor()
        try:
            fields = ["status = ?", "updated_at = CURRENT_TIMESTAMP"]
            params = [status]
            if success_count is not None:
                fields.append("success_count = ?")
                params.append(success_count)
            if skip_count is not None:
                fields.append("skip_count = ?")
                params.append(skip_count)
            params.append(result_id)
            cursor.execute(
                f"UPDATE import_results SET {', '.join(fields)} WHERE id = ?",
                params
            )
            conn.commit()
            return cursor.rowcount > 0
        finally:
            conn.close()

    @staticmethod
    def get_all(limit: int = 100) -> List[Dict]:
        import json
        conn = get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("""
                SELECT * FROM import_results
                ORDER BY created_at DESC
                LIMIT ?
            """, (limit,))
            rows = cursor.fetchall()
            results = []
            for row in rows:
                result = dict(row)
                for key in ['errors', 'warnings', 'conflict_batches', 'stock_warnings']:
                    if result.get(key):
                        result[key] = json.loads(result[key])
                results.append(result)
            return results
        finally:
            conn.close()


def close_db():
    try:
        conn = get_connection()
        conn.close()
    except Exception:
        pass
