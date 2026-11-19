# -*- coding: utf-8 -*-
"""风格分类基线（对应需求「风格识别 top-1」）

需求写的是「CLIP 选型与评测方案 + 风格分类基线（top-1）」。
本机没有 CLIP，这里用现成的 ResNet50 特征 + 逻辑回归训一个基线出来，
把「top-1 准确率」这个指标先立起来——以后换 CLIP 只要替换特征提取器，
评估代码一行不用改。

数据来源：B 的 120 条案例（实测有 10 组重复，去重后 110 条），
6 种风格各约 18~20 条。样本量小，所以用 5 折分层交叉验证而不是单次划分——
单次 70/30 划分在 110 条上抖得太厉害，结果不可信。

注意：这个基线是「在 B 的案例库内部」评估的，反映的是
「同类风格的照片特征是否聚集」，不等于在真实用户照片上的效果。
答辩时这点要说清楚。
"""

from typing import Dict, List, Optional, Tuple

import numpy as np

STYLE_NAMES = {
    "nordic": "北欧自然",
    "wabi": "日式侘寂",
    "midcentury": "中古复古",
    "minimal": "现代极简",
    "tropical": "热带雨林",
    "industrial": "工业冷调",
}


class StyleClassifier:
    """用图像特征训一个风格分类器

    用法：
        from verda.embedding import ImageEmbedder
        from verda.case_index import CaseIndex
        from verda.style_clf import StyleClassifier

        idx = CaseIndex(ImageEmbedder("resnet50")).build()
        clf = StyleClassifier().fit(idx)
        print(clf.evaluate())
        style, prob = clf.predict("my_photo.jpg")
    """

    def __init__(self, embedder=None):
        self.embedder = embedder
        self.model = None
        self.classes_: List[str] = []
        self.X: Optional[np.ndarray] = None
        self.y: Optional[np.ndarray] = None
        self.eval_result: Optional[dict] = None

    # ---------------- 训练 ----------------

    def fit(self, index, drop_duplicates: bool = True) -> "StyleClassifier":
        """从 CaseIndex 的特征和标签训练

        drop_duplicates: 是否去掉内容重复的案例。默认去——
            重复图会被分到不同风格（这是 B 的数据问题），
            留着等于给同一张图两个互相矛盾的标签，会拉低准确率。
        """
        from sklearn.linear_model import LogisticRegression

        if index.matrix is None:
            raise RuntimeError("先调 index.build() 建索引")
        if self.embedder is None:
            self.embedder = index.embedder

        keep = list(range(len(index.cases)))
        if drop_duplicates:
            drop = set()
            for group in index.find_duplicates():
                # group 里每条是 "C-001 xxx.jpg (nordic/living)" 格式
                for item in group[1:]:
                    cid = item.split()[0]
                    for i, c in enumerate(index.cases):
                        if c["case_id"] == cid:
                            drop.add(i)
                            break
            keep = [i for i in keep if i not in drop]

        self.X = index.matrix[keep]
        self.y = np.array([index.cases[i].get("style") or "unknown"
                           for i in keep])

        # 丢掉样本太少的类（交叉验证分层需要每类至少 k 个）
        uniq, counts = np.unique(self.y, return_counts=True)
        valid = {u for u, c in zip(uniq, counts) if c >= 5}
        mask = np.array([label in valid for label in self.y])
        self.X = self.X[mask]
        self.y = self.y[mask]

        # sklearn 1.5 起 multi_class 参数已弃用，多分类自动用 multinomial
        self.model = LogisticRegression(max_iter=2000, C=10.0)
        self.model.fit(self.X, self.y)
        self.classes_ = list(self.model.classes_)
        return self

    # ---------------- 评估 ----------------

    def evaluate(self, cv: int = 5) -> dict:
        """5 折分层交叉验证，返回 top-1 准确率和混淆矩阵"""
        from sklearn.linear_model import LogisticRegression
        from sklearn.metrics import (accuracy_score, confusion_matrix,
                                     classification_report)
        from sklearn.model_selection import StratifiedKFold

        if self.X is None or self.y is None:
            raise RuntimeError("先调 fit()")

        # 每类样本数可能少于 cv，动态收缩折数
        _, counts = np.unique(self.y, return_counts=True)
        folds = int(min(cv, counts.min()))
        if folds < 2:
            raise RuntimeError("每类样本太少（最少 %d 个），做不了交叉验证"
                               % counts.min())

        skf = StratifiedKFold(n_splits=folds, shuffle=True, random_state=42)
        y_true, y_pred = [], []

        for train_idx, test_idx in skf.split(self.X, self.y):
            clf = LogisticRegression(max_iter=2000, C=10.0)
            clf.fit(self.X[train_idx], self.y[train_idx])
            pred = clf.predict(self.X[test_idx])
            y_true.extend(self.y[test_idx])
            y_pred.extend(pred)

        acc = accuracy_score(y_true, y_pred)
        labels = sorted(set(y_true))
        cm = confusion_matrix(y_true, y_pred, labels=labels)
        report = classification_report(y_true, y_pred, labels=labels,
                                       output_dict=True, zero_division=0)

        # 多数类基线：全部猜最常见那类能得多少
        uniq, cnt = np.unique(self.y, return_counts=True)
        majority = float(cnt.max() / cnt.sum())
        # 随机基线
        random_base = 1.0 / len(uniq)

        result = {
            "samples": int(len(self.y)),
            "classes": len(uniq),
            "folds": folds,
            "top1_accuracy": round(float(acc), 3),
            "majority_baseline": round(majority, 3),
            "random_baseline": round(random_base, 3),
            "lift_over_majority": round(float(acc) - majority, 3),
            "labels": labels,
            "confusion_matrix": cm.tolist(),
            "per_class_f1": {
                k: round(v["f1-score"], 3)
                for k, v in report.items()
                if k in labels
            },
            "note": ("样本量 %d、%d 类，5 折交叉验证。"
                     "这是案例库内部的评估，不等于真实用户照片上的效果。"
                     % (len(self.y), len(uniq))),
        }
        self.eval_result = result
        return result

    # ---------------- 预测 ----------------

    def predict(self, image_path: str) -> Tuple[str, float, Dict[str, float]]:
        """预测单张图片的风格

        返回 (风格 key, 置信度, 各类概率字典)
        """
        if self.model is None:
            raise RuntimeError("先调 fit()")
        if self.embedder is None:
            raise RuntimeError("没有特征提取器")

        v = self.embedder.embed(image_path).reshape(1, -1)
        proba = self.model.predict_proba(v)[0]
        order = np.argsort(-proba)
        best = self.classes_[order[0]]
        detail = {self.classes_[i]: round(float(proba[i]), 4)
                  for i in order}
        return best, float(proba[order[0]]), detail

    def predict_style_or_none(self, image_path: str,
                              threshold: float = 0.35) -> Optional[str]:
        """置信度低于阈值就返回 None，让调用方走「用户手动选」的兜底"""
        style, prob, _ = self.predict(image_path)
        return style if prob >= threshold else None

    def style_name(self, key: str) -> str:
        return STYLE_NAMES.get(key, key)

    def confusion_table(self) -> List[str]:
        """把混淆矩阵排成可打印的表格"""
        if not self.eval_result:
            raise RuntimeError("先调 evaluate()")
        labels = self.eval_result["labels"]
        cm = self.eval_result["confusion_matrix"]
        short = [STYLE_NAMES.get(l, l)[:2] for l in labels]

        head = "        " + "".join("%6s" % s for s in short)
        lines = [head, "        " + "-" * (6 * len(short))]
        for i, lab in enumerate(labels):
            row = "%6s  " % STYLE_NAMES.get(lab, lab)[:4]
            row += "".join("%6d" % v for v in cm[i])
            lines.append(row)
        lines.append("")
        lines.append("（行=真实，列=预测；对角线上的数越大越好）")
        return lines
