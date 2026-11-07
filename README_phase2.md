# DataMate — Phase 1 + Phase 2 Starter

Bộ project này tích hợp bộ đọc dữ liệu Phase 1 với Query Engine Phase 2. Phase 2 sử dụng DuckDB để thực thi SQL trên các bảng đã được Phase 1 nạp thành Pandas DataFrame.

## 1. Phase 2 dùng để làm gì?

Phase 1 giúp Python **đọc và hiểu cấu trúc** của package: file nào tồn tại, mỗi bảng có cột gì, kiểu dữ liệu nào, có bao nhiêu dòng và dữ liệu mẫu ra sao.

Phase 2 giúp Python **tính toán trên dữ liệu** bằng SQL một cách có thể kiểm tra được: lọc dòng, đếm, tổng hợp, join nhiều bảng, xếp hạng, tính tỷ lệ và so sánh theo thời gian.

Ví dụ, khi có câu hỏi “Tháng 2 doanh thu tăng bao nhiêu so với tháng 1?”, Query Engine cần:

1. Chọn đúng các bảng và cột đã được xác định từ Phase 1.
2. Kết hợp bảng nếu ngày và doanh thu nằm ở các bảng khác nhau.
3. Dùng SQL để tính tổng theo tháng.
4. Tính chênh lệch và phần trăm tăng trưởng.
5. Trả về kết quả dạng DataFrame để tầng phía trên xử lý.

**Chưa có LLM trong Phase 2.** SQL trong bài kiểm thử và ví dụ đều do lập trình viên viết. Mục đích là xác minh phép tính trước khi để một Planner/LLM lựa chọn công cụ ở phase sau.

## 2. Công cụ và lý do sử dụng

- **DuckDB**: cơ sở dữ liệu phân tích chạy ngay trong tiến trình Python, hỗ trợ SQL và truy vấn trực tiếp trên dữ liệu dạng cột. Không cần dựng database server riêng cho phiên bản local này.
- **Pandas**: Phase 1 đã dùng Pandas để đọc CSV/Excel/SQLite vào DataFrame; DuckDB có thể nạp các DataFrame này thành bảng.
- **OpenPyXL**: tiếp tục dùng bởi Phase 1 để đọc Excel `.xlsx`.
- **sqlite3**: tiếp tục dùng bởi Phase 1 để đọc các file SQLite; không cần cài package pip riêng.
- **SQL**: biểu diễn rõ ràng các phép lọc, nhóm, tổng hợp và join; ta có thể so sánh kết quả SQL với phép tính Pandas độc lập.

Tài liệu tham khảo:
- DuckDB Python API: https://duckdb.org/docs/stable/clients/python/overview
- DuckDB Python API Reference: https://duckdb.org/docs/stable/clients/python/reference/

## 3. Cấu trúc project

```text
datamate-project/
├── train data/                   # Đặt dataset thật của bạn ở đây
│   ├── data/
│   │   ├── biz_101/
│   │   ├── biz_102/
│   │   └── ...
│   ├── calendar.csv
│   ├── rulebook.md
│   ├── questions.jsonl
│   └── answers.jsonl
├── src/
│   ├── data/                      # Phase 1
│   │   ├── loader.py
│   │   ├── inspector.py
│   │   ├── cleaner.py
│   │   └── schema.py
│   └── executor/                  # Phase 2
│       ├── duckdb_engine.py
│       ├── query_builder.py
│       ├── aggregation.py
│       ├── joins.py
│       ├── ranking.py
│       └── statistics.py
├── tests/
│   └── run_validation.py          # 20 kiểm thử đối chiếu với Pandas
├── outputs/
├── run_phase1.py
├── run_phase2.py
└── requirements.txt
```

## 4. Cài đặt trên Windows / VS Code

Mở Terminal tại thư mục gốc của project:

```powershell
py -3.11 -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

DuckDB Python hiện hành yêu cầu Python 3.11 trở lên. Nếu máy đang dùng Python 3.10, hãy tạo môi trường bằng Python 3.11+ để tránh xung đột phiên bản.

Kiểm tra cài đặt:

```powershell
python -c "import duckdb, pandas; print('DuckDB:', duckdb.__version__); print('Pandas:', pandas.__version__)"
```

## 5. Chạy bộ kiểm thử bắt buộc trước

Không cần dataset thật để chạy kiểm thử. Script tự tạo một bộ dữ liệu mẫu nhỏ và so sánh từng kết quả SQL với phép tính Pandas độc lập.

```powershell
python tests/run_validation.py
```

Bộ kiểm thử gồm 20 nhóm kiểm tra:

1. Đếm khách hàng.
2. Đếm đơn hàng.
3. Đếm khách hàng duy nhất đã mua.
4. Tổng doanh thu.
5. Trung bình giá trị dòng hàng.
6. Giá trị dòng hàng nhỏ nhất.
7. Giá trị dòng hàng lớn nhất.
8. Tổng hợp doanh thu theo sản phẩm.
9. LEFT JOIN để giữ khách hàng không có đơn.
10. JOIN ba bảng để tính doanh thu theo khu vực.
11. Top-3 sản phẩm theo doanh thu.
12. Bottom-2 sản phẩm theo doanh thu.
13. Top-3 dòng hàng có giá trị cao nhất.
14. Doanh thu theo tháng và giá trị kỳ trước.
15. Số đơn hàng theo tháng.
16. Tỷ trọng doanh thu theo sản phẩm.
17. Lọc khoảng ngày và tính tổng.
18. Lọc theo điều kiện số.
19. Chênh lệch và phần trăm tăng trưởng.
20. JOIN sản phẩm và dòng hàng để tổng hợp doanh thu theo danh mục.

Kết quả mong đợi sau khi cài dependency: `Passed: 20/20`, `Failed: 0`. Nếu có test fail, không chuyển qua bước tiếp theo trước khi xem nguyên nhân.

## 6. Nạp package DataMate thật vào DuckDB

Đặt thư mục `train data` cùng cấp với `run_phase2.py`, sau đó chạy:

```powershell
python run_phase2.py
```

Nếu folder dataset nằm ở chỗ khác:

```powershell
python run_phase2.py --package-dir "D:\duong dan\train data"
```

Mặc định database ở RAM (`:memory:`). Muốn lưu database ra file để mở lại ở lần chạy sau:

```powershell
python run_phase2.py --database "outputs/datamate.duckdb"
```

Script sẽ tạo:

```text
outputs/
├── phase2_table_inventory.csv
└── phase2_run_summary.json
```

`phase2_table_inventory.csv` ghi danh sách bảng, schema DuckDB, file nguồn, số dòng và danh sách cột. Script cũng in preview một vài bảng ở Terminal.

## 7. Cách dùng từng module

### 7.1. DuckDB Engine

Engine nhận `DataPackage` do Phase 1 tạo và đăng ký các DataFrame thành bảng trong DuckDB. Mỗi doanh nghiệp có schema riêng để tránh trùng tên bảng:

- `biz_101.orders`
- `biz_102.orders`
- `global_data.calendar` (tên gốc trong Phase 1 là `__global__.calendar`)

```python
from src.data.loader import DataPackageLoader
from src.executor import DuckDBEngine

package = DataPackageLoader("train data").load()

with DuckDBEngine() as engine:
    engine.register_package(package)
    result = engine.execute_query(
        'SELECT COUNT(*) AS n FROM "biz_101"."orders"'
    )
    if result["success"]:
        print(result["result"])
    else:
        print(result["error"])
```

`execute_query` trả về dictionary có `success`, `result`, `error`, `row_count`, `columns`. `fetch_df` trả trực tiếp DataFrame và raise exception nếu query lỗi.

### 7.2. Query Builder

Dùng khi cần SELECT, WHERE, ORDER BY, LIMIT phổ biến mà không phải tự ghép SQL.

```python
from src.executor import DuckDBEngine, QueryBuilder, FilterCondition

with DuckDBEngine() as engine:
    engine.register_package(package)
    builder = QueryBuilder(engine)
    result = builder.select(
        "biz_101.orders",
        columns=["order_id", "total_amount"],
        filters=[FilterCondition("total_amount", ">", 100000)],
        order_by=[("total_amount", "DESC")],
        limit=10,
    )
```

Giá trị trong điều kiện được bind bằng parameter (`?`), không nối trực tiếp vào chuỗi SQL. Tên bảng và tên cột được kiểm tra với catalog đã đăng ký.

### 7.3. Aggregation

```python
from src.executor import aggregate

result = aggregate(
    engine,
    "biz_101.orders",
    {
        "total_amount": ("SUM", "amount"),
        "average_amount": ("AVG", "amount"),
        "order_count": ("COUNT", "*"),
    },
    group_by=["customer_id"],
    order_by=[("total_amount", "DESC")],
)
```

Hỗ trợ `SUM`, `AVG`/`AVERAGE`, `COUNT`, `MIN`, `MAX`, `COUNT_DISTINCT`.

### 7.4. Join nhiều bảng

```python
from src.executor import JoinHandler, JoinSpec, Selection, JoinMetric

joins = JoinHandler(engine)
result = joins.fetch_df(
    "biz_101.orders",
    base_alias="o",
    joins=[
        JoinSpec("biz_101.customers", "c", "o", "customer_id", "customer_id"),
        JoinSpec("biz_101.order_items", "i", "o", "order_id", "order_id"),
    ],
    group_by=[Selection("c", "region")],
    metrics=[JoinMetric("revenue", "SUM", Selection("i", "line_total"))],
    order_by=[("region", "ASC")],
)
```

`JoinSpec` mô tả rõ bảng mới, alias và hai cột dùng để nối. Các kiểu join hỗ trợ: `INNER`, `LEFT`, `RIGHT`, `FULL OUTER`.

### 7.5. Ranking

```python
from src.executor import rank_groups, rank_rows

# Top 5 sản phẩm theo tổng doanh thu
result = rank_groups(
    engine,
    "biz_101.order_items",
    group_by=["product_id"],
    metric_column="line_total",
    aggregate_function="SUM",
    k=5,
    direction="top",
)

# 10 dòng dữ liệu có giá trị lớn nhất
result = rank_rows(
    engine,
    "biz_101.order_items",
    metric_column="line_total",
    k=10,
    direction="top",
)
```

### 7.6. Statistics

```python
from src.executor import calculate_change, period_over_period, percentage_of_total

monthly = period_over_period(
    engine,
    "biz_101.orders",
    date_column="order_date",
    value_column="total_amount",
    period="month",
    aggregation="SUM",
)

change = calculate_change(current=150000, previous=120000)
# absolute_change = 30000; ratio = 1.25; growth_pct = 25.0

shares = percentage_of_total(
    engine,
    "biz_101.order_items",
    group_by="product_id",
    value_column="line_total",
)
```

`period_over_period` so sánh với kỳ quan sát ngay trước đó; nếu thiếu tháng, kỳ trước có dữ liệu không nhất thiết là tháng lịch liền kề. `calculate_change` trả `growth_pct=None` nếu giá trị kỳ trước bằng 0, vì tỷ lệ tăng trưởng khi đó không xác định. Không tự động đổi mẫu số 0 thành 1.

## 8. Cách đọc tên bảng

Mỗi `LoadedTable` của Phase 1 có `qualified_name` dạng `business_id.table_name`. Engine chuyển tên này thành schema và table trong DuckDB.

| Tên logic từ Phase 1 | Tên SQL trong DuckDB |
|---|---|
| `biz_101.orders` | `"biz_101"."orders"` |
| `biz_102.orders` | `"biz_102"."orders"` |
| `__global__.calendar` | `"global_data"."calendar"` |

Nếu có hai file trong cùng doanh nghiệp cùng có tên bảng sau khi bỏ đuôi file (ví dụ `north/orders.csv` và `south/orders.csv`), engine sẽ báo duplicate thay vì âm thầm ghi đè. Khi đó cần đặt tên bảng duy nhất trong Phase 1 hoặc xử lý collision trước khi đăng ký.

## 9. Một số nguyên tắc an toàn và độ tin cậy

- Chỉ chạy SQL do bạn viết trong Phase 2; chưa cho LLM sinh SQL.
- `execute_query` giới hạn ở truy vấn đọc dữ liệu (`SELECT`, `WITH`, `EXPLAIN`, `VALUES`, `DESCRIBE`, `SHOW`). Đây là guardrail cho project, không phải sandbox chống mọi SQL độc hại.
- Dùng `?` và `parameters` cho giá trị lọc. Không f-string giá trị người dùng vào SQL.
- Tên bảng/cột phải được resolve từ catalog đã đăng ký rồi mới được quote.
- Không join chéo doanh nghiệp một cách mặc định. Hãy chỉ rõ đầy đủ tên bảng và quan hệ hợp lệ.
- Quan hệ từ tên cột chưa chắc là foreign key thật; cần kiểm tra dữ liệu và cardinality trước khi dùng.
- `LEFT JOIN` và `INNER JOIN` tạo kết quả khác nhau: kiểm thử có khách hàng không có đơn để bảo đảm bạn hiểu khác biệt.
- Dùng `DECIMAL`/kiểu số phù hợp khi dữ liệu tiền tệ cần độ chính xác cao; ví dụ mẫu dùng số nguyên VND để tránh sai số float.
- Kiểm tra `NULL`, phép chia cho 0, dữ liệu ngày không hợp lệ và trùng khóa trước khi tin kết quả.

## 10. Những phần chưa làm trong Phase 2

- Tự động suy luận quan hệ giữa mọi bảng CSV/Excel.
- Tự động chọn bảng/cột dựa trên câu hỏi tiếng Việt.
- LLM tạo SQL hoặc tự sửa SQL.
- Multi-agent, RAG, embedding hay fine-tuning.
- Phân quyền và sandbox cho SQL không đáng tin cậy.

Các phần đó chỉ nên thêm sau khi bộ query kiểm thử chạy ổn định và phép tính SQL đã được đối chiếu độc lập.
