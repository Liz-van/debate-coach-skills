#!/usr/bin/env python3
"""双 Agent 对抗收敛记录预检：出文件前校验 debate.json（可配合 md 报告一起查）。

用法:
  check_debate.py <debate.json> [--md <报告.md>] [--tier 精简|标准|完整]

硬项（不通过 → 退出码 1，先修再出文件）:
  H1 头部字段完整；roles 三项齐全，未标 fallback 时主笔与对手必须是两个不同 agent
  H2 攻防轮数 ≥ 档位下限；标准/完整档必须有对手判决陈述
  H3 每条攻击：编号唯一、目标论点存在、环节合法、严重程度合法、主张/依据/最低修补要求非空
  H3b 首轮草案登记的论点个数 ≥ 3（论点数量三档一致，固定 3 个）
  H4 攻击总数 ≥ 档位下限
  H5 每条攻击至少一条修补回应
  H6 修补回应：对应攻击存在、处理动作合法、具体改法非空、代价非空
  H7 致命级攻击必须有真改（修补/换证据/改判准/让步删点），不许只「拒绝并说明」
  H8 每个论点都有裁决；裁决目标存在、结果合法、理由非空
  H9 裁决后存活论点 ≥ 3（论点数量三档一致，固定 3 个）
  H10 md 的 §4 论点体系段不得出现预判对方反驳的句式（立论不预判反驳）
  H11 讨论轨（【讨论】触发的追加对抗轮）：每轮字段齐全（n 唯一、trigger/attacks/defenses/verdicts/changed 都不为空）；
      讨论轮不计入 H2 轮数与 H4 攻击总数（首轮收敛的档位下限一条都不放宽）
  H12 讨论轮每条攻击：编号在本轮内唯一、目标 ∈ 论点编号 ∪ {判准, 全局}、环节与严重程度合法、主张/依据/最低修补要求非空
  H13 讨论轮每条攻击都有回应；回应字段合法（动作合法、具体改法≥8 字、代价非空）；致命级必须真改
  H14 讨论轮每条攻击都有裁决（成立/不成立 + 理由非空）；changed 逐项非空

软项（告警，不阻断）:
  S1 攻击覆盖的论点个数是否够广（只打一个点说明对手没尽责）
  S2 有没有论点一次都没被打（说明对抗没覆盖到）
  S3 严重程度是否全是「次要」（对抗强度不足）
  S4 「拒绝并说明」占比是否过高（超过一半说明修补不实）
  S5 攻击依据是否既无来源编号、又没标「逻辑反驳」
  S6 记录档位与命令行档位不一致
  S7 讨论轮的 changed 里出现「全篇 / 整份报告 / 全文」这类字样（违反「只改受影响章节」）

退出码: 0 通过 / 1 硬项失败 / 2 输入或调用错误
"""

import argparse
import json
import re
import sys

# Windows 控制台默认 GBK，✓/✗ 会 UnicodeEncodeError；统一按 UTF-8 输出（stderr 同理，argparse 用法提示也走它）
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# arguments 三档一律 3：论点个数固定，不随档位变（H3b 管草案登记数、H9 管裁决后存活数）
TIERS = {
    "精简": {"rounds": 1, "attacks": 2, "cover": 1, "final": False, "arguments": 3},
    "标准": {"rounds": 2, "attacks": 3, "cover": 2, "final": True, "arguments": 3},
    "完整": {"rounds": 3, "attacks": 5, "cover": 2, "final": True, "arguments": 3},
}

LINK_ENUM = {"事实前提", "机制", "中间结果", "最终影响", "评价标准", "辩题结论",
             "证据", "概念", "比较", "语言", "结构"}
ACTION_ENUM = {"修补", "换证据", "改判准", "让步删点", "拒绝并说明"}
REAL_ACTION = ACTION_ENUM - {"拒绝并说明"}
RESULT_ENUM = {"存活", "修补后存活", "降级", "删除"}
SEVERITY_ENUM = {"致命", "重要", "次要"}
ALIVE_ENUM = {"存活", "修补后存活"}
# 讨论轨（【讨论】）：质疑不一定针对某个论点，允许打判准或全局
DISC_TARGET_EXTRA = {"判准", "全局"}
DISC_RESULT_ENUM = {"成立", "不成立"}
REWRITE_RE = re.compile(r"全篇|整份报告|全文重写|重写一遍|推倒重来")
PREDICT_RE = re.compile(r"对方(会|可能|或许|一定|大概)|反方(会|可能|或许|一定|大概)")
SRC_REF_RE = re.compile(r"\[\d+(?:\s*,\s*\d+)*\]")

HARD_FAIL = []
WARN = []


def s(v):
    return "" if v is None else str(v).strip()


def check_rounds(data, tier, name):
    rounds = data.get("rounds")
    if not isinstance(rounds, list):
        return []
    if len(rounds) < tier["rounds"]:
        line = f"H2 攻防轮数 {len(rounds)}（下限 {tier['rounds']}）"
        print(f"  ✗ {line}")
        HARD_FAIL.append(line)
    else:
        print(f"  ✓ H2 攻防轮数 {len(rounds)}（下限 {tier['rounds']}）")

    if tier["final"]:
        fin = s(data.get("opponent_final"))
        if len(fin) < 20:
            line = "H2b 缺对手判决陈述（opponent_final）"
            print(f"  ✗ {line}")
            HARD_FAIL.append(line)
        else:
            print(f"  ✓ H2b 对手判决陈述 {len(fin)} 字")
    return rounds


def collect(rounds):
    attacks, defenses = [], []
    for i, rd in enumerate(rounds, 1):
        n = rd.get("n", i) if isinstance(rd, dict) else i
        for a in (rd.get("attacks") or []) if isinstance(rd, dict) else []:
            if isinstance(a, dict):
                a = dict(a)
                a["_round"] = n
                attacks.append(a)
        for d in (rd.get("defenses") or []) if isinstance(rd, dict) else []:
            if isinstance(d, dict):
                d = dict(d)
                d["_round"] = n
                defenses.append(d)
    return attacks, defenses


def check_attacks(attacks, arg_ids, tier):
    seen = set()
    for a in attacks:
        aid = s(a.get("id")) or f"第{a['_round']}轮·无名"
        tgt = s(a.get("target"))
        link = s(a.get("link"))
        sev = s(a.get("severity"))
        bad = []
        if not s(a.get("id")):
            bad.append("缺编号")
        elif aid in seen:
            bad.append(f"编号重复 {aid}")
        seen.add(aid)
        if tgt not in arg_ids:
            bad.append(f"目标论点 {tgt or '空'} 不在 arguments 里")
        if link not in LINK_ENUM:
            bad.append(f"环节 {link or '空'} 不合法")
        if sev not in SEVERITY_ENUM:
            bad.append(f"严重程度 {sev or '空'} 不合法")
        for k, label in (("claim", "攻击主张"), ("basis", "依据"), ("demand", "最低修补要求")):
            if not s(a.get(k)):
                bad.append(f"缺{label}")
        if bad:
            line = f"H3 攻击 {aid}：{'；'.join(bad)}"
            print(f"  ✗ {line}")
            HARD_FAIL.append(line)

    if len(attacks) < tier["attacks"]:
        line = f"H4 攻击总数 {len(attacks)}（下限 {tier['attacks']}）"
        print(f"  ✗ {line}")
        HARD_FAIL.append(line)
    else:
        print(f"  ✓ H4 攻击总数 {len(attacks)}（下限 {tier['attacks']}）")


def attack_field(attacks, key):
    out = set()
    for a in attacks:
        t = s(a.get(key))
        if t:
            out.add(t)
    return out


def check_defenses(defenses, attack_ids, attacks):
    by_attack = {}
    for d in defenses:
        by_attack.setdefault(s(d.get("attack")), []).append(d)
        did = s(d.get("id")) or f"第{d['_round']}轮·无名"
        aid = s(d.get("attack"))
        action = s(d.get("action"))
        bad = []
        if not aid or aid not in attack_ids:
            bad.append(f"对应攻击 {aid or '空'} 不存在")
        if action not in ACTION_ENUM:
            bad.append(f"处理动作 {action or '空'} 不合法")
        if len(s(d.get("detail"))) < 8:
            bad.append("具体怎么改 为空或过短")
        if not s(d.get("cost")):
            bad.append("缺代价说明（没让步也要写「无」）")
        if bad:
            line = f"H6 修补 {did}：{'；'.join(bad)}"
            print(f"  ✗ {line}")
            HARD_FAIL.append(line)

    missing = sorted(aid for aid in attack_ids if not by_attack.get(aid))
    line = f"H5 未被回应的攻击 {missing if missing else '无'}"
    if missing:
        print(f"  ✗ {line}")
        HARD_FAIL.append(line)
    else:
        print(f"  ✓ {line}")

    # H7 致命攻击必须真改
    tight = []
    for a in attacks:
        if s(a.get("severity")) != "致命":
            continue
        acts = {s(d.get("action")) for d in by_attack.get(s(a.get("id")), [])}
        if not (acts & REAL_ACTION):
            tight.append(s(a.get("id")) or "无名")
    line = f"H7 致命攻击未真改 {tight if tight else '无'}"
    if tight:
        print(f"  ✗ {line}")
        HARD_FAIL.append(line)
    else:
        print(f"  ✓ {line}")


def check_verdicts(verdicts, arg_ids, tier):
    seen = set()
    for v in verdicts:
        tgt = s(v.get("target"))
        res = s(v.get("result"))
        bad = []
        if tgt not in arg_ids:
            bad.append(f"裁决目标 {tgt or '空'} 不在 arguments 里")
        elif tgt in seen:
            bad.append(f"裁决目标重复 {tgt}")
        seen.add(tgt)
        if res not in RESULT_ENUM:
            bad.append(f"结果 {res or '空'} 不合法")
        if not s(v.get("reason")):
            bad.append("缺理由")
        if bad:
            line = f"H8 裁决 {tgt or '空'}：{'；'.join(bad)}"
            print(f"  ✗ {line}")
            HARD_FAIL.append(line)

    missing = sorted(arg_ids - seen)
    line = f"H8b 未裁决的论点 {missing if missing else '无'}"
    if missing:
        print(f"  ✗ {line}")
        HARD_FAIL.append(line)
    else:
        print(f"  ✓ {line}")

    alive = [t for t in seen if s(next((v["result"] for v in verdicts
                                        if s(v.get("target")) == t), "")) in ALIVE_ENUM]
    line = (f"H9 存活论点 {len(alive)} 个（{', '.join(sorted(alive))}）"
            f" / 需要 ≥ {tier['arguments']}")
    if len(alive) >= tier["arguments"]:
        print(f"  ✓ {line}")
    else:
        print(f"  ✗ {line}（论点固定 3 个，三档一致：回第二步补料或改结构，不许硬凑、也不许把删掉的论点换名字塞回来）")
        HARD_FAIL.append(f"H9 存活论点 {len(alive)} 个 < {tier['arguments']}")
    return alive


def discussion_list(data):
    """讨论轨可写成 discussion 或 discussions，多个轮的数组或单轮对象都接受。"""
    for key in ("discussion", "discussions"):
        v = data.get(key)
        if isinstance(v, list) and v:
            return list(v)
        if isinstance(v, dict) and v:
            return [v]
    return []


def check_discussions(discs, arg_ids):
    """H11–H14：用户标【讨论】后追加的对抗轮。不计入轮数与攻击总数下限。"""
    if not discs:
        print("  ✓ H11 无讨论轨（用户未标【讨论】）")
        return
    seen_n = set()
    for i, d in enumerate(discs, 1):
        if not isinstance(d, dict):
            line = f"H11 讨论轮 {i} 不是对象"
            print(f"  ✗ {line}")
            HARD_FAIL.append(line)
            continue
        n = d.get("n", i)
        trig = s(d.get("trigger"))
        atks = [a for a in (d.get("attacks") or []) if isinstance(a, dict)]
        dfs = [x for x in (d.get("defenses") or []) if isinstance(x, dict)]
        vds = [x for x in (d.get("verdicts") or []) if isinstance(x, dict)]
        chg = [s(c) for c in (d.get("changed") or []) if s(c)]
        bad = []
        if n in seen_n:
            bad.append(f"轮号重复 {n}")
        seen_n.add(n)
        if not trig:
            bad.append("缺 trigger（用户的质疑 / 方向）")
        if not atks:
            bad.append("缺 attacks")
        if not dfs:
            bad.append("缺 defenses")
        if not vds:
            bad.append("缺 verdicts")
        if not chg:
            bad.append("缺 changed（改了哪一节）")
        if bad:
            line = f"H11 讨论轮 {n}：{'；'.join(bad)}"
            print(f"  ✗ {line}")
            HARD_FAIL.append(line)
        else:
            print(f"  ✓ H11 讨论轮 {n}：靶心「{trig[:18]}」攻击 {len(atks)} 条 / 回应 {len(dfs)} 条 / changed {len(chg)} 项")

        a_ids = []
        for a in atks:
            aid = s(a.get("id"))
            tgt = s(a.get("target"))
            link = s(a.get("link"))
            sev = s(a.get("severity"))
            b = []
            if not aid:
                b.append("缺编号")
            elif aid in a_ids:
                b.append(f"编号重复 {aid}")
            a_ids.append(aid)
            if tgt not in arg_ids and tgt not in DISC_TARGET_EXTRA:
                b.append(f"目标 {tgt or '空'} 不在 arguments 里，也不是 判准/全局")
            if link not in LINK_ENUM:
                b.append(f"环节 {link or '空'} 不合法")
            if sev not in SEVERITY_ENUM:
                b.append(f"严重程度 {sev or '空'} 不合法")
            for k, label in (("claim", "攻击主张"), ("basis", "依据"), ("demand", "最低修补要求")):
                if not s(a.get(k)):
                    b.append(f"缺{label}")
            if b:
                line = f"H12 讨论轮 {n} 攻击 {aid or '无名'}：{'；'.join(b)}"
                print(f"  ✗ {line}")
                HARD_FAIL.append(line)

        by_attack = {}
        for x in dfs:
            by_attack.setdefault(s(x.get("attack")), []).append(x)
            did = s(x.get("id")) or f"讨论轮{n}·无名"
            aid = s(x.get("attack"))
            action = s(x.get("action"))
            b = []
            if not aid or aid not in a_ids:
                b.append(f"对应攻击 {aid or '空'} 不存在")
            if action not in ACTION_ENUM:
                b.append(f"处理动作 {action or '空'} 不合法")
            if len(s(x.get("detail"))) < 8:
                b.append("具体怎么改 为空或过短")
            if not s(x.get("cost")):
                b.append("缺代价说明（没让步也要写「无」）")
            if b:
                line = f"H13 讨论轮 {n} 修补 {did}：{'；'.join(b)}"
                print(f"  ✗ {line}")
                HARD_FAIL.append(line)
        missing = [aid for aid in a_ids if aid and not by_attack.get(aid)]
        fatal = [s(a.get("id")) or "无名" for a in atks
                 if s(a.get("severity")) == "致命"
                 and not ({s(x.get("action")) for x in by_attack.get(s(a.get("id")), [])} & REAL_ACTION)]
        if missing or fatal:
            line = f"H13 讨论轮 {n}：未回应 {missing if missing else '无'}；致命未真改 {fatal if fatal else '无'}"
            print(f"  ✗ {line}")
            HARD_FAIL.append(line)
        else:
            print(f"  ✓ H13 讨论轮 {n}：每条攻击都有回应（含致命级真改）")

        seen_t = set()
        for v in vds:
            tgt = s(v.get("target"))
            res = s(v.get("result"))
            b = []
            if not tgt:
                b.append("缺裁决目标")
            elif tgt in seen_t:
                b.append(f"裁决目标重复 {tgt}")
            seen_t.add(tgt)
            if res not in DISC_RESULT_ENUM:
                b.append(f"结果 {res or '空'} 不合法（只取 成立/不成立）")
            if not s(v.get("reason")):
                b.append("缺理由")
            if b:
                line = f"H14 讨论轮 {n} 裁决 {tgt or '空'}：{'；'.join(b)}"
                print(f"  ✗ {line}")
                HARD_FAIL.append(line)
        no_verdict = [aid for aid in a_ids if aid and aid not in seen_t]
        if no_verdict:
            line = f"H14 讨论轮 {n}：未裁决的攻击 {no_verdict}"
            print(f"  ✗ {line}")
            HARD_FAIL.append(line)
        else:
            print(f"  ✓ H14 讨论轮 {n}：每条攻击都有裁决；changed {len(chg)} 项")

        for c in chg:
            if REWRITE_RE.search(c):
                WARN.append(f"S7 讨论轮 {n} 的 changed 出现「{c[:24]}」：讨论轮只许改受影响章节，不许重写全篇")


def check_md_purity(md_path):
    try:
        with open(md_path, encoding="utf-8") as f:
            lines = f.read().splitlines()
    except Exception as e:  # noqa: BLE001
        print(f"  ✗ 无法读取 md：{e}")
        return 2
    start = None
    for i, ln in enumerate(lines):
        if ln.startswith("#") and "论点体系" in ln:
            start = i
            break
    if start is None:
        WARN.append("H10 md 里没找到「论点体系」小节，跳过纯净检查")
        print("  ⚠ H10 未找到「论点体系」小节，跳过")
        return 0
    bad = []
    for ln in lines[start + 1:]:
        if ln.startswith("## "):
            break
        if PREDICT_RE.search(ln):
            bad.append(ln.strip()[:60])
    line = f"H10 §4 论点体系里预判反驳的句子 {len(bad)} 处"
    if bad:
        print(f"  ✗ {line}")
        for b in bad[:5]:
            print(f"      - {b}")
        HARD_FAIL.append(line)
    else:
        print(f"  ✓ {line}")
    return 0


def main():
    ap = argparse.ArgumentParser(description="双 Agent 对抗收敛记录预检")
    ap.add_argument("data", help="对抗记录 JSON（debate.json）")
    ap.add_argument("--md", help="报告 Markdown，用于检查 §4 是否预判反驳")
    ap.add_argument("--tier", default="标准", choices=list(TIERS))
    args = ap.parse_args()

    try:
        with open(args.data, encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:  # noqa: BLE001
        print(f"✗ 无法读取对抗记录 JSON：{e}")
        return 2

    tier = TIERS[args.tier]
    motion = s(data.get("motion")) or "（未填辩题）"
    print(f"== check_debate · 档位 {args.tier} · {motion} ==")

    # H1 头部与角色
    roles = data.get("roles") or {}
    proposer = s(roles.get("proposer"))
    opponent = s(roles.get("opponent"))
    judge = s(roles.get("judge"))
    fallback = bool(data.get("fallback"))
    bad = []
    if not s(data.get("motion")):
        bad.append("缺辩题")
    if not s(data.get("side")):
        bad.append("缺持方")
    for k, v in (("proposer", proposer), ("opponent", opponent), ("judge", judge)):
        if not v:
            bad.append(f"roles.{k} 为空")
    if not fallback and proposer and proposer == opponent:
        bad.append("主笔与对手是同一个 agent（若确为单 Agent 分饰，请把 fallback 设为 true）")
    line = f"H1 头部/角色 {'；'.join(bad) if bad else '完整'}"
    if bad:
        print(f"  ✗ {line}")
        HARD_FAIL.append(line)
    else:
        print(f"  ✓ {line}")

    rounds = check_rounds(data, tier, args.tier)
    attacks, defenses = collect(rounds)

    args_list = data.get("arguments") or []
    arg_ids = {s(a.get("id")) for a in args_list if isinstance(a, dict) and s(a.get("id"))}
    if not arg_ids:
        line = "H3 没有 arguments 列表（要先登记首轮草案的论点编号）"
        print(f"  ✗ {line}")
        HARD_FAIL.append(line)
    elif len(arg_ids) < tier["arguments"]:
        line = f"H3b 首轮草案登记论点 {len(arg_ids)} 个 < {tier['arguments']}（论点固定 3 个，三档一致）"
        print(f"  ✗ {line}")
        HARD_FAIL.append(line)
    else:
        print(f"  ✓ H3b 首轮草案登记论点 {len(arg_ids)} 个（{', '.join(sorted(arg_ids))}）")

    check_attacks(attacks, arg_ids, tier)
    check_defenses(defenses, attack_field(attacks, "id"), attacks)
    alive = check_verdicts(data.get("verdicts") or [], arg_ids, tier)
    check_discussions(discussion_list(data), arg_ids)

    # ---- 软项 ----
    targets = {s(a.get("target")) for a in attacks if s(a.get("target"))}
    if len(targets) < tier["cover"]:
        WARN.append(f"S1 攻击只覆盖 {len(targets)} 个论点（建议 ≥ {tier['cover']}）：只打一个点说明对手没尽责")
    untouched = sorted(arg_ids - targets)
    if untouched:
        WARN.append(f"S2 从未被攻击的论点：{untouched}")
    sevs = [s(a.get("severity")) for a in attacks]
    if sevs and set(sevs) == {"次要"}:
        WARN.append("S3 严重程度全是「次要」：这轮对抗没真打")
    if defenses:
        refuse = sum(1 for d in defenses if s(d.get("action")) == "拒绝并说明")
        if refuse * 2 > len(defenses):
            WARN.append(f"S4 「拒绝并说明」占 {refuse}/{len(defenses)}：修补不实，回看是否在硬顶")
    weak = [s(a.get("id")) for a in attacks
            if not SRC_REF_RE.search(s(a.get("basis"))) and "逻辑反驳" not in s(a.get("basis"))]
    if weak:
        WARN.append(f"S5 依据既无来源编号又没标「逻辑反驳」：{weak}")
    if s(data.get("tier")) and s(data.get("tier")) != args.tier:
        WARN.append(f"S6 记录档位「{s(data.get('tier'))}」与命令行 --tier {args.tier} 不一致")

    if args.md:
        rc = check_md_purity(args.md)
        if rc == 2:
            return 2

    print()
    if WARN:
        print("告警：")
        for w in WARN:
            print(f"  ⚠ {w}")
    if HARD_FAIL:
        print(f"\n✗ 硬项失败 {len(HARD_FAIL)} 项，先修再出文件")
        return 1
    print("\n✓ 对抗记录预检通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
