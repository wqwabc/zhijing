# -*- coding: utf-8 -*-
"""对话层：把当前方案上下文交给 DeepSeek，回答“为什么这样搭 / 能不能更便宜”等问题。

约束：
- 只使用传入的上下文（场景、植物、评分），不编造；
- 没有 Key 时用模板兜底，断网也能答（AC-10）；
- 回答控制在 120 字以内，适合聊天气泡。
"""

from __future__ import annotations

from . import llm

SYSTEM = (
    "你是「植境 Verda」的绿植搭配助手。规则：\n"
    "1) 只能用上下文里的场景、植物、分数与维度回答，不得编造；\n"
    "2) 不超过 120 字，先说结论，再给一句依据；\n"
    "3) 不推荐具体购买链接，不承诺养护效果；\n"
    "4) 不知道就直说“这个我判断不了”。"
)


def _dim_lowest(score: dict) -> str:
    dims = score.get("dimensions") or []
    if not dims:
        return ""
    low = min(dims, key=lambda d: d.get("score", 100))
    return "%s %.0f 分" % (low.get("name", ""), low.get("score", 0))


def fallback(message: str, context: dict) -> str:
    score = context.get("score") or {}
    plants = context.get("plants") or []
    scene = context.get("scene") or {}
    names = "、".join(p.get("name_cn", "") for p in plants[:4])

    if score and ("分" in message or "为什么" in message or "怎么样" in message):
        text = "当前这套综合 %.0f 分：审美 %.0f、适配 %.0f。" % (
            score.get("total", 0), score.get("aesthetic", 0), score.get("fit", 0))
        low = _dim_lowest(score)
        if low:
            text += "最低的是%s，可以先从这一维调整。" % low
        return text

    if names and ("植物" in message or "几株" in message or "什么" in message):
        return "当前放了 %d 株：%s。想换株或加减一株，直接说就行。" % (len(plants), names)

    if "预算" in message:
        return "当前场景预算 %.0f 元；如果要降档，我可以把单价最高的那一株换成入门价位。" % float(
            scene.get("budget") or 0)

    if names:
        return "当前是「%s」%s这套，共 %d 株。可以问我分数、某株的作用，或者让我换一株。" % (
            scene.get("room", ""), scene.get("style", ""), len(plants))
    return "先加几株植物，或者让我按场景推荐一套，我再解释为什么这样搭。"


def reply(message: str, history: list, context: dict,
          llm_cfg: dict = None) -> dict:
    if llm.available(llm_cfg):
        ctx_text = (
            "场景：%s / %s / 光照 %s / 预算 %s 元 / 宠物 %s\n"
            "当前植物：%s\n评分：%s"
            % (context.get("scene", {}).get("room", ""),
               context.get("scene", {}).get("style", ""),
               context.get("scene", {}).get("light", ""),
               context.get("scene", {}).get("budget", ""),
               "有" if context.get("scene", {}).get("has_pet") else "无",
               "、".join(p.get("name_cn", "") for p in context.get("plants", [])) or "无",
               ("综合 %.0f，审美 %.0f，适配 %.0f" % (
                   context["score"].get("total", 0),
                   context["score"].get("aesthetic", 0),
                   context["score"].get("fit", 0))) if context.get("score") else "无")
        )
        msgs = [{"role": "system", "content": SYSTEM},
                {"role": "system", "content": "上下文：\n" + ctx_text}]
        for item in history[-6:]:
            if item.get("role") in ("user", "assistant") and item.get("content"):
                msgs.append({"role": item["role"], "content": str(item["content"])[:500]})
        msgs.append({"role": "user", "content": message})

        text = llm.complete(msgs, temperature=0.6, max_tokens=400,
                            overrides=llm_cfg)
        if text:
            return {"reply": text.strip()[:300], "source": "llm",
                    "model": llm._config(llm_cfg)["model"]}
    return {"reply": fallback(message, context), "source": "template",
            "model": llm._config(llm_cfg)["model"]}
