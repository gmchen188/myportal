"""
demo/index.html 的静态自检。

页面的脚本是内联在一个大 HTML 里的 —— 改错一个引号，
浏览器只会报 "go is not defined"，看不出是哪一行。
这个脚本把内联 JS 抽出来交给 node 做语法检查，
并做几项结构断言，让这类错误在提交前就暴露。

运行：python tools/check_demo.py
"""

from __future__ import annotations

import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HTML = ROOT / "demo" / "index.html"

PASS, FAIL = [], []


def check(name: str, ok: bool, detail: str = "") -> None:
    (PASS if ok else FAIL).append(name)
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f"  — {detail}" if detail and not ok else ""))


def main() -> int:
    if not HTML.exists():
        print("index.html 不存在")
        return 2
    src = HTML.read_text(encoding="utf-8")

    print("[1] 内联 JS 语法")
    m = re.search(r"<script>(.*)</script>", src, re.S)
    if not m:
        check("找到内联 script", False)
        return 1
    js = m.group(1)
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False, encoding="utf-8") as fh:
        fh.write(js)
        tmp = fh.name
    r = subprocess.run(["node", "--check", tmp], capture_output=True)
    err = (r.stdout + r.stderr).decode("utf-8", "ignore")
    check("内联 JS 通过 node --check", r.returncode == 0, err[:400])
    Path(tmp).unlink(missing_ok=True)

    print("\n[2] 外部依赖（必须为 0 —— 演示要能离线用）")
    ext = len(re.findall(r'https?://|cdn\.|<script[^>]+src=|<link[^>]+href=', src))
    check("无外部引用", ext == 0, f"{ext} 处")

    print("\n[3] 双语完整性")
    vt = re.search(r"const VT = \{(.*?)\n\};", src, re.S)
    ot = re.search(r"const OT = \{(.*?)\n\};", src, re.S)
    for label, blk in (("VT", vt), ("OT", ot)):
        if not blk:
            check(f"{label} 字符串包存在", False)
            continue
        body = blk.group(1)
        entries = re.findall(r'"([a-zA-Z0-9._]+)"\s*:\s*\{zh:', body)
        missing = []
        for e in entries:
            seg = re.search(r'"' + re.escape(e) + r'"\s*:\s*\{(.*?)\},', body, re.S)
            if seg and 'en:' not in seg.group(1):
                missing.append(e)
        check(f"{label} 共 {len(entries)} 条且全部含 en", not missing, f"缺 en: {missing[:5]}")

    # VULNS 每条记录的每个多语言字段都要有 zh + en
    vul = re.search(r"const VULNS = (\[.*?\]);\n", src, re.S)
    if vul:
        import json

        try:
            arr = json.loads(vul.group(1))
        except Exception as exc:  # noqa: BLE001
            check("VULNS 是合法 JSON", False, str(exc)[:200])
            arr = []
        bad = []
        for rec in arr:
            for k, v in rec.items():
                # vector 是 CVSS 向量（AV/AC/PR…），不是可翻译文案 —— 不能按文案校验
                if k == "vector":
                    continue
                if isinstance(v, dict) and ("zh" not in v or "en" not in v):
                    bad.append((rec.get("id"), k))
        check(f"VULNS {len(arr)} 条的多语言字段齐全", not bad, str(bad[:5]))
        # CVSS 向量的八个分量必须齐全
        vbad = [r.get("id") for r in arr
                if set(r.get("vector", {})) != {"AV", "AC", "PR", "UI", "S", "C", "I", "A"}]
        check("每条记录的 CVSS 向量八分量齐全", not vbad, str(vbad[:5]))
        # 每条记录的向量与资产都要有
        incomplete = [r.get("id") for r in arr
                      if not r.get("vector") or not r.get("asset") or not r.get("cvss")]
        check("每条记录都有 vector / asset / cvss", not incomplete, str(incomplete[:5]))
    else:
        check("VULNS 数据存在", False)

    print("\n[4] 关键视图与挂钩")
    for key in ("VIEWS.ot", "VIEWS.vuln", "VIEWS.it", "VIEWS.topo"):
        check(f"{key} 已定义", f"{key}=" in src)
    for fn in ("purdueChart", "sankeyChart", "itotChart", "dfdChart", "vulnMatrix",
               "otGeometrySelfCheck"):
        check(f"{fn}() 已实现", f"function {fn}(" in src)
    for hook in ('q("cPurdue")', 'q("cSankey")', 'q("cItot")', 'q("cDfd")', 'q("cVulnMx")',
                 'q("impDrop")', 'q("exGen")'):
        check(f"{hook} 已接入渲染", hook in src)

    print("\n[4b] UR 子模块注册表")
    urm = re.search(r"const URM = (\{.*?\n\})\s*;", src, re.S)
    if urm:
        import json as _json

        try:
            u = _json.loads(urm.group(1))
            check(f"URM {len(u['modules'])} 个子模块", len(u["modules"]) > 0)
            # 组计数必须能从数据算出来，不能两处不一致
            counts = {}
            for m in u["modules"]:
                counts[m["g"]] = counts.get(m["g"], 0) + 1
            mismatch = [g["id"] for g in u["groups"] if counts.get(g["id"], 0) == 0]
            check("每个组都有子模块", not mismatch, str(mismatch))
            # 每个子模块必须有 zh + en 的名称与说明
            bad = [m["id"] for m in u["modules"]
                   if not (m["n"].get("zh") and m["n"].get("en")
                           and m["p"].get("zh") and m["p"].get("en"))]
            check(f"{len(u['modules'])} 个子模块的名称/说明均含中英", not bad, str(bad[:5]))
            # 列与记录数必须一致
            bad2 = [m["id"] for m in u["modules"]
                    if any(len(r) != len(m["cols"]) for r in m["rows"])]
            check("每个子模块的记录列数与表头一致", not bad2, str(bad2[:5]))
            # 每个子模块都要注册独立路由
            route = re.search(r"URM\.modules\.forEach", src)
            check("子模块按 urm:<id> 注册独立路由", route is not None)
        except Exception as exc:  # noqa: BLE001
            check("URM 是合法 JSON", False, str(exc)[:200])
    else:
        check("URM 注册表存在", False)

    print("\n[4d] 顶栏语言切换")
    check("顶栏有 .lang-tgl 双语切换器", 'class="lang-tgl"' in src)
    check("切换器有中/EN 两段",
          'data-lang="zh-CN"' in src and 'data-lang="en-US"' in src)
    # 位置要求：在主题按钮之前
    ti = src.find('id="langTgl"')
    th = src.find('id="themeBtn"')
    check("语言切换在深色/浅色按钮之前", ti > 0 and th > 0 and ti < th,
          f"langTgl@{ti} themeBtn@{th}")
    # 登录页与顶栏必须共用同一个切换入口
    check("登录页与顶栏共用 setLang()",
          "function setLang(" in src
          and '.lang-switch button, .lang-tgl button' in src)
    check("syncLangButtons() 同步两处状态", "function syncLangButtons()" in src)
    # 移动端不能横向溢出
    check("窄屏收起租户名（避免顶栏溢出）",
          ".tsw-btn #tswName{display:none}" in src)

    print("\n[4c] 资产导入 / 导出")
    for fn in ("assetValidate", "assetSuggestMapping", "assetSplit",
               "assetExportRows", "assetDoExport", "assetDoImport",
               "assetRenderImport", "assetRenderExportPreview", "assetDownload"):
        check(f"{fn}() 已实现", f"function {fn}(" in src)
    check("VIEWS.assetImport 已定义", "VIEWS.assetImport=" in src)
    check("VIEWS.assetExport 已定义", "VIEWS.assetExport=" in src)
    # 关键缺陷：c.indexOf(c) 永远返回 -1
    check("没有 c.indexOf(c) 这种死代码", "c.indexOf(c)" not in src)
    check("资产导入路由已登记", 'assetImport:["资产导入"' in src)
    check("资产导出路由已登记", 'assetExport:["资产导出"' in src)

    print("\n[5] 视图数据源引用的字段都存在")
    # VULNS 里的字段必须与渲染代码用的一致
    for field in ("fixText", "impact", "alt", "ur", "status", "due", "patch", "count"):
        check(f"VULNS 渲染使用 {field}", f"v.{field}" in src or f"sel.{field}" in src)

    print(f"\n{'=' * 58}")
    print(f"通过 {len(PASS)} 项，失败 {len(FAIL)} 项")
    if FAIL:
        for f in FAIL:
            print(f"  FAILED: {f}")
        return 1
    print("demo 自检通过。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
