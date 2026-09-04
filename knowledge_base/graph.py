"""records.json -> NetworkX 图（6 节点 5 边）。

药物/组成于 边依赖「给药表」抽取，暂缓；本脚本先建核心图
（推荐决策/方案/分层/推荐等级/证据类别 5 节点 + 方案/适用于/等级/证据 4 边）。
"""
import json
import pickle
from pathlib import Path

import networkx as nx

RECORDS = Path("knowledge_base/records.json")
OUT = Path("knowledge_base/graph.gpickle")


def build():
    recs = json.loads(RECORDS.read_text(encoding="utf-8"))
    G = nx.MultiDiGraph()
    for i, r in enumerate(recs):
        dec = f"dec::{i}"
        G.add_node(dec, type="推荐决策", 来源页码=r["来源页码"])

        reg = f"reg::{r['方案']}"
        G.add_node(reg, type="方案", name=r["方案"])
        G.add_edge(dec, reg, rel="方案")

        strat = f"strat::{r['治疗阶段']}::{r['人群']}::{r['分层条件']}"
        G.add_node(strat, type="分层",
                   治疗阶段=r["治疗阶段"], 人群=r["人群"], 分层条件=r["分层条件"])
        G.add_edge(dec, strat, rel="适用于")

        if r["推荐等级"]:
            lv = f"level::{r['推荐等级']}"
            G.add_node(lv, type="推荐等级")
            G.add_edge(dec, lv, rel="等级")

        if r["证据类别"]:
            ev = f"ev::{r['证据类别']}"
            G.add_node(ev, type="证据类别")
            G.add_edge(dec, ev, rel="证据")

    with open(OUT, "wb") as f:
        pickle.dump(G, f)

    ntype = {}
    for n, d in G.nodes(data=True):
        ntype[d["type"]] = ntype.get(d["type"], 0) + 1
    print(f"nodes={G.number_of_nodes()} edges={G.number_of_edges()} -> {OUT}")
    print("节点类型:", ntype)


if __name__ == "__main__":
    build()
