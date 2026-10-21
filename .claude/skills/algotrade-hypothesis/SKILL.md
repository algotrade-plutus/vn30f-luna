---
name: algotrade-hypothesis
description: >-
  Gác cổng cho mỗi ý tưởng chiến lược theo triết lý ALGOTRADE (Knowledge Hub, quy trình 9 bước). Dùng TRƯỚC khi
  thử một giả thuyết mới (chế độ Thiết kế: viết PROTOCOL.md có nguồn alpha, cơ chế, luật đo được, dự đoán bác bỏ,
  ngân sách lần thử, khoảng dữ liệu) và KHI nhánh nghiên cứu đã có kết quả (chế độ Phán quyết: giữ / sửa luật / bỏ).
---

# Algotrade Hypothesis: gác cổng giả thuyết

Triết lý và tóm tắt nguồn: [philosophy.md](philosophy.md). Toàn văn 24 bài ALGOTRADE Knowledge Hub nằm local ở
`docs/algotrade_knowledge_hub/` (thư mục `docs/` bị gitignore); tải lại bằng
`python3 .claude/skills/algotrade-hypothesis/scripts/algotrade_to_md.py`.

Skill này phủ bước 1 đến 6 của quy trình 9 bước: hình thành giả thuyết, dữ liệu, luật, backtest in-sample, tối ưu,
backtest out-of-sample. Paper trading, thử tài khoản nhỏ và chạy thật (bước 7 đến 9) theo quy định vận hành của dự án.
Engine backtest, phí, khoảng dữ liệu và ngưỡng hiệu suất lấy từ `AGENTS.md` / `CLAUDE.md` của dự án; skill không đặt
lại chúng.

## Chế độ 1: Thiết kế (trước khi chạy bất kỳ backtest nào của giả thuyết)

Tạo `PROTOCOL.md` cho nhánh nghiên cứu theo mẫu dưới. Thiếu mục nào thì chưa chạy. Hình hay event study khám phá được
làm trước, nhưng phải tính vào số lần thử.

```markdown
# Protocol: <tên giả thuyết> (<ngày>)

## 1. Giả thuyết
Một câu: <điều kiện quan sát được> thì <giá làm gì> trong <khoảng thời gian>.

## 2. Nguồn alpha và cơ chế
- Nguồn (1 đến 2 trong 8): common sense / mispricing / thiên kiến hành vi / tốc độ / mô hình thống kê /
  hiểu biết riêng của thị trường / lợi thế riêng của công ty / dữ liệu.
- Ai trả tiền cho mình, và vì sao họ hành động như vậy.
- Vì sao lợi thế còn tồn tại; khi nào nó sẽ mất.

## 3. Luật đo được
- Biến độc lập: chỉ báo nào, tính thế nào, chỉ dùng dữ liệu đã biết tại thời điểm quyết định.
- Biến phụ thuộc: lợi suất nào, horizon bao lâu.
- Luật vào / ra / đứng ngoài; tham số và lý do chọn giá trị mặc định.
- Ràng buộc thật của thị trường: phí, giờ giao dịch, ATC, đáo hạn, quy định.

## 4. Dự đoán bác bỏ (viết trước, định lượng)
- B1: nếu <...> thì giả thuyết sai.
- B2: ...

## 5. Tiêu chí chấp nhận
Ngưỡng hiệu suất của dự án sau phí, ổn định theo năm hoặc theo nhóm, tham số nằm trong vùng ổn định.

## 6. Ngân sách lần thử
Lưới khoá trước (liệt kê); tổng lần thử tích luỹ sau lưới này; DSR tính trên tổng đó.

## 7. Dữ liệu
Khoảng train / validation / out-of-sample; số lần đã nhìn out-of-sample; khoảng khoá cho kiểm tra cuối.
```

Kiểm tra trước khi cho chạy:

- Cơ chế có nói được ai trả tiền, hay chỉ nói "chỉ báo này hay thắng"?
- Dự đoán bác bỏ có thể xảy ra thật, hay là câu luôn đúng?
- Luật đã ít tham số nhất có thể chưa? Mỗi bộ lọc thêm vào là một lần thử.
- Mọi biến độc lập có causal không? Có đụng khoảng dữ liệu đang khoá không?

## Chế độ 2: Phán quyết (khi nhánh có kết quả)

Đọc report và output, trả lời từng câu, rồi ghi một dòng `Phán quyết:` vào report.

| Câu hỏi | Bỏ nếu |
|---|---|
| Dự đoán bác bỏ có xảy ra không? | Có |
| Bao nhiêu phiên bản trong lưới có lãi sau phí? | Chỉ lẻ tẻ vài điểm |
| Tham số tốt có lân cận cũng tốt không? | Đỉnh nhọn, lân cận sập |
| Có dương ở đa số năm, nhóm hoặc trạng thái thị trường không? | Lãi dồn vào một năm hay một sự kiện |
| Sau phí có đạt ngưỡng của dự án không? | Thiếu xa, không có đường sửa trong phạm vi giả thuyết |
| DSR với tổng lần thử tích luỹ là bao nhiêu? | Thấp và hết ngân sách thử |
| Đã nhìn out-of-sample mấy lần? | Hơn 1 lần mà vẫn gọi là out-of-sample thì không được tính |

Kết luận là một trong ba:

- GIỮ: sang bước kế (out-of-sample mở một lần, rồi paper trading theo quy trình của dự án).
- SỬA LUẬT: giả thuyết còn đứng nhưng bộ luật chưa đúng. Luật mới tính là lần thử mới; cập nhật ngân sách.
- BỎ: ghi lý do và bằng chứng vào report để không mở lại nhánh. Nếu thứ còn lại chỉ có ích làm feature hay bộ lọc,
  ghi rõ "dùng làm feature, không làm tín hiệu chính".

Ý tưởng mới nảy ra trong lúc phán quyết thì ghi vào mục "Ý tưởng ghi lại" của report, không chen vào nhánh đang chấm.

## Deflated Sharpe (DSR)

Xác suất Sharpe thật lớn hơn Sharpe tốt nhất mà N lần thử ngẫu nhiên đạt được (Bailey và López de Prado). Dùng Sharpe
theo kỳ (không annualize), T là số quan sát, γ ≈ 0,5772:

```text
SR0 = sqrt(Var(SR các lần thử)) * ((1 − γ) * Φ⁻¹(1 − 1/N) + γ * Φ⁻¹(1 − 1/(N·e)))
z   = (SR − SR0) * sqrt(T − 1) / sqrt(1 − skew·SR + (kurt − 1)/4 · SR²)
DSR = Φ(z)
```

DSR ≥ 0,95 mới coi là phân biệt được với may mắn. N là toàn bộ lần thử của dự án cho cùng mục tiêu, kể cả các lần đã bỏ.
