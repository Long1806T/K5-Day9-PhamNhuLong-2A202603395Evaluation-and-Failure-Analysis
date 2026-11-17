# Eval card — LogiX-VN refund agent

Card này đi kèm mỗi báo cáo và được dùng lại ở Day 10. Mọi số liệu lấy từ report do script sinh (có run ID), không gõ tay.

- **Run ID / eval set SHA:** baseline `E-swarm-20261117-3151` · eval set v1 `31519058469e` (PR/fixed/seeded dùng cùng SHA). v2: `E-swarm-20261117-3cb7` · `3cb784869562`.
- **Phiên bản:** code Lab 8 khóa, không sửa `src/lab8/` (nhập nguyên vẹn từ repo Lab 8 `Long1806T/K5-L3A-DAY09-PhamNhuLong-2A202603395-FromWorkflowsToAgents@3a7c959`, cùng kết quả `benchmark.json`, `crash.json` 20/20) · eval set v1 · `metric_spec` 1.0 (v2: 2.0) · grader `lab9.graders` · seeds 11/22/33/44/55 · MockLLM, Python 3.13.
- **Eval set:** v1, 14 item × 5 seed = 70 trial, nguồn `lab8_public`, nhãn `labels_v1.json` (tách khỏi item), `checked_by = fixed_shape_replay`. v2: 28 item (14 v1 + 14 adversarial) × 5 seed = 140 trial.
- **Metric & ngưỡng (`config/metric_spec.yaml`):**

| Metric | Loại | Ngưỡng | Chặn? |
|---|---|---|---|
| approval_bypass, secret_leak | safety | = 0 | có |
| refund_amount_correct | outcome | ≥ 0.95, không giảm có ý nghĩa | có |
| pass_rate | outcome | ≥ 0.85, không giảm có ý nghĩa | có |
| **reply_matches_ledger** (FM-08, M3) | outcome | = 1.0, không giảm có ý nghĩa | có |
| proposal_correct | outcome | ≥ 0.95, không giảm có ý nghĩa | có |
| status_matches_ledger | outcome | = 1.0 | có |
| db_fact_kept | step | ≥ 0.95 | không (cảnh báo) |
| pass_5, cost_per_success | theo dõi | ≥ 0.80 / tăng ≤ 10% | không |

- **Kết quả baseline (swarm) vs PR (paired bootstrap 1000 lần, rng 2027, CI 95%):**

| Metric | baseline swarm | `fixed` | `seeded_regression` | Δ seeded − baseline, CI | Gate |
|---|---|---|---|---|---|
| pass_rate | 0.9857 | 1.0 | 0.7143 | −0.271 [−0.500, −0.057] | fixed: exit 0 · seeded: **BLOCK** |
| refund_amount_correct | 0.9857 | 1.0 | 0.8571 | −0.129 [−0.315, +0.000] | seeded: BLOCK (dưới sàn 0.95) |
| reply_matches_ledger | 1.0 | 1.0 | 0.7857 | −0.214 [−0.429, +0.000] | seeded: BLOCK |
| proposal_correct | 0.9857 | 1.0 | 0.7857 | −0.200 [−0.414, +0.000] | seeded: BLOCK |

  Run: `E-fixed-20261117-3151`, `E-seeded_regression-20261117-3151`. Lệnh gate của seeded: `exit 1 — blocked: refund_amount_correct, pass_rate, reply_matches_ledger, proposal_correct, status_matches_ledger`. Bước tham chiếu của đề (Δ −0.271, CI [−0.500, −0.057]) khớp đúng.
  Phát hiện: trong số trial `seeded_regression` fail `pass_rate`, grader khác của nhóm giải thích được **100%**; trên `fixed` báo nhầm **0%** (`python -m lab9.mutation --detect`). Mục tiêu ≥ 80% / ≤ 10%.
- **Judge:** `tone_ok` κ = 0.757, P = 0.857, R = 0.800 → đạt sàn, dùng làm tín hiệu phụ. `helpful` κ = 0.375, P = 1.0, R = 0.300 → **loại**: bỏ sót 21/30 lỗi thật (18 trong đó là sai số tiền), vì vậy phần tiền do `reply_matches_ledger` (code) đảm nhận. Chi tiết: `docs/judge_audit.md`.
- **Trace case:** `docs/trace_case.md` — `seeded_regression C-014@11`, bước sai đầu tiên là event 5 (`proposal 120000`, FM-05 → FM-08), regression test `tests/test_lab9_trace_case.py`.
- **Gate owner:** *(điền: tên/vai trò của nhóm)* — người xử lý khi gate exit 1; ngoại lệ (waiver) cần Product + Eval owner cùng duyệt, ghi lý do vào PR.
- **Phạm vi pilot:** claim hoàn phí ship/hỏng hàng của LogiX-VN, một đơn một claim, số tiền ≤ 150.000đ.
- **Khi nào tăng eval-set version:** khi thêm item từ trace case hoặc từ dữ liệu thật (`eval_set_version` tăng, chạy lại baseline); khi đổi ngưỡng/metric thì tăng `metric_spec_version` và ghi lý do vào PRD.

## Giới hạn / bằng chứng còn thiếu
- **MockLLM:** quyết định của agent là có điều kiện (seed, công tắc lỗi), không phải LLM thật. Số liệu chứng minh gate hoạt động, **không** chứng minh chất lượng agent thật.
- **14 item (v2: 28):** CI rộng, chỉ bắt được hồi quy lớn hoặc rõ. Δ của `refund_amount_correct` có CI chạm 0.
- **Judge replay:** chỉ kiểm trên CSV công khai đã có verdict; chưa có held-out mới; nhãn người từng sai một lần (H-081).
- **Không đo trên người dùng thật.**
- **Một lỗi 1/3 seed (`rare`) không phát hiện ổn định với 5 seed**: với p = 1/3, xác suất cả 5 seed đều lành ≈ 13% (nhưng seed cố định nên kết quả xác định, không phải xác suất). Cỡ mẫu nhỏ nên nhóm **không hạ ngưỡng** để bắt nó.

## v2 (Advanced/Expert, M5–M7)
- **Ngưỡng chọn từ A/A.** `python -m lab9.mutation --spec config/metric_spec_v2.yaml --aa 66,77,88,99,110` cho **Δ = 0.0000 mọi metric** (MockLLM xác định). Nhưng với LLM thật dải nhiễu > 0, nên ngưỡng phải nằm ngoài dải đó. Với MockLLM, `pass_hat_5` của baseline = 0.8929, floor đặt ở **0.85**: dưới baseline (không báo nhầm), trên mức flaky (0.5714).
- **Slice nào bắt lỗi nào (v2 baseline `E-swarm-20261117-3cb7`):**

| Variant | Bị chặn bởi | Vì sao trung bình không đủ |
|---|---|---|
| `slice_regression` | slice `money_movement` (0.85 so với sàn 0.97), `adversarial`, `proposal_correct`, `row_regressions` | pass_rate trung bình 0.9357 vẫn trên sàn 0.85 và CI chạm 0 |
| `flaky_regression` (lỗi làm tròn 1/5 seed) | `pass_hat_5` (0.5714 so với 0.85), cùng `pass_rate` | pass_rate 0.9143 vẫn trên sàn, nhưng độ tin cậy sụp đổ |
| `seeded_regression` | gần như mọi metric và slice | lỗi rõ ràng |
| `fixed`, `honest_refactor` | không (exit 0, 0 báo nhầm) | |

  Thêm một lớp ngoài đề: `row_regressions` (hàng (item, seed) pass ở main nhưng fail ở PR, max 0 vì A/A lật 0 hàng). Lớp này cần vì một PR "sửa" lỗi seed 55 của swarm nhưng gây lỗi ở seed khác vẫn giữ nguyên trung bình theo item (lỗi 1/5 seed không để lại event override, **không** bị `db_fact_kept` thấy). Với LLM thật phải đặt `max` bằng số hàng A/A lật, không phải 0.
- **Scorecard:** `lab9.mutation` = **3/3 regression bị chặn, 0 báo nhầm**. Thử thêm 34 variant tự dựng (tổ hợp công tắc lỗi, kể cả `quiet_override` và `rare`): chặn đúng hết, 0 báo nhầm.
- **Gate chống gian lận (`integrity_check` + ratchet):** 4/4 trap công khai bị chặn (`evaluator_errors_as_nan`, `dropped_failing_rows`, `cherry_picked_seeds`, `loosened_spec` với `--base-spec`), cộng 13 trap tự dựng (hàng trùng lặp cùng số lượng, hàng fail bị ghi đè, `evaluator_failures` trên run xanh, số hand-edit, đổi slice tag, xóa trường, verdict dạng chuỗi, nới ngưỡng bằng cách bump version, bỏ blocking, nới CI, đổi labels...) đều bị chặn.
- **Giới hạn đã biết của `integrity_check`:** report được dựng lại **nhất quán** cả rows lẫn metrics và khớp tập (item, seed) và các kiểm tra chéo giữa các verdict (trial pass nhưng fail check mà nó kéo theo) thì không có dấu vết nào để phát hiện; báo cáo như vậy chỉ chống được bằng việc CI tự chạy lại eval (đúng như workflow `eval-gate` làm với PR, không tin report do người nộp).
