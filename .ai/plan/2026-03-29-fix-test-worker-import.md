# Fix test worker import
Date: 2026-03-29
Status: done

---
---
# Fix test_worker.py import error

## 背景

commit 9347f18 从 `stages/gpu/worker.py` 删除了 `_sanitize_generation_results_for_ipc`，
但 `tests/test_worker.py` 未同步清理。

## 改动文件

- `tests/test_worker.py`：删除 `_sanitize_generation_results_for_ipc` 的 import 及对应测试函数

## 不改动文件

无其他文件需要改动。
