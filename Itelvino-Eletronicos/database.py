import hashlib
import os
import secrets
import sqlite3
from datetime import datetime
from pathlib import Path


def data_directory():
    configured = os.environ.get("ITELVINO_DATA_DIR")
    if configured:
        path = Path(configured)
    else:
        base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        path = Path(base) / "ItelvinoEletronicos"
    path.mkdir(parents=True, exist_ok=True)
    return path



def now_text():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


class Database:
    def __init__(self):
        self.path = data_directory() / "itelvino.db"
        self.initialize()

    def connect(self):
        conn = sqlite3.connect(self.path, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA busy_timeout = 30000")
        return conn

    def initialize(self):
        with self.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS users (
                    username TEXT PRIMARY KEY COLLATE NOCASE,
                    salt TEXT NOT NULL,
                    password_hash TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS products (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    barcode TEXT NOT NULL UNIQUE,
                    description TEXT NOT NULL,
                    quantity INTEGER NOT NULL DEFAULT 0 CHECK(quantity >= 0),
                    cost REAL NOT NULL DEFAULT 0,
                    price REAL NOT NULL DEFAULT 0,
                    photo_path TEXT,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS sales (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    subtotal REAL NOT NULL,
                    discount_percent REAL NOT NULL DEFAULT 0,
                    discount_value REAL NOT NULL DEFAULT 0,
                    total REAL NOT NULL,
                    payment_method TEXT NOT NULL,
                    installments INTEGER NOT NULL DEFAULT 1,
                    username TEXT NOT NULL DEFAULT 'Histórico anterior',
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS sale_items (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    sale_id INTEGER NOT NULL REFERENCES sales(id),
                    product_id INTEGER NOT NULL REFERENCES products(id),
                    barcode TEXT NOT NULL,
                    description TEXT NOT NULL,
                    quantity INTEGER NOT NULL,
                    unit_price REAL NOT NULL,
                    unit_cost REAL,
                    line_total REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS movements (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    product_id INTEGER NOT NULL REFERENCES products(id),
                    kind TEXT NOT NULL,
                    quantity INTEGER NOT NULL,
                    unit_cost REAL NOT NULL DEFAULT 0,
                    note TEXT NOT NULL DEFAULT '',
                    sale_id INTEGER REFERENCES sales(id),
                    username TEXT NOT NULL DEFAULT 'Histórico anterior',
                    created_at TEXT NOT NULL
                );
            """)
            product_columns = {row["name"] for row in db.execute("PRAGMA table_info(products)")}
            if "photo_path" not in product_columns:
                db.execute("ALTER TABLE products ADD COLUMN photo_path TEXT")
            item_columns = {row["name"] for row in db.execute("PRAGMA table_info(sale_items)")}
            if "unit_cost" not in item_columns:
                # Recover the sale-time cost from stock history where available.
                db.execute("ALTER TABLE sale_items ADD COLUMN unit_cost REAL")
                db.execute("""
                    UPDATE sale_items
                    SET unit_cost=(
                        SELECT m.unit_cost FROM movements m
                        WHERE m.sale_id=sale_items.sale_id
                          AND m.product_id=sale_items.product_id
                          AND m.kind='Venda'
                        LIMIT 1
                    )
                    WHERE EXISTS (
                        SELECT 1 FROM movements m
                        WHERE m.sale_id=sale_items.sale_id
                          AND m.product_id=sale_items.product_id
                          AND m.kind='Venda'
                    )
                """)
            sales_columns = {row["name"] for row in db.execute("PRAGMA table_info(sales)")}
            if "username" not in sales_columns:
                db.execute("ALTER TABLE sales ADD COLUMN username TEXT NOT NULL DEFAULT 'Histórico anterior'")
            movement_columns = {row["name"] for row in db.execute("PRAGMA table_info(movements)")}
            if "username" not in movement_columns:
                db.execute("ALTER TABLE movements ADD COLUMN username TEXT NOT NULL DEFAULT 'Histórico anterior'")
            legacy = {row["key"]: row["value"] for row in db.execute("SELECT key,value FROM settings")}
            if legacy.get("username") and legacy.get("salt") and legacy.get("password_hash"):
                db.execute(
                    "INSERT OR IGNORE INTO users(username,salt,password_hash,created_at) VALUES(?,?,?,?)",
                    (legacy["username"], legacy["salt"], legacy["password_hash"], now_text()),
                )

    def has_user(self):
        with self.connect() as db:
            return db.execute("SELECT 1 FROM users LIMIT 1").fetchone() is not None

    def _password_values(self, password):
        salt = secrets.token_bytes(16)
        digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 240000).hex()
        return salt.hex(), digest

    def setup_user(self, username, password):
        salt, digest = self._password_values(password)
        with self.connect() as db:
            db.execute("INSERT INTO users(username,salt,password_hash,created_at) VALUES(?,?,?,?)",
                       (username, salt, digest, now_text()))

    def add_user(self, username, password):
        salt, digest = self._password_values(password)
        try:
            with self.connect() as db:
                db.execute("INSERT INTO users(username,salt,password_hash,created_at) VALUES(?,?,?,?)",
                           (username, salt, digest, now_text()))
        except sqlite3.IntegrityError as exc:
            raise ValueError("Já existe um usuário com esse nome.") from exc

    def authenticate(self, username, password):
        with self.connect() as db:
            record = db.execute("SELECT username,salt,password_hash FROM users WHERE username=?", (username.strip(),)).fetchone()
        if not record:
            return False
        digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(record["salt"]), 240000).hex()
        return secrets.compare_digest(digest, record["password_hash"])

    def canonical_username(self, username):
        with self.connect() as db:
            record = db.execute("SELECT username FROM users WHERE username=?", (username.strip(),)).fetchone()
            return record["username"] if record else username.strip()

    def change_password(self, username, current_password, new_password):
        if not self.authenticate(username, current_password):
            raise ValueError("Usuário ou senha atual incorretos.")
        salt, digest = self._password_values(new_password)
        with self.connect() as db:
            db.execute("UPDATE users SET salt=?,password_hash=? WHERE username=?", (salt, digest, username.strip()))

    def products(self, search=""):
        with self.connect() as db:
            return db.execute(
                "SELECT * FROM products WHERE barcode LIKE ? OR description LIKE ? ORDER BY description COLLATE NOCASE",
                (f"%{search}%", f"%{search}%"),
            ).fetchall()

    def product(self, product_id):
        with self.connect() as db:
            return db.execute("SELECT * FROM products WHERE id=?", (product_id,)).fetchone()

    def by_barcode(self, barcode):
        with self.connect() as db:
            return db.execute("SELECT * FROM products WHERE barcode=?", (barcode.strip(),)).fetchone()

    def save_product(self, product_id, barcode, description, cost, price, initial_qty, photo_path, username):
        stamp = now_text()
        with self.connect() as db:
            if product_id:
                db.execute("UPDATE products SET barcode=?,description=?,cost=?,price=?,photo_path=? WHERE id=?",
                           (barcode, description, cost, price, photo_path, product_id))
            else:
                cursor = db.execute(
                    "INSERT INTO products(barcode,description,cost,price,photo_path,created_at) VALUES(?,?,?,?,?,?)",
                    (barcode, description, cost, price, photo_path, stamp),
                )
                product_id = cursor.lastrowid
                if initial_qty > 0:
                    db.execute("UPDATE products SET quantity=? WHERE id=?", (initial_qty, product_id))
                    db.execute("INSERT INTO movements(product_id,kind,quantity,unit_cost,note,username,created_at) VALUES(?,?,?,?,?,?,?)",
                               (product_id, "Entrada inicial", initial_qty, cost, "Saldo inicial do cadastro", username, stamp))
        return product_id

    def stock_movement(self, product_id, kind, quantity, unit_cost, note, username):
        stamp = now_text()
        with self.connect() as db:
            product = db.execute("SELECT quantity FROM products WHERE id=?", (product_id,)).fetchone()
            if not product:
                raise ValueError("Produto não encontrado.")
            if kind == "Entrada":
                db.execute("UPDATE products SET quantity=quantity+?,cost=? WHERE id=?", (quantity, unit_cost, product_id))
            else:
                if product["quantity"] < quantity:
                    raise ValueError("A saída é maior que o saldo atual do produto.")
                db.execute("UPDATE products SET quantity=quantity-? WHERE id=?", (quantity, product_id))
            db.execute("INSERT INTO movements(product_id,kind,quantity,unit_cost,note,username,created_at) VALUES(?,?,?,?,?,?,?)",
                       (product_id, kind, quantity, unit_cost, note, username, stamp))

    def complete_sale(self, cart, discount_percent, payment_method, installments, username):
        subtotal = sum(item["qty"] * item["price"] for item in cart)
        discount_value = round(subtotal * discount_percent / 100, 2)
        total = round(subtotal - discount_value, 2)
        stamp = now_text()
        with self.connect() as db:
            costs = {}
            for item in cart:
                row = db.execute("SELECT quantity,cost FROM products WHERE id=?", (item["id"],)).fetchone()
                if row is None or row["quantity"] < item["qty"]:
                    raise ValueError(f"Estoque insuficiente para {item['description']}.")
                costs[item["id"]] = row["cost"]
            cur = db.execute(
                "INSERT INTO sales(subtotal,discount_percent,discount_value,total,payment_method,installments,username,created_at) VALUES(?,?,?,?,?,?,?,?)",
                (subtotal, discount_percent, discount_value, total, payment_method, installments, username, stamp),
            )
            sale_id = cur.lastrowid
            for item in cart:
                line_total = round(item["qty"] * item["price"], 2)
                db.execute("INSERT INTO sale_items(sale_id,product_id,barcode,description,quantity,unit_price,unit_cost,line_total) VALUES(?,?,?,?,?,?,?,?)",
                           (sale_id, item["id"], item["barcode"], item["description"], item["qty"], item["price"], costs[item["id"]], line_total))
                db.execute("UPDATE products SET quantity=quantity-? WHERE id=?", (item["qty"], item["id"]))
                db.execute("INSERT INTO movements(product_id,kind,quantity,unit_cost,note,sale_id,username,created_at) VALUES(?,?,?,?,?,?,?,?)",
                           (item["id"], "Venda", item["qty"], costs[item["id"]], f"Venda #{sale_id}", sale_id, username, stamp))
        return sale_id, subtotal, discount_value, total

    def _sales_where(self, date_expression, date_value, sale_number="", item_query=""):
        conditions = [date_expression]
        values = [date_value]
        if sale_number:
            conditions.append("s.id=?")
            values.append(int(sale_number))
        if item_query:
            conditions.append("EXISTS (SELECT 1 FROM sale_items fi WHERE fi.sale_id=s.id AND (fi.barcode LIKE ? OR fi.description LIKE ?))")
            values.extend((f"%{item_query}%", f"%{item_query}%"))
        return " AND ".join(conditions), values

    def daily_sales(self, day, sale_number="", item_query=""):
        with self.connect() as db:
            where, values = self._sales_where("substr(s.created_at,1,10)=?", day, sale_number, item_query)
            sales = db.execute(f"SELECT s.*,(SELECT GROUP_CONCAT(si.description || ' (x' || si.quantity || ')', ', ') FROM sale_items si WHERE si.sale_id=s.id) AS item_list FROM sales s WHERE {where} ORDER BY s.created_at DESC", values).fetchall()
            sums = db.execute(f"SELECT s.payment_method,COUNT(*) AS amount,SUM(s.total) AS total FROM sales s WHERE {where} GROUP BY s.payment_method", values).fetchall()
            summary = db.execute(f"SELECT COUNT(*) AS sale_count,COALESCE(SUM(s.total),0) AS total,COALESCE(SUM(s.subtotal),0) AS subtotal,COALESCE(SUM(s.discount_value),0) AS discount FROM sales s WHERE {where}", values).fetchone()
            items = db.execute(f"SELECT COALESCE(SUM(si.quantity),0) AS quantity,COALESCE(SUM(si.quantity*si.unit_cost),0) AS invested,COALESCE(SUM(CASE WHEN si.unit_cost IS NULL THEN si.quantity ELSE 0 END),0) AS unknown_cost_quantity FROM sale_items si JOIN sales s ON s.id=si.sale_id WHERE {where}", values).fetchone()
            return sales, sums, summary, items

    def monthly_sales(self, month, sale_number="", item_query=""):
        with self.connect() as db:
            where, values = self._sales_where("substr(s.created_at,1,7)=?", month, sale_number, item_query)
            summary = db.execute(f"SELECT COUNT(*) AS count,COALESCE(SUM(s.subtotal),0) AS subtotal,COALESCE(SUM(s.discount_value),0) AS discount,COALESCE(SUM(s.total),0) AS total FROM sales s WHERE {where}", values).fetchone()
            item_summary = db.execute(f"SELECT COALESCE(SUM(si.quantity),0) AS quantity,COALESCE(SUM(si.quantity*si.unit_cost),0) AS invested,COALESCE(SUM(CASE WHEN si.unit_cost IS NULL THEN si.quantity ELSE 0 END),0) AS unknown_cost_quantity FROM sale_items si JOIN sales s ON s.id=si.sale_id WHERE {where}", values).fetchone()
            methods = db.execute(f"SELECT s.payment_method,COUNT(*) AS count,COALESCE(SUM(s.total),0) AS total FROM sales s WHERE {where} GROUP BY s.payment_method", values).fetchall()
            sales = db.execute(f"SELECT s.*,(SELECT GROUP_CONCAT(si.description || ' (x' || si.quantity || ')', ', ') FROM sale_items si WHERE si.sale_id=s.id) AS item_list FROM sales s WHERE {where} ORDER BY s.created_at DESC,s.id DESC", values).fetchall()
            return summary, item_summary, methods, sales

    def monthly_movements(self, month, kind="Todos", sale_number="", item_query=""):
        with self.connect() as db:
            conditions = ["substr(m.created_at,1,7)=?"]
            values = [month]
            if kind == "Entradas":
                conditions.append("m.kind IN ('Entrada','Entrada inicial')")
            elif kind == "Saídas":
                conditions.append("m.kind IN ('Saída manual','Venda')")
            if sale_number:
                conditions.append("m.sale_id=?")
                values.append(int(sale_number))
            if item_query:
                conditions.append("(p.barcode LIKE ? OR p.description LIKE ?)")
                values.extend((f"%{item_query}%", f"%{item_query}%"))
            where = " AND ".join(conditions)
            rows = db.execute(f"SELECT m.*,p.barcode,p.description,s.payment_method,s.installments,s.id AS sale_number,CASE WHEN m.sale_id IS NOT NULL THEN 'Venda #' || s.id || ' · ' || s.payment_method || ' · ' || s.installments || ' parcela(s)' ELSE m.note END AS reference FROM movements m JOIN products p ON p.id=m.product_id LEFT JOIN sales s ON s.id=m.sale_id WHERE {where} ORDER BY m.created_at DESC,m.id DESC", values).fetchall()
            incoming = [row for row in rows if row["kind"] in ("Entrada", "Entrada inicial")]
            outgoing = [row for row in rows if row["kind"] in ("Saída manual", "Venda")]
            totals = {
                "incoming": sum(row["quantity"] for row in incoming),
                "outgoing": sum(row["quantity"] for row in outgoing),
                "incoming_value": sum(row["quantity"] * row["unit_cost"] for row in incoming),
                "outgoing_value": sum(row["quantity"] * row["unit_cost"] for row in outgoing),
            }
            return totals, rows

    def movement_history(self):
        with self.connect() as db:
            return db.execute("""
                SELECT m.id,m.created_at,m.kind,p.barcode,p.description,m.quantity,
                       m.unit_cost,m.quantity*m.unit_cost AS movement_value,m.username,
                       CASE WHEN m.sale_id IS NOT NULL
                            THEN 'Venda #' || s.id || ' · ' || s.payment_method || ' · ' || s.installments || ' parcela(s)'
                            ELSE m.note END AS reference
                FROM movements m
                JOIN products p ON p.id=m.product_id
                LEFT JOIN sales s ON s.id=m.sale_id
                ORDER BY m.created_at DESC,m.id DESC
            """).fetchall()


