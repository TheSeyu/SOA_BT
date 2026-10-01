import datetime
import functools
import hashlib
import hmac
import sqlite3

import jwt
from flask import Flask, g, jsonify, request

app = Flask(__name__)
app.config["SECRET_KEY"] = "doi-khoa-bi-mat-nay-khi-trien-khai-that"
DB_PATH = "users.db"
TOKEN_EXPIRE_HOURS = 1


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


def init_db():
    """Tạo bảng User theo phụ lục và thêm tài khoản mẫu."""
    db = sqlite3.connect(DB_PATH)
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS User (
            IdUser   INTEGER PRIMARY KEY AUTOINCREMENT,
            UserName VARCHAR(255) NOT NULL UNIQUE,
            Password VARCHAR(255) NOT NULL,
            Token    VARCHAR(255)
        )
        """
    )
    # Mật khẩu đã mã hoá MD5 (giống như client gửi lên)
    md5_123456 = hashlib.md5(b"123456").hexdigest()
    db.execute(
        "INSERT OR IGNORE INTO User (UserName, Password) VALUES (?, ?)",
        ("admin", md5_123456),
    )
    db.commit()
    db.close()


# -------------------------------------------------------------------- JWT
def create_token(user_id, username):
    payload = {
        "sub": str(user_id),
        "username": username,
        "iat": datetime.datetime.now(datetime.timezone.utc),
        "exp": datetime.datetime.now(datetime.timezone.utc)
        + datetime.timedelta(hours=TOKEN_EXPIRE_HOURS),
    }
    return jwt.encode(payload, app.config["SECRET_KEY"], algorithm="HS256")


# ------------------------------------------------------------- Middleware
def token_required(f):
    """Middleware xác thực token: đọc header  Authorization: Bearer <token>."""

    @functools.wraps(f)
    def wrapper(*args, **kwargs):
        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            return jsonify(message="Thiếu token (Authorization: Bearer <token>)"), 401
        token = auth_header.split(" ", 1)[1].strip()

        try:
            payload = jwt.decode(token, app.config["SECRET_KEY"], algorithms=["HS256"])
        except jwt.ExpiredSignatureError:
            return jsonify(message="Token đã hết hạn"), 401
        except jwt.InvalidTokenError:
            return jsonify(message="Token không hợp lệ"), 401

        # Kiểm tra token khớp với token đã lưu trong DB
        user = get_db().execute(
            "SELECT * FROM User WHERE IdUser = ?", (payload["sub"],)
        ).fetchone()
        if user is None or user["Token"] != token:
            return jsonify(message="Token không còn hiệu lực"), 401

        g.current_user = user
        g.token_payload = payload
        return f(*args, **kwargs)

    return wrapper


# ----------------------------------------------------------------- Router
@app.route("/", methods=["POST"])
def login():
    """Đăng nhập: nhận userName, password (đã mã hoá MD5 tại client) -> sinh JWT."""
    data = request.get_json(silent=True) or request.form
    username = data.get("userName")
    password = data.get("password")
    if not username or not password:
        return jsonify(message="Thiếu userName hoặc password"), 400

    db = get_db()
    user = db.execute("SELECT * FROM User WHERE UserName = ?", (username,)).fetchone()
    if user is None or not hmac.compare_digest(user["Password"], password):
        return jsonify(message="Sai tài khoản hoặc mật khẩu"), 401

    token = create_token(user["IdUser"], user["UserName"])
    db.execute("UPDATE User SET Token = ? WHERE IdUser = ?", (token, user["IdUser"]))
    db.commit()
    return jsonify(message="Đăng nhập thành công", token=token)


@app.route("/auth", methods=["GET", "POST"])
@token_required
def auth():
    """API xác thực token."""
    return jsonify(
        message="Token hợp lệ",
        userId=g.current_user["IdUser"],
        userName=g.current_user["UserName"],
        expires=g.token_payload["exp"],
    )


@app.route("/hello", methods=["GET"])
@token_required
def hello():
    """API 'Hello World' của bài thực hành số 1, nay được bảo vệ bằng middleware."""
    return jsonify(message="Hello World")


if __name__ == "__main__":
    init_db()
    app.run(debug=True, port=5000)
