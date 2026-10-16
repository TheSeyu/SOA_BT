# Product Service (Bài thực hành số 3)

- Cổng: **5001** · CSDL riêng: `products.db` (SQLite, tự tạo khi chạy lần đầu)
- Xác thực: gọi sang Auth service (`main.py`, cổng **5000**) tại `/auth`
  → phải chạy Auth service trước. Đổi địa chỉ bằng biến môi trường `AUTH_URL`.

## Chạy (2 terminal, trong venv của dự án)
    # Terminal 1 - Auth service
    python main.py
    # Terminal 2 - Product service
    cd product_service
    python app.py

## API (header: Authorization: Bearer <token>)
| Method | URL            | Mô tả                                   |
|--------|----------------|-----------------------------------------|
| GET    | /products      | Danh sách sản phẩm                      |
| GET    | /products/<id> | Chi tiết 1 sản phẩm                     |
| POST   | /products      | Thêm sản phẩm                           |
| PUT    | /products/<id> | Cập nhật (gửi trường nào sửa trường đó) |
| DELETE | /products/<id> | Xoá sản phẩm                            |

Body POST/PUT (JSON): `name` (bắt buộc khi POST), `description`,
`price` (bắt buộc khi POST), `quantity` (mặc định 0).
