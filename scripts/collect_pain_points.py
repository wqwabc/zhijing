# -*- coding: utf-8 -*-
"""痛点样本：公开搜索结果（标题 + 落地 URL），按查询维度打原因标签。

双通道：百度优先，被限流时自动切搜狗。
合规：只取标题与链接，不复制正文；不记录个人信息；单条 ≤120 字。

    python collect_pain_points.py --target 200 --sleep 5
"""
from __future__ import annotations
import argparse, html, re, time
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlparse

import requests

from common import TODAY, read_csv, write_csv

S = requests.Session()
S.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Accept-Language": "zh-CN,zh;q=0.9",
})

QUERIES = [
    ("绿植养死了怎么办", "养死"), ("植物叶子发黄怎么办", "养死"),
    ("浇水过多烂根怎么办", "浇水"), ("出差没人浇花怎么办", "养护时间"),
    ("家里光线暗养什么植物", "光照"), ("卧室没有阳光能养绿植吗", "光照"),
    ("阳台西晒植物晒死", "光照"), ("猫吃了绿植中毒", "宠物风险"),
    ("家里有猫能养什么植物", "宠物风险"), ("狗咬植物怎么办", "宠物风险"),
    ("绿植买大了放不下", "尺寸不符"), ("客厅放什么尺寸的绿植", "尺寸不符"),
    ("小户型绿植太多拥挤", "空间拥挤"), ("绿植和家具不搭", "风格不搭"),
    ("北欧风客厅绿植怎么选", "风格不搭"), ("租房买绿植预算多少", "预算"),
    ("租房绿植搬家怎么带走", "搬家"), ("房东不让打孔挂植物", "租房限制"),
    ("绿植长小飞虫怎么办", "虫害"), ("植物叶子灰尘怎么清理", "清洁"),
    ("网上买绿植收到烂了", "购买体验"), ("办公桌放什么植物好养", "养护时间"),
    ("书房放什么绿植不挡光", "尺寸不符"), ("绿植摆放在哪个位置好", "搭配"),
    ("新买的绿植蔫了怎么办", "购买体验"), ("植物烂根怎么救", "浇水"),
    ("绿植多久浇一次水", "浇水"), ("卧室放植物影响睡眠吗", "光照"),
    ("客厅植物怎么摆好看", "搭配"), ("植物叶子上有白点", "虫害"),
    ("阳台种什么花好养", "光照"), ("刚装修完放什么植物", "搭配"),
    ("花盆太小要不要换盆", "尺寸不符"), ("猫咪啃绿萝怎么办", "宠物风险"),
    ("植物掉叶子是什么原因", "养死"), ("客厅放绿植有什么讲究", "搭配"),
]

PLATFORM = {
    "zhidao.baidu.com": "百度知道", "zhihu.com": "知乎", "www.zhihu.com": "知乎",
    "douban.com": "豆瓣", "xiaohongshu.com": "小红书", "tieba.baidu.com": "百度贴吧",
    "baijiahao.baidu.com": "百家号", "jingyan.baidu.com": "百度经验",
    "baike.baidu.com": "百度百科", "post.smzdm.com": "什么值得买",
    "www.douyin.com": "抖音", "wenku.baidu.com": "百度文库",
}


def resolve(link: str) -> str:
    try:
        r = S.head(link, allow_redirects=True, timeout=8)
        return r.url
    except Exception:
        return link


def fetch_hits(q: str):
    """百度 → 搜狗 双通道，返回 [(url, title)]。"""
    for name, url, params in (
        ("baidu", "https://www.baidu.com/s", {"wd": q, "ie": "utf-8", "rn": 20}),
        ("sogou", "https://www.sogou.com/web", {"query": q}),
    ):
        try:
            r = S.get(url, params=params, timeout=25)
            t = r.content.decode("utf-8", "ignore")
        except Exception as e:
            print("  ERR", name, type(e).__name__, flush=True)
            continue
        if len(t) < 50000:
            print("  BLOCK", name, len(t), flush=True)
            continue
        hits = re.findall(r'<h3[^>]*>\s*<a[^>]*href="([^"]+)"[^>]*>(.*?)</a>', t, re.S)
        out = []
        for link, title in hits:
            link = html.unescape(link)
            if link.startswith("/"):
                link = "https://www.sogou.com" + link
            title = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", "", title))).strip()
            if len(title) < 10 or "视频" in title or "图片" in title or "最新相关信息" in title:
                continue
            out.append((link, title))
        if out:
            print("  via", name, len(out), flush=True)
            return out
    return []


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", type=int, default=200)
    ap.add_argument("--sleep", type=float, default=5.0)
    a = ap.parse_args()
    rows = read_csv("pain_points.csv")
    seen = {r["url"] for r in rows}
    print("已有", len(rows), flush=True)

    for q, cause in QUERIES:
        if len(rows) >= a.target:
            break
        hits = fetch_hits(q)
        if not hits:
            time.sleep(a.sleep)
            continue
        with ThreadPoolExecutor(6) as ex:
            finals = list(ex.map(resolve, [h[0] for h in hits]))
        add = 0
        for (link, title), final in zip(hits, finals):
            if len(rows) >= a.target:
                break
            if final in seen or "baidu.com/link" in final or "wappass" in final or "/link?url=" in final:
                continue
            dom = urlparse(final).netloc
            rows.append({
                "pain_id": f"PP-{len(rows)+1:03d}", "raw_text": title[:120],
                "answer_snippet": "", "platform": PLATFORM.get(dom, dom),
                "url": final, "cause_tag": cause, "scene": "通用",
                "collected_at": TODAY, "note": "公开搜索结果标题，链接为原始落地页",
            })
            seen.add(final)
            add += 1
        print(f"{q} -> +{add} (total {len(rows)})", flush=True)
        write_csv("pain_points.csv", rows)
        time.sleep(a.sleep)

    write_csv("pain_points.csv", rows)
    from collections import Counter
    print("total", len(rows), Counter(r["cause_tag"] for r in rows).most_common())


if __name__ == "__main__":
    main()
