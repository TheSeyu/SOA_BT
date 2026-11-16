"""
BÀI THỰC HÀNH SỐ 4 - Dịch vụ quản lý đơn hàng (Order Management Service)

- Chạy độc lập trên cổng 5002, có cơ sở dữ liệu riêng (orders.db) -> đúng SOA.
- Không tự xác thực: gọi sang Auth service (bài 2, cổng 5000) tại /auth.
- Kiểm tra tồn kho bằng cách gọi sang Product service (bài 3, cổng 5001),
  chuyển tiếp chính token của người dùng. Không đọc chung DB của service khác.
- Chỉ dùng thư viện đã có trong venv (flask) + thư viện chuẩn.
"""
import datetime
import functools
import json
import os
import sqlite3
import urllib.error
import urllib.request

from flask import Flask, g, jsonify, request

app = Flask(__name__)
app.json.ensure_ascii = False  # trả tiếng Việt có dấu

PORT = 5002
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "orders.db")
AUTH_URL = os.environ.get("AUTH_URL", "http://localhost:5000/auth")
PRODUCT_URL = os.environ.get("PRODUCT_URL", "http://localhost:5001/products")
HTTP_TIMEOUT = 5  # giây

VALID_STATUS = ["pending", "confirmed", "shipping", "completed", "cancelled"]


# ---------------------------------------------------------------- Database
def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


@app.teardown_appcontext
def close_db(_exc):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def now_str():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def init_db():
    db = sqlite3.connect(DB_PATH)
    db.execute("PRAGMA foreign_keys = ON")
    db.executescript(
        """
        CREATE TABLE IF NOT EXISTS orders (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            customer_name VARCHAR(255) NOT NULL,
            status        VARCHAR(20)  NOT NULL DEFAULT 'pending',
            total         DECIMAL(12, 2) NOT NULL DEFAULT 0,
            created_at    TIMESTAMP NOT NULL,
            updated_at    TIMESTAMP NOT NULL
        );
        CREATE TABLE IF NOT EXISTS order_items (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            order_id   INTEGER NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
            product_id INTEGER NOT NULL,
            quantity   INT NOT NULL,
            unit_price DECIMAL(10, 2) NOT NULL
        );
        """
    )
    db.commit()
    db.close()


# ------------------------------------------------- Xác thực qua Auth service
def token_required(f):
    """Chuyển tiếp header Authorization sang Auth service (/auth)."""

    @functools.wraps(f)
    def wrapper(*args, **kwargs):
        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            return jsonify(message="Thiếu token (Authorization: Bearer <token>)"), 401

        req = urllib.request.Request(
            AUTH_URL, headers={"Authorization": auth_header}, method="GET"
        )
        try:
            with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as resp:
                g.auth_info = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            try:
                msg = json.loads(e.read().decode("utf-8")).get("message")
            except (ValueError, AttributeError):
                msg = None
            return jsonify(message=msg or "Xác thực thất bại"), 401
        except (urllib.error.URLError, TimeoutError, OSError):
            return jsonify(message=f"Không kết nối được Auth service ({AUTH_URL})"), 503
        except ValueError:
            return jsonify(message="Auth service trả về dữ liệu không hợp lệ"), 502

        g.auth_header = auth_header
        return f(*args, **kwargs)

    return wrapper


# ------------------------------------------------ Gọi sang Product service
class ProductError(Exception):
    def __init__(self, message, status):
        super().__init__(message)
        self.message = message
        self.status = status


def fetch_product(product_id):
    """GET /products/<id> trên Product service, kèm token của người dùng."""
    req = urllib.request.Request(
        f"{PRODUCT_URL}/{product_id}",
        headers={"Authorization": g.auth_header},
        method="GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        if e.code == 404:
            raise ProductError(f"Sản phẩm id={product_id} không tồn tại", 404)
        raise ProductError("Product service từ chối yêu cầu", 502)
    except (urllib.error.URLError, TimeoutError, OSError):
        raise ProductError(f"Không kết nối được Product service ({PRODUCT_URL})", 503)
    except ValueError:
        raise ProductError("Product service trả về dữ liệu không hợp lệ", 502)


# -------------------------------------------------------------- Tiện ích
def order_to_dict(db, order_row):
    d = dict(order_row)
    d["total"] = float(d["total"])
    items = db.execute(
        "SELECT product_id, quantity, unit_price FROM order_items WHERE order_id = ?",
        (d["id"],),
    ).fetchall()
    d["items"] = [dict(i) for i in items]
    return d


def get_order_or_none(order_id):
    return get_db().execute("SELECT * FROM orders WHERE id = ?", (order_id,)).fetchone()


def validate_items(data):
    """Trả về (danh sách (product_id, quantity) đã gộp, lỗi)."""
    items = data.get("items")
    if not isinstance(items, list) or not items:
        return None, "items là bắt buộc, là danh sách có ít nhất 1 phần tử"
    merged = {}
    for it in items:
        if not isinstance(it, dict):
            return None, "Mỗi phần tử của items phải là object {product_id, quantity}"
        pid, qty = it.get("product_id"), it.get("quantity")
        if isinstance(pid, bool) or not isinstance(pid, int) or pid <= 0:
            return None, "product_id phải là số nguyên dương"
        if isinstance(qty, bool) or not isinstance(qty, int) or qty <= 0:
            return None, "quantity phải là số nguyên > 0"
        merged[pid] = merged.get(pid, 0) + qty  # gộp nếu trùng sản phẩm
    return list(merged.items()), None


def validate_customer(data):
    name = data.get("customer_name")
    if not isinstance(name, str) or not name.strip() or len(name.strip()) > 255:
        return None, "customer_name là bắt buộc, kiểu chuỗi, dài 1-255 ký tự"
    return name.strip(), None


# ----------------------------------------------------------------- Router
@app.route("/orders", methods=["POST"])
@token_required
def create_order():
    """POST /orders: tạo đơn hàng (kiểm tra tồn kho qua Product service)."""
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify(message="Body phải là JSON object"), 400
    customer, err = validate_customer(data)
    if err:
        return jsonify(message=err), 400
    items, err = validate_items(data)
    if err:
        return jsonify(message=err), 400

    priced, total = [], 0.0
    for pid, qty in items:
        try:
            product = fetch_product(pid)
        except ProductError as e:
            return jsonify(message=e.message), e.status
        stock = product.get("quantity", 0)
        if stock < qty:
            return (
                jsonify(
                    message=f"Sản phẩm id={pid} không đủ hàng (còn {stock}, cần {qty})"
                ),
                400,
            )
        price = float(product.get("price", 0))
        priced.append((pid, qty, price))
        total += price * qty

    ts = now_str()
    db = get_db()
    cur = db.execute(
        "INSERT INTO orders (customer_name, status, total, created_at, updated_at)"
        " VALUES (?, 'pending', ?, ?, ?)",
        (customer, round(total, 2), ts, ts),
    )
    order_id = cur.lastrowid
    db.executemany(
        "INSERT INTO order_items (order_id, product_id, quantity, unit_price)"
        " VALUES (?, ?, ?, ?)",
        [(order_id, pid, qty, price) for pid, qty, price in priced],
    )
    db.commit()
    resp = jsonify(
        message="Tạo đơn hàng thành công",
        order=order_to_dict(db, get_order_or_none(order_id)),
    )
    resp.status_code = 201
    resp.headers["Location"] = f"/orders/{order_id}"
    return resp


@app.route("/orders", methods=["GET"])
@token_required
def list_orders():
    """GET /orders: danh sách đơn hàng (lọc theo ?status=...)."""
    db = get_db()
    status = request.args.get("status")
    if status:
        rows = db.execute(
            "SELECT * FROM orders WHERE status = ? ORDER BY id", (status,)
        ).fetchall()
    else:
        rows = db.execute("SELECT * FROM orders ORDER BY id").fetchall()
    return jsonify([order_to_dict(db, r) for r in rows])


@app.route("/orders/<int:order_id>", methods=["GET"])
@token_required
def get_order(order_id):
    """GET /orders/<id>: chi tiết một đơn hàng."""
    row = get_order_or_none(order_id)
    if row is None:
        return jsonify(message=f"Không tìm thấy đơn hàng id={order_id}"), 404
    return jsonify(order_to_dict(get_db(), row))


@app.route("/orders/<int:order_id>", methods=["PUT"])
@token_required
def update_order(order_id):
    """PUT /orders/<id>: cập nhật thông tin đơn (tên khách và/hoặc trạng thái)."""
    row = get_order_or_none(order_id)
    if row is None:
        return jsonify(message=f"Không tìm thấy đơn hàng id={order_id}"), 404
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify(message="Body phải là JSON object"), 400

    clean = {}
    if "customer_name" in data:
        name, err = validate_customer(data)
        if err:
            return jsonify(message=err), 400
        clean["customer_name"] = name
    if "status" in data:
        if data["status"] not in VALID_STATUS:
            return jsonify(message=f"status hợp lệ: {VALID_STATUS}"), 400
        clean["status"] = data["status"]
    if not clean:
        return jsonify(message="Không có trường nào để cập nhật (customer_name, status)"), 400

    clean["updated_at"] = now_str()
    set_clause = ", ".join(f"{col} = ?" for col in clean)  # cột do server lọc sẵn
    db = get_db()
    db.execute(f"UPDATE orders SET {set_clause} WHERE id = ?", (*clean.values(), order_id))
    db.commit()
    return jsonify(
        message="Cập nhật đơn hàng thành công",
        order=order_to_dict(db, get_order_or_none(order_id)),
    )


@app.route("/orders/<int:order_id>/status", methods=["PATCH"])
@token_required
def update_status(order_id):
    """PATCH /orders/<id>/status: cập nhật trạng thái đơn hàng."""
    row = get_order_or_none(order_id)
    if row is None:
        return jsonify(message=f"Không tìm thấy đơn hàng id={order_id}"), 404
    data = request.get_json(silent=True)
    status = data.get("status") if isinstance(data, dict) else None
    if status not in VALID_STATUS:
        return jsonify(message=f"status hợp lệ: {VALID_STATUS}"), 400

    db = get_db()
    db.execute(
        "UPDATE orders SET status = ?, updated_at = ? WHERE id = ?",
        (status, now_str(), order_id),
    )
    db.commit()
    return jsonify(
        message="Cập nhật trạng thái thành công",
        order=order_to_dict(db, get_order_or_none(order_id)),
    )


@app.route("/orders/<int:order_id>", methods=["DELETE"])
@token_required
def delete_order(order_id):
    """DELETE /orders/<id>: xoá đơn hàng (và các dòng chi tiết)."""
    db = get_db()
    cur = db.execute("DELETE FROM orders WHERE id = ?", (order_id,))
    db.commit()
    if cur.rowcount == 0:
        return jsonify(message=f"Không tìm thấy đơn hàng id={order_id}"), 404
    return jsonify(message=f"Đã xoá đơn hàng id={order_id}")


# ------------------------------------------------------ Xử lý lỗi dạng JSON
@app.errorhandler(404)
def not_found(_e):
    return jsonify(message="Đường dẫn không tồn tại"), 404


@app.errorhandler(405)
def method_not_allowed(_e):
    return jsonify(message="Phương thức không được hỗ trợ"), 405


if __name__ == "__main__":
    init_db()
    app.run(debug=True, port=PORT)
