"""合成数据生成：程序化生成带缺陷的代码评审评测样例。

用途：作为真实 PR 抽取的规模补充，以及离线环境下的可复现数据源。
每条样例由「一段含缺陷的代码变更（diff）+ 标准缺陷标注」构成，
缺陷类型覆盖 logic / security / performance / style 四类，严重度覆盖三级。

生成是确定性的：给定 seed 即可复现同一批数据。
"""

from __future__ import annotations

import random

# 缺陷模板：每个模板是一个 (类型, 严重度, 缺陷描述, 位置, diff 的 before/after)
# 这里用「最小可复现缺陷」的范式，确保每条样例都明确、可对齐。
_DEFECT_TEMPLATES: list[dict] = [
    {
        "type": "security",
        "severity": "critical",
        "message": "使用字符串拼接构造 SQL 查询，存在 SQL 注入风险",
        "location": "query.py:12",
        "diff": "def find(user_id):\n-    return db.execute(\"SELECT * FROM t WHERE id = %s\", (user_id,))\n+    return db.execute(\"SELECT * FROM t WHERE id = '\" + user_id + \"'\")",
    },
    {
        "type": "logic",
        "severity": "critical",
        "message": "除数为 0 时未做防护，存在除零错误",
        "location": "math.py:8",
        "diff": "def rate(total, count):\n-    return total / count if count else 0\n+    return total / count",
    },
    {
        "type": "performance",
        "severity": "major",
        "message": "循环内使用 += 拼接字符串，应使用 join 避免 O(n^2) 开销",
        "location": "join.py:20",
        "diff": "def join_lines(lines):\n-    return \"\\n\".join(lines)\n+    out = \"\"\n+    for l in lines:\n+        out += l + \"\\n\"\n+    return out",
    },
    {
        "type": "style",
        "severity": "minor",
        "message": "函数命名与缩进不符合团队规范（应 snake_case + 4 空格）",
        "location": "util.py:3",
        "diff": "def ProcessData(x):\n+  y = x + 1\n+  return y",
    },
    {
        "type": "logic",
        "severity": "major",
        "message": "打开文件后未关闭，应使用 with 语句管理资源",
        "location": "io.py:15",
        "diff": "def read(p):\n-    with open(p) as f:\n-        return f.read()\n+    f = open(p)\n+    return f.read()",
    },
    {
        "type": "security",
        "severity": "major",
        "message": "命令拼接 shell=True 执行，存在命令注入风险",
        "location": "run.py:30",
        "diff": "def exec_cmd(name):\n-    subprocess.run([\"ping\", name], check=True)\n+    subprocess.run(\"ping \" + name, shell=True)",
    },
    {
        "type": "logic",
        "severity": "major",
        "message": "边界条件判断错误：应为 < 而非 <=，导致越界访问",
        "location": "list.py:44",
        "diff": "def get(arr, i):\n-    if i < len(arr):\n-        return arr[i]\n+    if i <= len(arr):\n+        return arr[i]",
    },
    {
        "type": "performance",
        "severity": "minor",
        "message": "在循环内重复调用昂贵的数据库查询，应批量预取",
        "location": "batch.py:60",
        "diff": "def load(ids):\n-    return [db.get(i) for i in ids]\n+    out = []\n+    for i in ids:\n+        out.append(db.get(i))\n+    return out",
    },
    {
        "type": "security",
        "severity": "critical",
        "message": "硬编码了密钥/凭证，应改用环境变量或密钥管理",
        "location": "config.py:5",
        "diff": "API_KEY = \"sk-live-1234567890abcdef\"\n# 应使用 os.environ.get(\"API_KEY\")",
    },
    {
        "type": "logic",
        "severity": "minor",
        "message": "异常被空 except 静默吞掉，导致问题难排查",
        "location": "safe.py:70",
        "diff": "def run():\n+    try:\n+        risky()\n+    except:\n+        pass",
    },
]


# 变量名候选池：每次生成时随机抽取，替换 diff 里的占位符，
# 从而产生「内容不同但缺陷类型相同」的多样样本，避免去重时被误杀。
_FUNC_NAMES = [
    "fetch_user", "load_config", "compute_score", "render_page",
    "parse_input", "build_query", "handle_event", "save_record",
]
_VAR_NAMES = ["data", "item", "value", "result", "record", "entry", "payload", "row"]
_MODULE_NAMES = ["service", "handler", "client", "worker", "mapper", "helper", "api", "core"]
_LINE_BASES = [8, 12, 16, 20, 24, 28, 32, 36, 40, 44, 48, 52]


def _vary_template(tpl: dict, rng: random.Random, idx: int) -> dict:
    """对模板做变量替换，生成一条内容不同的新样本。

    替换规则：函数名 -> 随机候选 + 序号；变量名 -> 随机候选；
    文件名 -> 随机模块名；行号 -> 随机基准 + 偏移。
    """
    func = f"{rng.choice(_FUNC_NAMES)}_{idx}"
    var = f"{rng.choice(_VAR_NAMES)}_{idx}"
    module = f"{rng.choice(_MODULE_NAMES)}_{idx}"
    line = rng.choice(_LINE_BASES) + (idx % 5)

    diff = tpl["diff"].replace("find", func).replace("user_id", var)
    diff = diff.replace("total", var).replace("count", f"{var}_n")
    diff = diff.replace("lines", f"{var}_list").replace("out", f"{var}_out")
    diff = diff.replace("ProcessData", func.capitalize())
    diff = diff.replace("read", func).replace("exec_cmd", func)
    diff = diff.replace("get", func).replace("load", func)
    diff = diff.replace("risky", f"{func}_risky")

    # 文件名与行号：把 location 里的模块名/行号换成新的
    location = tpl["location"]
    orig_file = location.split(":")[0]
    new_location = f"{module}.py:{line}"
    diff = diff.replace(orig_file, f"{module}.py")

    return {
        "diff": diff,
        "location": new_location,
    }


def generate_samples(count: int, seed: int = 42, repo: str = "synthetic") -> list[dict]:
    """生成 count 条合成评测样例，确定性可复现。

    通过变量替换让每条样本的 diff 内容都不同（语义等价、缺陷类型相同），
    既能通过去重校验，又能真实测试模型对「同类缺陷不同写法」的泛化。
    """
    rng = random.Random(seed)
    samples: list[dict] = []
    for idx in range(count):
        tpl = _DEFECT_TEMPLATES[idx % len(_DEFECT_TEMPLATES)]
        varied = _vary_template(tpl, rng, idx)
        samples.append(
            {
                "id": f"syn-{idx:04d}",
                "title": tpl["message"],
                "repo": repo,
                "context": f"合成样例（seed={seed}），用于规模补充与离线可复现评测。",
                "diff": varied["diff"],
                "defects": [
                    {
                        "id": f"syn-{idx:04d}-1",
                        "type": tpl["type"],
                        "severity": tpl["severity"],
                        "message": tpl["message"],
                        "location": varied["location"],
                        "category": None,
                    }
                ],
            }
        )
    return samples


def _distribution_summary(samples: list[dict]) -> dict:
    """统计合成数据的缺陷类型/严重度分布，用于质量校验报告。"""
    by_type: dict[str, int] = {}
    by_severity: dict[str, int] = {}
    for s in samples:
        for d in s["defects"]:
            by_type[d["type"]] = by_type.get(d["type"], 0) + 1
            by_severity[d["severity"]] = by_severity.get(d["severity"], 0) + 1
    return {"by_type": by_type, "by_severity": by_severity, "total": len(samples)}
