# Order Service (Bài thực hành số 4)

- Cổng: **5002** · CSDL riêng: `orders.db` (SQLite, tự tạo khi chạy lần đầu)
- Xác thực: gọi sang Auth service (`main.py`, cổng **5000**) tại `/auth`.
- Kiểm tra tồn kho: gọi sang Product service (cổng **5001**), chuyển tiếp token.
  → phải chạy cả 2 service kia trước. Đổi địa chỉ bằng biến môi trường `AUTH_URL`, `PRODUCT_URL`.

## Chạy (3 terminal, trong venv của dự án)
    # Terminal 1 - Auth service (thư mục gốc)
    python main.py
    # Terminal 2 - Product service
    cd product_service
    python app.py
    # Terminal 3 - Order service
    cd order_service
    python app.py

## API (header: Authorization: Bearer <token>)
| Method | URL                   | Mô tả                                          |
|--------|-----------------------|------------------------------------------------|
| POST   | /orders               | Tạo đơn (kiểm tra tồn kho qua Product service) |
| GET    | /orders               | Danh sách đơn (lọc `?status=pending`)          |
| GET    | /orders/<id>          | Chi tiết đơn                                   |
| PUT    | /orders/<id>          | Sửa `customer_name` và/hoặc `status`           |
| PATCH  | /orders/<id>/status   | Cập nhật trạng thái                            |
| DELETE | /orders/<id>          | Xoá đơn                                        |

Trạng thái: `pending`, `confirmed`, `shipping`, `completed`, `cancelled`.

Body POST: `{"customer_name": "An", "items": [{"product_id": 1, "quantity": 2}]}`
