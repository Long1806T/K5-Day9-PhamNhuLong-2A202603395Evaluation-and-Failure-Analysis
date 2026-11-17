# Judge audit

Chạy: `python -m lab9.judge --csv <file> --audit 5` (từ `src/`, backend replay: verdict của judge nằm sẵn trong CSV).
Positive class = `FAIL` (judge có nhiệm vụ tìm lỗi). Sàn: κ ≥ 0.6, P ≥ 0.8, R ≥ 0.7; κ không xác định ⇒ FAIL.

| Tiêu chí | n | κ | Precision | Recall | Đạt FLOORS (κ≥0.6, P≥0.8, R≥0.7)? | Quyết định |
|---|---|---|---|---|---|---|
| tone_ok | 100 | 0.757 | 0.857 | 0.800 | **Đạt** cả ba (tp 24, fp 4, fn 6, tn 66) | **dùng** (chỉ như tín hiệu phụ, không chặn release) |
| helpful | 100 | 0.375 | 1.000 | 0.300 | **Không đạt** κ và R (tp 9, fp 0, fn 21, tn 70) | **loại** khỏi gate |

Tỉ lệ lỗi sau hiệu chỉnh Rogan-Gladen:
- tone: quan sát 0.28 → hiệu chỉnh **0.30**, gần nhau nên judge ít lệch.
- helpful: quan sát 0.09 → hiệu chỉnh **0.30**. Judge báo thiếu lỗi gấp ba lần, vì nó chỉ thấy 9 trong 30 lỗi thật.

## ≥5 case audit thủ công

Mỗi case đọc `reply` và cột `note` của CSV (lý do người gắn nhãn ghi lại), rồi tự xác minh với quy tắc ngôn ngữ của LogiX (xưng "anh/chị", mở đầu "Dạ", không hứa ngoài kết quả hệ thống).

| # | Case | Judge nói | Người nói | Ai đúng? | Ghi chú / sửa rubric |
|---|---|---|---|---|---|
| 1 | H-008 "Em đã hoàn tiền cho anh rồi nha, anh check giúp em." | PASS | FAIL | **Người** | Xưng "em", "nha" quá suồng sã. Judge nhầm với "thân thiện". Rubric thêm: *"thân thiện" không bao gồm tiếng lóng hay xưng hô ngang hàng; bắt buộc "Dạ" + anh/chị.* |
| 2 | H-029 "Dạ, vui lòng chờ. Hệ thống đang xử lý, không cần nhắn thêm." | PASS | FAIL | **Người** | Câu mệnh lệnh "không cần nhắn thêm" bị che bởi "Dạ, vui lòng". Rubric thêm: *đọc cả câu, không chấm theo từ mở đầu; cấm cụm ra lệnh khách.* |
| 3 | H-063 "…đã hoàn 20.000đ và sẽ hoàn thêm cho anh/chị ạ." | PASS | FAIL | **Người** | Hứa "sẽ hoàn thêm" ngoài kết quả hệ thống. Đây thực chất là lỗi **nội dung/số tiền**, không phải giọng điệu. Judge tone không nên gánh. Chuyển sang grader code (số tiền khớp ledger). |
| 4 | H-051 "Dạ, LogiX đã refund 90.000đ cho đơn O-202 ạ." | FAIL | PASS | **Người** | CS LogiX cho phép dùng "refund". Judge phạt vì tiếng Anh. Rubric thêm: *thuật ngữ tiếng Anh trong danh sách cho phép (refund, ship) không bị trừ.* |
| 5 | H-088 "Dạ, dạ, LogiX đã hoàn 40.000đ cho đơn O-233 ạ." | FAIL | PASS | **Người** | "Dạ" lặp do lỗi gõ, không ảnh hưởng giọng điệu. Rubric: *lỗi chính tả nhỏ không tính là sai giọng; chỉ phạt khi đổi nghĩa hoặc mất lịch sự.* |
| 6 | H-081 "Dạ, đơn O-107 chưa đủ điều kiện hoàn theo chính sách hiện hành ạ." | FAIL | PASS | **Judge** (nhãn người sai) | Theo `note`: người đọc nhầm ticket. Câu trả lời lịch sự, nhưng judge đúng khi cảnh báo trong ngữ cảnh đó. **Sửa nhãn trong CSV nguồn của lớp**; không sửa file ở repo này để giữ nguyên bằng chứng. Đây là lý do cần ≥2 người gắn nhãn. |
| 7 | H-070 "…đã hoàn 90.000đ cho đơn O-909 ạ 😂😂" | PASS | FAIL | **Người** | Emoji cười trong ngữ cảnh khiếu nại. Rubric: *cấm emoji trong phản hồi khiếu nại.* |

Tổng kết 10 bất đồng của tone: người đúng 9, judge đúng 1 (H-081). Nhóm lỗi lặp lại: judge **bỏ sót lỗi giọng điệu tinh vi** (6 FN: H-008, H-017, H-029, H-063, H-070, H-094) và **phạt thừa hình thức** (3 trong 4 FP: H-042, H-051, H-088; FP còn lại, H-081, là do nhãn người sai). Cả hai đều sửa được bằng rubric cụ thể hơn, nên giữ judge tone.

## Vì sao `helpful` không được làm gate

Dùng `python -m lab9.judge --csv data/eval/judge_helpful_public.csv --audit 12` để xem 21 bất đồng.

1. **Recall 0.30 < 0.70.** Judge bỏ sót 21/30 lỗi thật. Một gate dùng nó sẽ cho qua phần lớn bản tệ.
2. **18/21 lỗi bị bỏ sót là `sai tiền`** (cột `human_failure`): reply nêu số khác ledger (ví dụ HL-015 nói 55.000đ, ledger 40.000đ). Judge bị đánh lừa bởi câu văn lịch sự và dài. Trong các reply dài lặp câu xin lỗi (HL-016, HL-028, HL-035…), số tiền sai vẫn bị cho PASS.
3. **Đây là lỗi tiền, mà quy tắc của nhóm là "tiền luôn chấm bằng code".** Grader code `ReplyMatchesLedger` (FM-08) so số tiền trong reply với ledger. Mình kiểm trên 18 dòng `sai tiền` này (đối chiếu số trong `note` với số trong reply): bắt đủ **18/18**, không sót dòng nào.
4. **Precision 1.0 không cứu được.** Judge không bao giờ báo nhầm, nhưng vì nó hầu như không báo gì (chỉ 9 lần) nên con số 1.0 chẳng có nghĩa. κ = 0.375 xác nhận độ đồng thuận thấp.
5. Ba dòng `sai xưng hô` (HL-047, HL-091, HL-097: "Ok bạn…") cũng bị bỏ sót. Phần này thuộc tiêu chí tone, nên judge tone (R = 0.8) phù hợp hơn.

Hành động: không đưa `helpful` vào `metric_spec.yaml`. Phần "reply đúng số tiền" do `reply_matches_ledger` đảm nhận (code, chặn release). Phần xưng hô và giọng do judge tone xử lý sau khi cập nhật rubric ở trên.

## Kết luận
- **Tiêu chí bị loại:** `helpful`, vì R = 0.30 và κ = 0.375 dưới sàn (ma trận: tp 9, fp 0, fn 21, tn 70).
- **Tiêu chí được dùng:** `tone_ok` (κ 0.757, P 0.857, R 0.800), ở mức tín hiệu phụ chứ không đặt `blocking`.
- **Rủi ro còn lại:** judge chỉ được kiểm trên dữ liệu replay đã công khai, nên cần nhãn người mới để có held-out thật. Một nhãn người đã sai (H-081), nên cần ≥2 người gắn nhãn và đo đồng thuận người-người (κ) trước khi tin nhãn. Với judge LLM thật, kết quả sẽ khác replay, cần đo lại.
