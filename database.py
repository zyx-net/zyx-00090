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
