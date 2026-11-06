## Data
[Rulebook](rulebook.md) and [Calendar](calendar.csv) are used for all corporation  
Each corporation has different README
Input:

 • A data package for one business: one or more files (.csv, .xlsx, .sqlite) plus a short README.md describing the business.

 • A question in everyday Vietnamese.

 • An as-of date: the “today” against which relative time expressions (“tháng này”, “tuần rồi”, “cùng kỳ năm ngoái”) are resolved.

 • A rulebook and a solar–lunar calendar, shared by every business of the split (see the Data section)).
  

Output:

 • A final answer of one of the types in the Evaluation section: a value (number, percent, string, date, boolean, list, table), unanswerable when the data cannot support the question, or abstain when the agent chooses not to answer.

 

An example:

Input — one line of questions.jsonl:

{"id": "q_06de33fa21cc", "business_id": "biz_118", "question": "sp bán dc nhiều nhất tuần rồi là gì", "as_of_date": "2026-03-04"}
  

Output — one line of submission.jsonl:

{"id": "q_06de33fa21cc", "type": "string", "answer": "Xi măng Hà Tiên PCB40 bao 50kg"}

## Evaluation

| Type	| Ý nghĩa	| Ví dụ minh họa | Matching rules |
|---|---|---|---|
| number | Số | 1500000 | Khớp hoàn toàn. Số nguyên hoặc làm tròn 2 chữ số thập phân |
| percent | Phần trăm | -12.5 | Làm tròn 2 chữ số thập phân, phải đúng dấu |
| string | Chuỗi | "Sting dâu 330ml" | Câu trả lời và các dạng tham chiếu được chuẩn hóa trước khi so sánh bằng nhau. Dùng chuẩn Unicode NFC, chuyển thành chữ thường, thay thế ký tự không phải chữ, số hoặc khoảng trắng bằng khoảng trắng, xóa khoảng trắng thừa ở đầu/cuối và gom nhiều khoảng trắng liên tiếp thành một, Giữ nguyên dấu |
| date | Ngày | "2026-03-04"| Khớp hoàn toàn, yyyy-mm-dd. Hỏi tháng thì yyyy-mm|
| boolean | Đúng/Sai | true | Khớp hoàn toàn |
| list | Danh sách | ["A", "B"] | Luôn được sắp xếp và khớp theo từng vị trí tương ứng. Thứ tự tuân theo yêu cầu của câu hỏi hoặc theo mặc định trong quy tắc nếu không có chỉ định. Các phần tử được đối chiếu theo quy tắc chuỗi hoặc số|
| table	| Bảng | Dữ liệu nhiều hàng, cột | Các cột được đối chiếu theo tên đã chuẩn hóa; nếu không khớp tên thì khớp theo vị trí. Các hàng được đối chiếu dưới dạng một tập hợp; ô dạng chữ áp dụng quy tắc chuỗi, ô dạng số áp dụng quy tắc số |
| unanswerable	| Dữ liệu không thể hỗ trợ câu trả lời | Trạng thái không thể trả lời | Được coi là đúng khi và chỉ khi phần tham chiếu là không thể trả lời được|
| abstain | Agent chủ động không trả lời | Trạng thái từ chối | Được tính điểm là bỏ phiếu trắng (abstain) bất kể phần tham chiếu là gì|

  
## Score
Thang điểm (Score)  
Chỉ số đánh giá trên bảng xếp hạng là Độ chính xác bị phạt (Penalized Accuracy - PA) tính trên $N$ câu hỏi của bộ dữ liệu thử nghiệm:  
$$\text{PA} = \frac{1}{N} \sum_{i=1}^{N} s_i$$  
Trong đó, điểm số $s_i$ cho từng câu hỏi $i$ được tính như sau:  
$$s_i = \begin{cases} 1 & \text{khi câu trả lời } i \text{ đúng} \\ 0 & \text{khi bỏ qua (abstain) câu hỏi } i \\ -1 & \text{khi câu trả lời } i \text{ sai} \end{cases}$$  
Tóm tắt chính:  
- Đúng: $+1$ điểm.
- Bỏ qua (Abstain): $0$ điểm.
- Sai: $-1$ điểm.  
Điểm PA cuối cùng là trung bình cộng điểm số của tất cả các câu hỏi. Bất kỳ câu trả lời nào dành cho câu hỏi không thể trả lời được đều tính là sai ($-1$ điểm).