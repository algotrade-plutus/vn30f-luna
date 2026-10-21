# 0. Giới thiệu

## 0.1 Thị trường

Hợp đồng tương lai chỉ số VN30 giao dịch trên thị trường phái sinh của Sở Giao dịch Chứng khoán Hà Nội (HNX). Đề tài
này giao dịch hợp đồng tháng gần nhất, VN30F1M.

| Đặc điểm | Giá trị |
|---|---|
| Tài sản cơ sở | Chỉ số VN30: 30 cổ phiếu vốn hoá lớn và thanh khoản tốt nhất trên HOSE |
| Hệ số nhân | 100.000 đồng mỗi điểm chỉ số |
| Giờ giao dịch | Khớp lệnh định kỳ mở cửa, khớp lệnh liên tục 09:00 đến 11:30 và 13:00 đến 14:30, khớp lệnh định kỳ đóng cửa (ATC) 14:30 đến 14:45 |
| Đáo hạn | Thứ Năm tuần thứ ba của tháng; nếu trùng ngày nghỉ thì lùi về phiên giao dịch liền trước |
| Thanh toán | Bằng tiền, theo chỉ số VN30 |
| Chi phí | Phí HNX và VSDC theo từng hợp đồng, thuế thu nhập cá nhân trên giao dịch chuyển nhượng |

Đây là thị trường dùng đòn bẩy cao, nhà đầu tư cá nhân chiếm tỷ trọng lớn, và không được bán khống cổ phiếu cơ sở. Hai
trong ba giả thuyết ở chương 1 dựa trên chính các đặc điểm này.

## 0.2 Vì sao kết hợp nhiều nguồn alpha

Một thuật toán giao dịch tốt nên kết hợp nhiều nguồn alpha khác nhau. Mỗi nguồn alpha có giai đoạn hoạt động tốt và
giai đoạn kém riêng của nó. Nếu các nguồn dựa trên những cơ chế khác nhau, giai đoạn kém của nguồn này thường rơi vào
giai đoạn tốt của nguồn kia. Khi gộp lại, lợi nhuận đều đặn hơn: Sharpe cao hơn và drawdown nông hơn so với từng nguồn
riêng lẻ. ALGOTRADE Knowledge Hub cũng nêu ý này trong bài *Capital Allocation and Beta Management* (mục "Portfolio
Synergy and Alpha Diversification"): các chiến lược không tương quan với nhau giúp cải thiện Sharpe và rút ngắn thời
gian phục hồi sau drawdown.

Calibrum áp dụng nguyên tắc đó cho VN30F1M với ba nguồn alpha, mỗi nguồn là một sleeve:

| Sleeve | Nguồn alpha | Cơ chế |
|---|---|---|
| Calendar | Kinh nghiệm giao dịch, thiên kiến hành vi | Dòng tiền và áp lực bán theo lịch: đầu tuần, giữa tuần, đầu tháng, trước kỳ nghỉ, ngày đáo hạn |
| Basis | Định giá sai, cấu trúc thị trường | Chênh lệch giữa hợp đồng và chỉ số (basis) lệch quá mức rồi quay về |
| Momentum | Mô hình thống kê, thiên kiến hành vi | Quán tính giá trong phiên (momentum) |

Câu hỏi của đề tài: kết hợp ba nguồn này có cho ra một chiến lược đứng vững ngoài mẫu, sau chi phí thật hay không.

## 0.3 Cách làm

- Xây dựng chiến lược trên nến 30 phút, chỉ dùng dữ liệu đã biết tại thời điểm ra quyết định.
- Đi theo bước 1 đến bước 6 của quy trình 9 bước của ALGOTRADE: hình thành giả thuyết, chuẩn bị dữ liệu, chuyển giả
  thuyết thành luật, backtest in-sample, tối ưu, backtest out-of-sample.
- Kiểm tra bằng hai engine: engine lab chạy nhanh để kiểm tra riêng phần alpha, và sàn giả lập Plutus để kiểm tra alpha
  cùng với việc khớp lệnh, với hợp đồng thật, phí theo quy định và ký quỹ.
- Trước mỗi phép thử, viết ra luật chọn và số lần thử; dữ liệu out-of-sample chỉ nhìn một lần.

## 0.4 Cấu trúc báo cáo

Mỗi chương ứng với một bước, xem [README.md](README.md).
