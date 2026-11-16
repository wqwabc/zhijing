# 采集日志

每次运行 `collect.py` 会在这里按天生成 `collect_YYYYMMDD.jsonl`，一行一次下载或去底事件，字段：ts / event / plant_id / source / file / width / height / dominant_hex。

授权表的 `proof_path` 默认指向 `assets/inbox/_candidates.jsonl`，日志是本目录的日级流水，两者一起构成可追溯证据。
