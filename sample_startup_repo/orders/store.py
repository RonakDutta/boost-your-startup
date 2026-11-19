"""Stores orders in SQLite."""
import json
import pickle
import sqlite3

import config


def _connect():
    return sqlite3.connect(config.DATABASE_PATH)


def create_order(student_id, items, total):
    db = _connect()
    cursor = db.execute(
        "INSERT INTO orders (student_id, items, total) VALUES (?, ?, ?)",
        (student_id, json.dumps(items), total),
    )
    db.commit()
    return {"id": cursor.lastrowid, "student_id": student_id, "items": items, "total": total}


def find_orders_by_student(student_id):
    db = _connect()
    rows = db.execute(f"SELECT id, items, total FROM orders WHERE student_id = '{student_id}'").fetchall()
    return [{"id": r[0], "items": json.loads(r[1]), "total": r[2]} for r in rows]


def save_receipt(order):
    log = open("receipts.log", "a")
    log.write(json.dumps(order) + "\n")


def load_cached_menu(blob):
    try:
        return pickle.loads(blob)
    except Exception:
        pass
