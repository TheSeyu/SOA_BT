"""
BÀI THỰC HÀNH SỐ 3 - Dịch vụ quản lý sản phẩm (Product Management Service)

- Chạy độc lập trên cổng 5001, có cơ sở dữ liệu riêng (products.db).
- Không tự xác thực: mọi API đều gọi sang Auth service (bài 2, cổng 5000)
  tại endpoint /auth để kiểm tra token.
- Chỉ dùng thư viện đã có trong venv (flask) + thư viện chuẩn, không cần cài thêm.
"""
import datetime
import functools
import json
import os
import sqlite3
import urllib.error
import urllib.request
from decimal import Decimal, InvalidOperation

from flask import Flask, g, jsonify, request

app = Flask(__name__)
app.json.ensure_ascii = False  # trả tiếng Việt có dấu, không bị \uXXXX

PORT = 5001
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "products.db")
AUTH_URL = os.environ.get("AUTH_URL", "http://localhost:5000/auth")
AUTH_TIMEOUT = 5  # giây

MAX_PRICE = Decimal("100000000")  # DECIMAL(10, 2) -> tối đa 99.999.999,99


# ---------------------------------------------------------------- Database
def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
    return g.db


@app.teardown_appcontext
def close_db(_exc):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def now_str():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def init_db():
    """Tạo bảng products theo phụ lục và thêm vài sản phẩm mẫu nếu bảng trống."""
    db = sqlite3.connect(DB_PATH)
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS products (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            name        VARCHAR(255) NOT NULL,
            description TEXT,
            price       DECIMAL(10, 2) NOT NULL,
            quantity    INT NOT NULL DEFAULT 0,
            created_at  TIMESTAMP NOT NULL,
            updated_at  TIMESTAMP NOT NULL
        )
        """
    )
    if db.execute("SELECT COUNT(*) FROM products").fetchone()[0] == 0:
        ts = now_str()
        db.executemany(
            "INSERT INTO products (name, description, price, quantity, created_at, updated_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            [
                ("Bàn phím cơ", "Bàn phím cơ switch đỏ, layout TKL", 850000.00, 25, ts, ts),
                ("Chuột không dây", "Chuột không dây 2.4GHz, pin AA", 220000.00, 60, ts, ts),
                ("Màn hình 24 inch", "Full HD, tấm nền IPS, 75Hz", 3290000.00, 12, ts, ts),
            ],
        )
    db.commit()
    db.close()


# ------------------------------------------------- Xác thực qua Auth service
def token_required(f):
    """Middleware: chuyển tiếp header Authorization sang Auth service (/auth)."""

    @functools.wraps(f)
    def wrapper(*args, **kwargs):
        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            return jsonify(message="Thiếu token (Authorization: Bearer <token>)"), 401

        req = urllib.request.Request(
            AUTH_URL, headers={"Authorization": auth_header}, method="GET"
        )
        try:
            with urllib.request.urlopen(req, timeout=AUTH_TIMEOUT) as resp:
                g.auth_info = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:  # Auth service từ chối token
            try:
                msg = json.loads(e.read().decode("utf-8")).get("message")
            except (ValueError, AttributeError):
                msg = None
            return jsonify(message=msg or "Xác thực thất bại"), 401
        except (urllib.error.URLError, TimeoutError, OSError):
            return (
                jsonify(message=f"Không kết nối được Auth service ({AUTH_URL})"),
                503,
            )
        except ValueError:
            return jsonify(message="Auth service trả về dữ liệu không hợp lệ"), 502

        return f(*args, **kwargs)

    return wrapper


# -------------------------------------------------------------- Tiện ích
def row_to_dict(row):
    d = dict(row)
    d["price"] = float(d["price"])
    return d


def parse_price(value):
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise ValueError
    try:
        d = Decimal(str(value))
    except InvalidOperation:
        raise ValueError
    if not d.is_finite() or d < 0 or d >= MAX_PRICE:
        raise ValueError
    return float(d.quantize(Decimal("0.01")))


def validate_product(data, require_all):
    """Trả về (dữ liệu sạch, thông báo lỗi). require_all=True dùng cho POST."""
    if not isinstance(data, dict):
        return None, "Body phải là JSON object"

    clean = {}

    if "name" in data or require_all:
        name = data.get("name")
        if not isinstance(name, str) or not name.strip() or len(name.strip()) > 255:
            return None, "name là bắt buộc, kiểu chuỗi, dài 1-255 ký tự"
        clean["name"] = name.strip()

    if "description" in data:
        desc = data["description"]
        if desc is not None and not isinstance(desc, str):
            return None, "description phải là chuỗi hoặc null"
        clean["description"] = desc

    if "price" in data or require_all:
        try:
            clean["price"] = parse_price(data.get("price"))
        except ValueError:
            return None, "price là bắt buộc, là số từ 0 đến 99999999.99"

    if "quantity" in data:
        qty = data["quantity"]
        if isinstance(qty, bool) or not isinstance(qty, int) or qty < 0:
            return None, "quantity phải là số nguyên >= 0"
        clean["quantity"] = qty
    elif require_all:
        clean["quantity"] = 0

    if not clean:
        return None, "Không có trường nào để cập nhật (name, description, price, quantity)"
    return clean, None


def get_product_or_none(product_id):
    return get_db().execute(
        "SELECT * FROM products WHERE id = ?", (product_id,)
    ).fetchone()


# ----------------------------------------------------------------- Router
@app.route("/products", methods=["GET"])
@token_required
def list_products():
    """GET /products: lấy danh sách tất cả sản phẩm."""
    rows = get_db().execute("SELECT * FROM products ORDER BY id").fetchall()
    return jsonify([row_to_dict(r) for r in rows])


@app.route("/products/<int:product_id>", methods=["GET"])
@token_required
def get_product(product_id):
    """GET /products/<id>: lấy chi tiết một sản phẩm."""
    row = get_product_or_none(product_id)
    if row is None:
        return jsonify(message=f"Không tìm thấy sản phẩm id={product_id}"), 404
    return jsonify(row_to_dict(row))


@app.route("/products", methods=["POST"])
@token_required
def create_product():
    """POST /products: thêm sản phẩm mới."""
    clean, error = validate_product(request.get_json(silent=True), require_all=True)
    if error:
        return jsonify(message=error), 400

    ts = now_str()
    db = get_db()
    cur = db.execute(
        "INSERT INTO products (name, description, price, quantity, created_at, updated_at)"
        " VALUES (?, ?, ?, ?, ?, ?)",
        (
            clean["name"],
            clean.get("description"),
            clean["price"],
            clean["quantity"],
            ts,
            ts,
        ),
    )
    db.commit()
    row = get_product_or_none(cur.lastrowid)
    resp = jsonify(message="Thêm sản phẩm thành công", product=row_to_dict(row))
    resp.status_code = 201
    resp.headers["Location"] = f"/products/{cur.lastrowid}"
    return resp


@app.route("/products/<int:product_id>", methods=["PUT"])
@token_required
def update_product(product_id):
    """PUT /products/<id>: cập nhật thông tin sản phẩm (gửi trường nào cập nhật trường đó)."""
    if get_product_or_none(product_id) is None:
        return jsonify(message=f"Không tìm thấy sản phẩm id={product_id}"), 404

    clean, error = validate_product(request.get_json(silent=True), require_all=False)
    if error:
        return jsonify(message=error), 400

    clean["updated_at"] = now_str()
    # Tên cột lấy từ khoá do server tạo ra (đã lọc ở validate_product) nên an toàn
    set_clause = ", ".join(f"{col} = ?" for col in clean)
    db = get_db()
    db.execute(
        f"UPDATE products SET {set_clause} WHERE id = ?",
        (*clean.values(), product_id),
    )
    db.commit()
    return jsonify(
        message="Cập nhật sản phẩm thành công",
        product=row_to_dict(get_product_or_none(product_id)),
    )


@app.route("/products/<int:product_id>", methods=["DELETE"])
@token_required
def delete_product(product_id):
    """DELETE /products/<id>: xoá sản phẩm."""
    db = get_db()
    cur = db.execute("DELETE FROM products WHERE id = ?", (product_id,))
    db.commit()
    if cur.rowcount == 0:
        return jsonify(message=f"Không tìm thấy sản phẩm id={product_id}"), 404
    return jsonify(message=f"Đã xoá sản phẩm id={product_id}")


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
