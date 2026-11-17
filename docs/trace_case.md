# Trace case: từ trace tới quyết định sai đầu tiên

```bash
cd src
python -m lab9.trace_case --shape seeded_regression --claim C-014 --seed 11
python -m lab9.trace_case --shape fixed --claim C-014 --seed 11   # đối chứng
python -m pytest -q -m student -o addopts= tests/test_lab9_trace_case.py
```

## Case của nhóm: `seeded_regression C-014@11`

| Trường | Nội dung |
|---|---|
| Trial | `seeded_regression C-014@11`, run ID trial `R-seeded_regression-C-014-s11`, report `E-seeded_regression-20261117-3151` (`reports/eval_seeded_regression.json`) |
| Triệu chứng | Lab 8 grader FAIL (`proposal_mismatch`). Ledger ghi **90.000đ**, nhãn là **120.000đ**, và reply nói "đã hoàn **120.000đ**". Trial này vừa sai tiền (FM-05) vừa báo sai số cho khách (FM-08). Grader `pass_rate` chỉ thấy cái đầu, `reply_matches_ledger` thấy cái sau. |
| Bước sai đầu tiên | **Event 5, kind `proposal`**: `{"amount_vnd": 120000}` |
| Vì sao là bước *đầu tiên* | Event 1 `handoff` và 2 `investigator` đúng (O-515 hiển thị, thuộc đúng principal). Event 3 `quote` = 150.000 là đúng (max của ship 30.000 và hỏng hàng 150.000, không cộng). Event 4 `refund_history` chỉ **đọc**: đã hoàn 30.000, chưa quyết định gì. Event 5 là nơi agent tự trừ 30.000 khỏi 150.000. Host (`durability.issue_refund`) trừ khoản đã hoàn thêm một lần nữa nên 150.000 − 30.000 − 30.000 = 90.000. Event 6 `reply` chỉ là hệ quả (nói 120.000). |
| Failure mode | **FM-05** (pre_deducted), kéo theo **FM-08** (reply nói khác ledger) |
| Đối chứng | `fixed C-014@11`: không có event `proposal` (agent truyền nguyên quote 150.000 cho host), ledger 120.000, reply 120.000, mọi grader PASS. |
| Regression test | `tests/test_lab9_trace_case.py` (3 test). Đã **fail trên variant lỗi** theo thiết kế: `RefundAmountCorrect`, `ProposalCorrect`, `ReplyMatchesLedger`, `TrialPass` đều trả False trên `seeded_regression`. Đã **pass trên `fixed`** (cả 6 grader trả đúng). Test 1 ghim số event và `kind` của bước sai. |
| Chưa chắc chắn | Trace không chứng minh *vì sao* agent trừ trước (trong MockLLM đây là công tắc `pre_deducted`, với LLM thật có thể do prompt). Trace cũng không cho biết ý định: chỉ thấy event 5 là `proposal`, không có suy luận. Một case trên một claim không đại diện cho cả FM-05. Cần thêm ≥3 item để thấy xu hướng (v2 có E-105, E-106, E-111). |

## Quy tắc

- Đọc **ledger trước reply**: reply trôi chảy vẫn có thể đi kèm một khoản hoàn sai (C-014 ở trên là ví dụ).
- "Bước sai đầu tiên" phải dẫn số event cụ thể, không phải "agent bị nhầm".
- Case chỉ hoàn thành khi có regression test chạy được. Case này nằm ở `tests/test_lab9_trace_case.py`. C-014 đã là item E-014 trong eval set (provenance `lab8_public`/T14).
- Coding sheet đầy đủ (12 trial → FM + bước sai đầu tiên) nằm trong `docs/failure_taxonomy.md`.
