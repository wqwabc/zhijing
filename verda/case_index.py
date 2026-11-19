# -*- coding: utf-8 -*-
"""案例库检索（FR-09）

对应《需求分析 v2.1》FR-09：
    · 采集 100–150 张有授权的室内绿植照片
    · 自动打标：房间类型、风格、主色、植物数量
    · 支持按风格/场景筛选，按「找相似」检索
    · 图片可点回原页面，显示作者与许可
    · 验收 AC-06：top-3 相关案例命中率 ≥80%（人工 30 组查询）

实现：用 ResNet50 的 2048 维语义特征 + 余弦相似度。特征只在第一次建库时算，
落盘缓存到 `.cache/case_embeddings.npz`，之后秒开。

两种检索入口：
    search_by_image()   以图搜图（用户上传自己的房间照片，找相似的案例）
    search_by_palette() 按配色搜（不需要模型，纯 OKLCH 距离，任何时候都能用）
"""

import csv
import json
import os
import time
from typing import Dict, List, Optional, Sequence

import numpy as np

from .color import hex_to_oklch, hue_distance


def _parse_palette(text: str) -> List[str]:
    """B 的 palette_hex 是 "CCCFD0/#B4B5B2/#2A3032" 这种，解析成 hex 列表"""
    if not text:
        return []
    out = []
    for part in str(text).replace("#", "").split("/"):
        s = part.strip()
        if len(s) == 6:
            out.append("#" + s.upper())
    return out


class CaseIndex:
    """案例库索引

    用法：
        from verda.embedding import ImageEmbedder
        idx = CaseIndex(ImageEmbedder("resnet50"))
        idx.build()                                  # 首次会算特征，之后读缓存
        hits = idx.search_by_image("myroom.jpg", top_k=3, style="nordic")
    """

    def __init__(self, embedder=None, manifest_csv: str = None,
                 cases_root: str = None, cache_path: str = None):
        # 延迟导入，避免不用图像检索时也去 import torch
        if embedder is None:
            from .embedding import ImageEmbedder
            embedder = ImageEmbedder("resnet50")
        self.embedder = embedder

        if manifest_csv is None or cases_root is None:
            data_dir = self._find_data_dir()
            manifest_csv = manifest_csv or os.path.join(data_dir,
                                                        "cases_manifest.csv")
            # B 的 file_path 是相对「B 包的根目录」写的（assets/cases/xxx.jpg），
            # 所以 cases_root 应该是仓库根，也就是 data 目录的上一层
            cases_root = cases_root or os.path.dirname(data_dir)
        self.manifest_csv = manifest_csv
        self.cases_root = cases_root
        # 缓存放在 .cache/ 下，不污染数据目录
        c_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.cache_path = cache_path or os.path.join(
            c_root, ".cache", "case_embeddings.npz")

        self.cases: List[dict] = []
        self.matrix: Optional[np.ndarray] = None

    @staticmethod
    def _find_data_dir() -> str:
        here = os.path.dirname(os.path.abspath(__file__))
        cur = here
        for _ in range(5):
            cur = os.path.dirname(cur)
            cand = os.path.join(cur, "data")
            if os.path.isdir(cand):
                return cand
        raise FileNotFoundError("找不到 data 目录")

    # ---------------- 建库 ----------------

    def load_manifest(self) -> List[dict]:
        """读 cases_manifest.csv，只保留有图、有标签的"""
        rows = []
        with open(self.manifest_csv, "r", encoding="utf-8-sig", newline="") as f:
            for r in csv.DictReader(f):
                if not r.get("case_id") or not r.get("file_path"):
                    continue
                r["palette"] = _parse_palette(r.get("palette_hex", ""))
                r["abs_path"] = os.path.join(self.cases_root,
                                             r["file_path"].replace("\\", "/"))
                r["exists"] = os.path.exists(r["abs_path"])
                if not r["exists"]:
                    continue
                rows.append(r)
        return rows

    def build(self, force: bool = False, verbose: bool = True) -> "CaseIndex":
        """建索引：算特征矩阵，落盘缓存"""
        self.cases = self.load_manifest()
        if not self.cases:
            raise RuntimeError("案例清单是空的：%s" % self.manifest_csv)

        ids = [c["case_id"] for c in self.cases]

        # 命中缓存就直读
        if not force and os.path.exists(self.cache_path):
            data = np.load(self.cache_path, allow_pickle=True)
            cached_ids = list(data["case_ids"])
            if cached_ids == ids:
                self.matrix = data["matrix"]
                if verbose:
                    print("读缓存：%d 条案例，特征维度 %d"
                          % (self.matrix.shape[0], self.matrix.shape[1]))
                return self

        if verbose:
            print("建索引：%d 条案例，骨干网 %s"
                  % (len(self.cases), self.embedder.backbone))
        t0 = time.time()
        paths = [c["abs_path"] for c in self.cases]
        self.matrix = self.embedder.embed_batch(paths, verbose=verbose)
        dt = time.time() - t0

        os.makedirs(os.path.dirname(self.cache_path), exist_ok=True)
        np.savez_compressed(self.cache_path,
                            case_ids=np.array(ids, dtype=object),
                            matrix=self.matrix)
        if verbose:
            print("建库完成：%d 条 × %d 维，耗时 %.1f 秒（单条约 %.2f 秒），"
                  "缓存 -> %s"
                  % (self.matrix.shape[0], self.matrix.shape[1], dt,
                     dt / max(len(ids), 1), os.path.basename(self.cache_path)))
        return self

    # ---------------- 检索 ----------------

    def _filter(self, style: str = None, room: str = None,
                usable_for: str = None) -> List[int]:
        """按标签筛出候选下标"""
        idx = []
        for i, c in enumerate(self.cases):
            if style and c.get("style") != style:
                continue
            if room and c.get("room") != room:
                continue
            if usable_for and usable_for not in (c.get("usable_for") or ""):
                continue
            idx.append(i)
        return idx

    @staticmethod
    def _pack(case: dict, score: float) -> dict:
        """输出结构，带上溯源信息（FR-09 要求可点回原页面看作者和许可）"""
        return {
            "case_id": case["case_id"],
            "file_path": case["file_path"],
            "score": round(float(score), 4),
            "room": case.get("room", ""),
            "style": case.get("style", ""),
            "plant_count": case.get("plant_count", ""),
            "height_profile": case.get("height_profile", ""),
            "palette": case.get("palette", []),
            "source": case.get("source", ""),
            "source_url": case.get("source_url", ""),
            "author": case.get("author", ""),
            "license": case.get("license", ""),
            "license_url": case.get("license_url", ""),
        }

    def search_by_image(self, image_path: str, top_k: int = 3,
                        style: str = None, room: str = None,
                        exclude_case_id: str = None) -> List[dict]:
        """以图搜图：给一张图，找最相似的案例"""
        if self.matrix is None:
            raise RuntimeError("先调 build() 建索引")

        q = self.embedder.embed(image_path)          # 已 L2 归一化
        sims = self.matrix @ q                        # 余弦相似度

        cand = self._filter(style=style, room=room)
        scored = []
        for i in cand:
            if exclude_case_id and self.cases[i]["case_id"] == exclude_case_id:
                continue
            scored.append((i, float(sims[i])))
        scored.sort(key=lambda x: -x[1])

        return [self._pack(self.cases[i], s) for i, s in scored[:top_k]]

    def search_by_case_id(self, case_id: str, top_k: int = 3,
                          same_style: bool = False,
                          same_room: bool = False) -> List[dict]:
        """用库里某个案例反查相似案例（评估和演示用）"""
        if self.matrix is None:
            raise RuntimeError("先调 build() 建索引")
        pos = next((i for i, c in enumerate(self.cases)
                    if c["case_id"] == case_id), None)
        if pos is None:
            raise KeyError("没有这个案例：%s" % case_id)

        base = self.cases[pos]
        sims = self.matrix @ self.matrix[pos]

        cand = self._filter(
            style=base.get("style") if same_style else None,
            room=base.get("room") if same_room else None)

        scored = [(i, float(sims[i])) for i in cand if i != pos]
        scored.sort(key=lambda x: -x[1])
        return [self._pack(self.cases[i], s) for i, s in scored[:top_k]]

    def search_by_palette(self, hex_list: Sequence[str], top_k: int = 3,
                          style: str = None, room: str = None) -> List[dict]:
        """按配色搜（纯 OKLCH，不需要模型）

        距离算法：对查询色和案例色的每个配对算 OKLCH 距离
        （明度差 × 1.0 + 彩度差 / 0.3 + 色相差 / 180），取每对里最小的，
        再对所有配对的均值作为总距离，最后换算成 0~1 的相似度。
        """
        q = [hex_to_oklch(h) for h in hex_list if h]
        if not q:
            return []

        cand = self._filter(style=style, room=room)
        scored = []
        for i in cand:
            pal = self.cases[i].get("palette") or []
            if not pal:
                continue
            targets = [hex_to_oklch(h) for h in pal]
            pair_dists = []
            for ql, qc, qh in q:
                best = None
                for tl, tc, th in targets:
                    d = (abs(ql - tl) + abs(qc - tc) / 0.3
                         + hue_distance(qh, th) / 180.0)
                    if best is None or d < best:
                        best = d
                pair_dists.append(best)
            avg = sum(pair_dists) / len(pair_dists)
            # 距离 0 完全一致（相似度 1.0），距离 3 最不相干（相似度 0.25）
            scored.append((i, 1.0 / (1.0 + avg)))

        scored.sort(key=lambda x: -x[1])
        return [self._pack(self.cases[i], s) for i, s in scored[:top_k]]

    def find_duplicates(self, threshold: float = 0.999) -> List[List[str]]:
        """找出内容重复的案例

        B 的包里存在同一张图被采两次、标成不同风格的情况（实测 10 组）。
        这会让检索结果出现「看起来一样的两条」，也让风格标签失去意义。

        这里用特征相似度判断（阈值默认 0.999，几乎只命中完全相同的图），
        返回每组重复的 case_id + 文件名，方便反馈给 B 清理。
        """
        if self.matrix is None:
            raise RuntimeError("先调 build() 建索引")

        sims = self.matrix @ self.matrix.T
        n = len(self.cases)
        seen = set()
        groups: List[List[str]] = []

        for i in range(n):
            if i in seen:
                continue
            group = [i]
            for j in range(i + 1, n):
                if j in seen:
                    continue
                if float(sims[i, j]) >= threshold:
                    group.append(j)
                    seen.add(j)
            if len(group) > 1:
                seen.add(i)
                groups.append([
                    "%s %s (%s/%s)" % (
                        self.cases[k]["case_id"],
                        os.path.basename(self.cases[k]["file_path"]),
                        self.cases[k].get("style"), self.cases[k].get("room"))
                    for k in group
                ])
        return groups

    # ---------------- 检索质量评估 ----------------

    def evaluate(self, n_queries: int = 30, top_k: int = 3) -> dict:
        """自动评估 top-k 命中率（AC-06 要 >=80%）

        需求那边的验收是「人工 30 组查询」，这里用自动代理指标：
        随机抽 n_queries 个案例当查询，看 top-k 结果里有没有同风格或同场景的。
        虽然没有人工判断严谨，但能发现明显坏掉的检索。
        """
        if self.matrix is None:
            raise RuntimeError("先调 build() 建索引")

        rng = np.random.default_rng(42)
        n = len(self.cases)
        picks = rng.choice(n, size=min(n_queries, n), replace=False)

        style_hits = 0
        room_hits = 0
        rows = []
        for pos in picks:
            base = self.cases[int(pos)]
            sims = self.matrix @ self.matrix[int(pos)]
            order = np.argsort(-sims)
            top = [int(i) for i in order if int(i) != int(pos)][:top_k]

            s_hit = any(self.cases[i].get("style") == base.get("style")
                        for i in top)
            r_hit = any(self.cases[i].get("room") == base.get("room")
                        for i in top)
            style_hits += 1 if s_hit else 0
            room_hits += 1 if r_hit else 0
            rows.append({
                "query": base["case_id"],
                "query_style": base.get("style"),
                "query_room": base.get("room"),
                "top": [self.cases[i]["case_id"] for i in top],
                "style_hit": s_hit,
                "room_hit": r_hit,
            })

        n_q = len(rows)
        return {
            "queries": n_q,
            "top_k": top_k,
            "style_hit_rate": round(style_hits / n_q, 3) if n_q else 0,
            "room_hit_rate": round(room_hits / n_q, 3) if n_q else 0,
            "either_hit_rate": round(
                sum(1 for r in rows if r["style_hit"] or r["room_hit"]) / n_q, 3)
            if n_q else 0,
            "details": rows,
        }
