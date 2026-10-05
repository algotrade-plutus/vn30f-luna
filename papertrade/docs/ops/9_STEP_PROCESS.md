# Quy trình phát triển thuật toán giao dịch 9 bước

> Nguồn tham khảo: [AlgoTrade — Quy trình phát triển 9 bước](https://www.algotrade.vn/vi/knowledge/9-step-process/the-9-step)  
> Tài liệu này ghi lại nội dung từ tài liệu người dùng cung cấp và diễn giải nó
> thành định hướng cho repository. Đây chưa phải bản thiết kế kiến trúc code.

## Mục tiêu của quy trình

Mục tiêu tối thượng không phải là tạo ra kết quả backtest đẹp, mà là tăng độ tin
cậy rằng thuật toán có thể tạo lợi nhuận ổn định và bền vững trong tương lai.
Một ý tưởng từng hoạt động tốt trên dữ liệu quá khứ vẫn có thể thất bại khi đi
vào điều kiện thị trường chưa từng quan sát.

Quy trình 9 bước đưa hoạt động phát triển thuật toán về một chu trình khoa học:
hình thành giả thuyết, kiểm chứng bằng dữ liệu, thực thi nhất quán, đánh giá và
cải tiến qua nhiều vòng lặp. Quy trình không bảo đảm dự đoán đúng tương lai; nó
chỉ giúp bằng chứng về hiệu quả được tạo ra một cách khách quan và có thể kiểm
tra lại.

## Ba nguyên tắc nền tảng

### 1. Minh bạch

Toàn bộ thông tin liên quan đến quá trình đầu tư phải được ghi lại đầy đủ, rõ
ràng và chính xác, bao gồm:

- dữ liệu đầu vào và phiên bản dữ liệu;
- giả thuyết và bộ quy tắc ra quyết định;
- tham số và lịch sử thay đổi tham số;
- giao dịch, chi phí, kết quả và nguyên nhân ra quyết định;
- điều kiện chấp nhận hoặc loại bỏ một phiên bản thuật toán.

Mục đích là để một kết quả có thể được truy vấn, tái lập, kiểm chứng và phân
tích sau này.

### 2. Khả nguỵ

Mỗi giả thuyết và thuật toán phải có tiêu chí khách quan để chứng minh rằng nó
không hiệu quả. Một giả thuyết không thể bị bác bỏ bằng dữ liệu thì không phải
là giả thuyết có thể kiểm nghiệm.

### 3. Nhất quán

Quy trình đầu tư phải được áp dụng nhất quán qua đủ số vòng lặp và đủ số giao
dịch để kết quả thống kê có ý nghĩa. Không thay đổi quy tắc tuỳ tiện sau khi đã
nhìn thấy kết quả của một tập dữ liệu được dùng để kiểm định.

## Sơ đồ quyết định

```text
0. Observation: ghi nhận hiện tượng cần giải thích
          ↓
1. Hình thành giả thuyết
          ↓
2. Chuẩn bị dữ liệu
          ↓
3. Hình thành bộ quy tắc đầu tư
          ↓
4. Kiểm thử quá khứ trong mẫu ── không đạt ──→ quay lại Bước 1
          ↓ đạt
5. Tối ưu hoá (quét lưới bình nguyên tham số)
          ↓
6. Kiểm thử quá khứ ngoài mẫu ── không đạt ─→ quay lại Bước 1
          ↓ đạt
6.5. Kiểm định thực thi sàn (Plutus) ─ không đạt ─→ quay lại Bước 3/5
          ↓ đạt
7. Giao dịch trên giấy (Paper Trading) ── không đạt ─→ quay lại Bước 1
          ↓ đạt
8. Kiểm thử trên tài khoản nhỏ ─ không đạt ─→ quay lại Bước 1
          ↓ đạt
9. Giao dịch thực
```

Bước 1–6 dùng dữ liệu quá khứ. Bước 6.5 mô phỏng khớp lệnh thực tế và ký quỹ sàn (Plutus).
Bước 7 trở đi dùng dữ liệu phát sinh theo thời gian thực (Paper Trading).

## Nội dung từng bước

### Bước 0 — Observation (Quan sát khởi nguồn)

Ghi ngắn gọn hiện tượng thị trường khiến ta muốn đặt giả thuyết: mẫu hình nào
được chú ý, trong bối cảnh nào và vì sao đáng kiểm tra. Observation chỉ là điểm
khởi đầu để đặt câu hỏi; nó chưa phải bằng chứng về quan hệ nhân quả hay hiệu
quả giao dịch.

Đầu ra cần có:

- một mô tả ngắn về hiện tượng quan sát được;
- phạm vi thị trường và thời gian liên quan;
- câu hỏi dẫn tới giả thuyết ở Bước 1.

### Bước 1 — Hình thành giả thuyết thuật toán

Giả thuyết thuật toán là một giả định có thể kiểm chứng bằng dữ liệu, mô tả một
mối quan hệ định lượng giữa các yếu tố thị trường mà nhà đầu tư tin rằng có thể
khai thác để tạo lợi nhuận.

Giả thuyết có thể bắt nguồn từ dữ liệu, lý thuyết, quan sát thị trường hoặc kinh
nghiệm giao dịch. Chất lượng và độ chặt chẽ của giả thuyết quyết định chất lượng
của toàn bộ các bước sau.

Đầu ra cần có:

- phát biểu giả thuyết rõ ràng;
- cơ chế kinh tế hoặc hành vi được kỳ vọng;
- biến quan sát và quan hệ định lượng;
- điều kiện có thể bác bỏ giả thuyết;
- phạm vi thị trường và thời gian áp dụng dự kiến.

### Bước 2 — Chuẩn bị dữ liệu

Chuẩn bị dữ liệu gồm thu thập, tổ chức, làm sạch và thẩm định có hệ thống để bảo
đảm dữ liệu đầu vào chính xác, đầy đủ và nhất quán. Dữ liệu có thể là dữ liệu
thị trường, báo cáo tài chính hoặc nguồn phi truyền thống.

Làm sạch dữ liệu phải xử lý tối thiểu:

- dữ liệu khuyết;
- bản ghi trùng lặp;
- điểm bất thường;
- sai timezone hoặc session;
- điều chỉnh mã hợp đồng và corporate action nếu có;
- tính toàn vẹn thứ tự thời gian;
- nguy cơ survivorship, look-ahead và future leakage.

Đầu ra cần có một dataset chuẩn, có nguồn gốc và có thể tái tạo. Hiệu suất của
thuật toán phụ thuộc trực tiếp vào chất lượng dataset này.

### Bước 3 — Hình thành bộ quy tắc đầu tư

Bộ quy tắc đầu tư là thuật toán giao dịch được xây dựng từ giả thuyết, mô tả
bằng các điều kiện, công thức và chỉ dẫn đủ rõ để con người khác hoặc máy tính
có thể thực thi nhất quán.

Bộ quy tắc gồm ba lớp:

1. **Thu thập thông tin:** xác định dữ liệu và thông tin được phép dùng.
2. **Ra quyết định:** xác định điều kiện kích hoạt hành động giao dịch.
3. **Thực thi:** xác định đặt, huỷ, sửa lệnh; chiều giao dịch; quy mô; loại lệnh
   và các ràng buộc liên quan.

Quy tắc phải đủ chi tiết để thi hành chính xác nhưng đủ tổng quát để thích ứng
với nhiều trạng thái thị trường. Có thể bỏ qua các bước kiểm định trung gian và
đi thẳng tới giao dịch thực, nhưng đó là lựa chọn rủi ro cao và không thuộc quy
trình chuẩn của dự án.

### Bước 4 — Kiểm thử dữ liệu quá khứ trong mẫu

Thuật toán ban đầu được mô phỏng trên dữ liệu quá khứ trong mẫu nhằm đánh giá
tiềm năng sinh lợi và độ ổn định trong nhiều điều kiện thị trường.

Đánh giá cần bao gồm ít nhất:

- lợi nhuận và phân phối PnL;
- Sharpe;
- maximum drawdown;
- số giao dịch và thời gian nắm giữ;
- turnover;
- phí, thuế, trượt giá và các chi phí khác;
- độ nhạy với thời điểm khớp lệnh và chất lượng dữ liệu.

Tài liệu nguồn gợi ý tối thiểu khoảng 30 giao dịch để các chỉ số bắt đầu có ý
nghĩa thống kê. Đây là ngưỡng tham khảo, không phải bằng chứng đầy đủ về độ tin
cậy.

Nếu không đạt tiêu chí định trước, phải quay lại Bước 1–3 thay vì sửa tuỳ tiện
trên chính kết quả vừa quan sát. Nếu đạt, chuyển sang tối ưu hoá.

### Bước 5 — Tối ưu hoá

Tối ưu hoá điều chỉnh tham số trên dữ liệu trong mẫu để tìm vùng tham số đáp
ứng mục tiêu hiệu suất và các ràng buộc đã định trước.

Mục tiêu không phải là tìm một điểm tham số tạo kết quả quá khứ cao nhất. Mục
tiêu là tìm một vùng tham số ổn định, có khả năng duy trì hiệu suất trong nhiều
điều kiện thị trường. Phải đặc biệt cảnh giác với overfit.

Sau bước này cần đóng băng:

- phiên bản thuật toán;
- bộ tham số được chọn;
- tiêu chí chọn tham số;
- kết quả trong mẫu làm đường cơ sở;
- toàn bộ lịch sử thí nghiệm.

Dữ liệu ngoài mẫu và dữ liệu tương lai không được dùng để chọn tham số.

### Bước 6 — Kiểm thử dữ liệu quá khứ ngoài mẫu

Phiên bản đã tối ưu và đóng băng được chạy trên dữ liệu quá khứ ngoài mẫu. Tập
dữ liệu này phải được giữ độc lập với quá trình hình thành giả thuyết, phát
triển và tối ưu.

Mục đích là kiểm tra khả năng khái quát hoá bằng cách so sánh kết quả trong mẫu
và ngoài mẫu. Mức hiệu suất có thể giảm, nhưng hành vi, chiều tác động và hồ sơ
rủi ro phải còn nhất quán ở mức chấp nhận được theo tiêu chí đã đặt trước.

Nếu ngoài mẫu không đạt, phải quay lại Bước 1 để xem xét giả thuyết và thiết kế,
không tiếp tục tinh chỉnh trên tập ngoài mẫu rồi vẫn gọi nó là ngoài mẫu.

### Bước 6.5 — Kiểm định thực thi sàn và an toàn ký quỹ (Plutus Execution Fidelity)

Sau khi thuật toán đạt chuẩn toán học ở Bước 6 (Sharpe, Margin bps ngoài mẫu),
phiên bản thuật toán được đưa vào môi trường mô phỏng khớp lệnh thực tế chuẩn quy
chế sàn Việt Nam (**Plutus** — mô phỏng sàn HNXDS và Trung tâm Bù trừ VSDC) nhằm
kiểm tra tính khả thi khi vận hành với cơ chế tiền mặt và đòn bẩy thật.

Mục đích kiểm định:

1. **Khả năng chịu đòn bẩy & an toàn ký quỹ:** Kiểm tra quy chế thanh toán lãi lỗ
   tiền mặt hàng ngày (Daily Variation Margin VM Cash Settlement) của VSDC. Đảm bảo
   Tỷ lệ sử dụng ký quỹ (Margin Utilisation) luôn nằm trong vùng an toàn (< 80%),
   **tuyệt đối không bị cảnh báo (Warning 80%), gọi ký quỹ (Margin Call 90%) hoặc
   cưỡng bức đóng vị thế (Forced Liquidation 100%)**.
2. **Khớp lệnh & ranh giới thị trường:** Đảm bảo 100% lệnh phát sinh (MTL/LO) hợp
   lệ với bước giá (tick grid), biên độ trần/sàn, và không bị từ chối (0 Rejects).
3. **Đo lường hao mòn chi phí thực tế:** Khấu trừ đầy đủ 100% chi phí pháp định
   theo quy chuẩn (Phí HNX 2,700đ/HĐ, Phí bù trừ VSDC 2,550đ/HĐ, Thuế PIT 0.1%).
4. **Cơ chế tất toán đáo hạn:** Kiểm tra vị thế được tự động tất toán mượt mà vào
   ngày Thứ Năm lần thứ 3 hàng tháng (Expiry Settlement).

Nếu không đạt (bị Margin Call hoặc tỷ lệ ký quỹ vượt quá ranh giới an toàn), thuật
toán phải quay lại Bước 3 hoặc Bước 5 để tinh chỉnh lại quy mô vị thế (position sizing)
hoặc bổ sung bộ lọc rủi ro.

### Bước 7 — Giao dịch trên giấy

Thuật toán được chạy trên dữ liệu thị trường phát sinh theo thời gian thực nhưng
không sử dụng vốn thật. Đây là lần đầu toàn bộ hệ thống phải ra quyết định theo
luồng dữ liệu trực tiếp, không biết trước tương lai.

Bước này kiểm định đồng thời:

- độ tin cậy của hiệu suất trên dữ liệu tương lai chưa từng xuất hiện;
- parity giữa research và runtime theo từng quyết định/bar;
- tính đúng đắn của aggregation, session, clock và rollover;
- đường đi của signal → position → order mô phỏng;
- trạng thái, restart, idempotency và khả năng tái lập;
- monitoring, logging và phát hiện sai lệch;
- tác động ước lượng của phí, spread và slippage.

Nếu kết quả nhất quán với kiểm thử quá khứ và đạt tiêu chí chấp nhận, quy trình
gốc cho phép chuyển sang Bước 8. Trong phạm vi dự án hiện tại, Bước 7 là điểm
dừng cuối cùng.

### Bước 8 — Kiểm thử trên tài khoản nhỏ

Thuật toán sử dụng một phần nhỏ vốn thật để đo các yếu tố mà mô phỏng không thể
phản ánh đầy đủ, ví dụ thanh khoản, trượt giá thực tế và lỗi hệ thống trong quá
trình thực thi. Tài liệu nguồn gợi ý giai đoạn này thường kéo dài khoảng hai
tháng để tích luỹ đủ giao dịch và quan sát độ ổn định.

**Ngoài phạm vi repository hiện tại.**

### Bước 9 — Giao dịch thực

Hệ thống vận hành với toàn bộ quy mô vốn dự kiến, vẫn cần giám sát chặt trong
giai đoạn đầu và tiếp tục theo dõi độ ổn định dài hạn. Một vòng lặp chỉ được xem
là hoàn tất khi hệ thống có thể vận hành ổn định, liên tục và không cần can thiệp
thường xuyên.

**Ngoài phạm vi repository hiện tại.**

## Quy ước dữ liệu của dự án

Repository hiện chia dữ liệu theo ba cửa sổ half-open `[start, end)`:

| Phase | Khoảng thời gian | Vai trò |
|---|---:|---|
| `in_sample` | 2020-01-01 → trước 2023-01-01 | Bước 4–5: phát triển, kiểm thử trong mẫu và tối ưu |
| `out_of_sample` | 2023-01-01 → trước 2025-01-01 | Bước 6: kiểm định độc lập trên quá khứ ngoài mẫu |
| `forward_test` | từ 2025-01-01 | Bước 7: kiểm tra overfit và future/look-ahead leakage trên dữ liệu mới |

VN30F1M hiện không có đủ dữ liệu từ đầu năm 2020; cửa sổ cấu hình vẫn bắt đầu
từ 2020 để áp dụng thống nhất cho các nguồn, còn mỗi dataset chỉ trả về phần dữ
liệu thực sự tồn tại.

`forward_test` phải được xem là dữ liệu bị khoá. Khi kết quả của phase này đã
được dùng để sửa giả thuyết, logic hoặc tham số, phần dữ liệu đã xem không còn
là forward test độc lập cho phiên bản tiếp theo.

## Phạm vi repository: Bước 0–7

Repository này chỉ phục vụ Bước 0 đến Bước 7:

| Bước | Năng lực cần có trong repo | Hiện trạng sơ bộ |
|---:|---|---|
| 0 | Observation ngắn giải thích nguồn gốc của giả thuyết | Có trong hồ sơ giả thuyết Luna |
| 1 | Hồ sơ giả thuyết, giả định, tiêu chí bác bỏ | Chưa có cấu trúc chính thức |
| 2 | Data ingestion, canonical dataset, validation, lineage | Có `lab/data`, cần chuẩn hoá |
| 3 | Strategy/rule definition tách khỏi data và execution | Code hiện còn phân tán |
| 4 | Backtest trong mẫu có accounting chuẩn | Có `lab/backtest` |
| 5 | Experiment và tối ưu có audit trail | Chưa có cấu trúc chính thức |
| 6 | Chạy ngoài mẫu trên phiên bản đã freeze | Có phase config, cần workflow/gate |
| 7 | Paper trading trên dữ liệu thời gian thực | `papertrade/` |
| 8 | Tài khoản thật quy mô nhỏ | Không triển khai |
| 9 | Giao dịch thật toàn phần | Không triển khai |

Vì vậy, `papertrade/` không phải toàn bộ dự án và cũng không phải production với
vốn thật. Nó là adapter/runtime của Bước 7. Kiến trúc mới phải giữ Bước 1–6 độc
lập, có đầu ra rõ ràng, sau đó mới chuyển một phiên bản đã freeze sang Bước 7.

## Các ràng buộc kiến trúc rút ra từ quy trình

1. Giả thuyết, dữ liệu, strategy, backtest, tối ưu và paper runtime là các khối
   riêng; không nhét tất cả vào một alpha hoặc notebook.
2. Mỗi lần chạy phải gắn với phiên bản code, config, data fingerprint và phase.
3. Một engine accounting duy nhất phải được dùng cho mọi candidate research.
4. Dữ liệu trong mẫu, ngoài mẫu và forward test phải được kiểm soát bên ngoài
   strategy; strategy không được tự chọn khoảng thời gian.
5. Chỉ Bước 4–5 được phép tối ưu. Bước 6–7 chỉ đánh giá phiên bản đã freeze.
6. Mỗi gate phải có tiêu chí chấp nhận/bác bỏ được khai báo trước khi chạy.
7. Nếu một gate thất bại, tạo vòng nghiên cứu mới từ Bước 1; không âm thầm sửa
   phiên bản cũ bằng dữ liệu của gate thất bại.
8. Signal logic giữa research và paper runtime phải parity; execution adapter
   được phép khác nhưng phải có contract rõ ràng.
9. Bước 7 không được chứa credential trong code/config versioned và phải có
   logging, reconciliation, restart safety cùng fail-closed behavior.
10. Bước 8–9 không được vô tình xuất hiện dưới tên gọi khác trong repository.

## Điểm cần chốt trước khi thiết kế lại code

- Mẫu chuẩn cho một hồ sơ giả thuyết và tiêu chí bác bỏ ở Bước 1.
- Contract của canonical market data và các kiểm tra chất lượng ở Bước 2.
- Interface chung cho signal, position policy và execution intent ở Bước 3.
- Bộ metric/gate tối thiểu để chấp nhận Bước 4, 6 và 7.
- Cách lưu experiment, parameter search, data fingerprint và artifact.
- Quy tắc freeze/unfreeze một strategy version.
- Cách chứng minh parity giữa backtest và `papertrade/` theo từng bar/quyết định.
