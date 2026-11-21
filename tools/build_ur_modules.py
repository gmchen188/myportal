# -*- coding: utf-8 -*-
"""
把 UR 子模块注册表注入 demo/index.html，并生成追溯页与子模块页。

用法：python tools/build_ur_modules.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HTML = ROOT / "demo" / "index.html"
sys.path.insert(0, str(Path(__file__).parent))

from ur_modules_data import build  # noqa: E402

DATA = build()

# ══════════════════════════════════════════════════════════════
# 1) 注入数据（作为 JS 常量）
# ══════════════════════════════════════════════════════════════
DATA_JS = (
    "/* ══════════════════════════════════════════════════════════════\n"
    "   UR 条款追溯 —— 子模块注册表\n"
    "   由 tools/ur_modules_data.py 生成。组计数也来自数据，不是手写死的。\n"
    "   ══════════════════════════════════════════════════════════════ */\n"
    "const URM = " + json.dumps(DATA, ensure_ascii=False, indent=1) + ";\n"
    "const URM_BY_ID = Object.fromEntries(URM.modules.map(m=>[m.id,m]));\n"
    "const URM_GROUPS = URM.groups;\n"
    "let URG = null;   // 当前展开的组（null = 总览）\n\n"
)

# ══════════════════════════════════════════════════════════════
# 2) 追溯页 + 子模块页
# ══════════════════════════════════════════════════════════════
VIEWS_JS = r'''
/* ══════════════════════════════════════════════════════════════
   UR 条款追溯：组 → 子模块 → 独立页面
   ══════════════════════════════════════════════════════════════ */
const URM_CELL_TONE={
  "在基线内":"ok","符合":"ok","通过":"ok","全部拦截":"ok","成立":"ok","生效":"ok","已实施":"ok",
  "已批准":"ok","已评估":"ok","已执行":"ok","已演练":"ok","已关闭":"ok","已生成":"ok","已回收":"ok",
  "已收敛":"ok","已核验":"ok","正常":"ok","成功":"ok","有效":"ok","已确认":"ok","已完成":"ok",
  "已启用":"ok","已达标":"ok","达标":"ok","启用":"ok","在用":"ok","在管":"ok","在保":"ok","在支持":"ok",
  "未发现同源":"ok","未发现":"ok","恢复成功":"ok","校验值一致":"ok","差异 0":"ok","已录制":"ok","已恢复":"ok",
  "一致":"ok",
  "关注":"medium","整改中":"medium","生效中":"medium","待复核":"medium","待执行":"medium","待回收":"medium",
  "不符合":"medium","缺口":"medium","待整改":"medium","停用":"medium","已停用":"medium","开放":"medium",
  "部分成立":"medium","部分":"medium","待收敛":"medium","待核验":"medium","待确认":"medium","待定":"medium",
  "中":"medium","中危":"medium","已撤销":"medium","待接入":"medium","未配置":"medium",
  "严重":"crit","未通过":"crit","失败":"crit","恢复失败":"crit","发现 2 例同源":"crit","过期":"crit",
  "未完成":"crit","高":"high","高危":"high"
};
const URM_ST={ok:{zh:"已核验",en:"Verified",c:"ok"},
              warn:{zh:"需关注",en:"Needs Attention",c:"medium"},
              crit:{zh:"不达标",en:"Not Met",c:"crit"}};
const URM_CL={
  "3.1":{zh:"变更管理",en:"Change Management"},
  "3.2":{zh:"软件更新",en:"Software Update"},
  "3.3":{zh:"防火墙管理",en:"Firewall Management"},
  "3.4":{zh:"恶意软件防护管理",en:"Malware Protection Management"},
  "3.5":{zh:"访问控制管理",en:"Access Control Management"},
  "3.6":{zh:"保密信息管理",en:"Classified Information Management"},
  "3.7":{zh:"远程访问管理",en:"Remote Access Management"},
  "3.8":{zh:"移动及便携式设备管理",en:"Mobile & Portable Device Management"},
  "3.9":{zh:"安全异常检测",en:"Security Anomaly Detection"},
  "3.10":{zh:"安全功能验证",en:"Security Function Validation"},
  "3.11":{zh:"事件响应计划",en:"Incident Response Plan"},
  "3.12":{zh:"恢复计划",en:"Recovery Planning"}
};

function urmBadge(st){
  const s=URM_ST[st]||URM_ST.ok;
  return `<span class="bdg b-${s.c}">${L(s)}</span>`;
}

/* ── 总览 / 组展开 ─────────────────────────────────────────── */
VIEWS.urtrace=()=>{
  const total=URM.modules.length;
  if(URG){
    const g=URM_GROUPS.find(x=>x.id===URG);
    const mods=URM.modules.filter(m=>m.g===URG);
    return `<div class="card" style="margin-bottom:16px">
      <div class="card-h"><h3>${L(g.n)}</h3>
        <span class="sub">${L(g.d)}</span>
        <div class="right">
          <a class="link" href="#" data-go="urtrace" data-back="1">← ${LANG==="zh-CN"?"返回总览":"Back to Overview"}</a>
        </div></div>
      <div class="muted sm" style="margin-bottom:12px">
        ${LANG==="zh-CN"?`本组共 ${mods.length} 个子模块，每个子模块有独立页面。`:
                    `${mods.length} sub-modules in this group, each with its own page.`}
      </div>
      <div class="grid g-3" style="gap:12px">
        ${mods.map(m=>`<a href="#" data-go="urm:${m.id}" class="urmod">
          <div style="display:flex;align-items:center;gap:8px;margin-bottom:6px">
            <b style="font-size:13px">${L(m.n)}</b>
            <span class="bdg b-neutral mono">${m.cl}</span>
            ${urmBadge(m.st)}
          </div>
          <div class="muted sm" style="line-height:1.55">${L(m.p)}</div>
          <div class="urmod-f">
            <span>${LANG==="zh-CN"?`${m.rows.length} 条记录`:`${m.rows.length} records`}</span>
            <span>${LANG==="zh-CN"?`${m.ev} 条证据`:`${m.ev} evidence`}</span>
            <span class="urmod-go">${LANG==="zh-CN"?"打开 →":"Open →"}</span>
          </div>
        </a>`).join("")}
      </div>
    </div>`;
  }
  return `<div class="card" style="margin-bottom:16px">
    <div class="card-h"><h3>${LANG==="zh-CN"?"UR 条款追溯":"UR Clause Traceability"}</h3>
      <span class="sub">${LANG==="zh-CN"?`IACS UR E26（Rev.1）/ E27 / E22 · ${URM_GROUPS.length} 组共 ${total} 个台账模块`:
                                      `IACS UR E26 (Rev.1) / E27 / E22 · ${total} register modules in ${URM_GROUPS.length} groups`}</span>
      <div class="right"><a class="link" href="#" data-go="ur12">${LANG==="zh-CN"?"12 项合规模块 →":"12 UR Compliance Modules →"}</a></div></div>
    <div class="grid g-3" style="gap:12px">
      ${URM_GROUPS.map(g=>{
        const mods=URM.modules.filter(m=>m.g===g.id);
        const ev=mods.reduce((a,m)=>a+m.ev,0);
        const rows=mods.reduce((a,m)=>a+m.rows.length,0);
        const bad=mods.filter(m=>m.st!=="ok").length;
        return `<a href="#" data-grp="${g.id}" class="urgrp">
          <div style="display:flex;align-items:center;gap:9px;margin-bottom:7px">
            <b style="font-size:13.5px">${L(g.n)}</b>
            <span class="bdg b-info">${mods.length} ${LANG==="zh-CN"?"个模块":"modules"}</span>
            ${bad?`<span class="bdg b-medium">${bad} ${LANG==="zh-CN"?"需关注":"need attention"}</span>`:""}
          </div>
          <div class="muted sm" style="line-height:1.55">${L(g.d)}</div>
          <div class="urgrp-f">
            <span>${LANG==="zh-CN"?`${rows} 条记录`:`${rows} records`}</span>
            <span>${ev} ${LANG==="zh-CN"?"条证据":"evidence"}</span>
            <span class="urgrp-go">${LANG==="zh-CN"?"展开子模块 →":"Expand →"}</span>
          </div>
        </a>`;}).join("")}
    </div>
    <div class="foot"><b>${LANG==="zh-CN"?"元数据驱动":"Metadata Driven"}</b><div>${
      LANG==="zh-CN"?"一个模块注册项同时生成三样东西：Pydantic 校验 Schema、FastAPI CRUD 路由、前端表单与表格。<b>新增一个台账模块 = 加一段注册代码，前端零改动。</b>":
                    "One registration entry generates three things: a Pydantic validation schema, FastAPI CRUD routes, and the front-end form and table. <b>Adding a register module means adding a registration entry — zero front-end change.</b>"}</div></div>
  </div>`;
};

/* ── 子模块独立页 ───────────────────────────────────────────── */
function urmPage(m){
  const g=URM_GROUPS.find(x=>x.id===m.g);
  const cl=URM_CL[m.cl];
  const others=URM.modules.filter(x=>x.g===m.g && x.id!==m.id);
  return `
  <div class="card" style="margin-bottom:16px">
    <div class="card-h">
      <h3>${L(m.n)}</h3>
      <span class="bdg b-neutral mono">${m.cl}</span>
      <span class="bdg b-info">${L(g.n)}</span>
      <div class="right">${urmBadge(m.st)}
        <a class="link" href="#" data-go="urtrace" style="margin-left:12px">${LANG==="zh-CN"?"← 返回追溯":"← Back"}</a></div>
    </div>
    <div class="muted" style="font-size:12.5px;line-height:1.7;max-width:960px">${L(m.p)}</div>
  </div>

  <div class="grid g-4" style="margin-bottom:16px">
    ${kpi("urm.k1",m.rows.length,LANG==="zh-CN"?"条":"records","","urm.d1","info","",t("demo"),"flat")}
    ${kpi("urm.k2",m.ev,LANG==="zh-CN"?"条":"evidence","","urm.d2","","",t("demo"),"flat")}
    ${kpi("urm.k3",m.cl,"","urm.d3","","",t("demo"),"flat")}
    ${kpi("urm.k4",others.length,LANG==="zh-CN"?"个":"siblings","","urm.d4","warn","",t("demo"),"flat")}
  </div>

  <div class="grid g-21">
    <div class="card">
      <div class="card-h"><h3>${LANG==="zh-CN"?"台账记录":"Register Records"}</h3>
        <span class="sub">${m.rows.length} ${LANG==="zh-CN"?"条":"records"}</span>
        <div class="right"><span class="bdg b-neutral">${t("demo")}</span></div></div>
      <div class="tbl-wrap"><table><thead><tr>
        ${m.cols.map(c=>`<th>${LANG==="zh-CN"?c[1]:c[2]}</th>`).join("")}
      </tr></thead><tbody>
        ${m.rows.map(r=>`<tr>${r.map((cell,ci)=>{
          const c=m.cols[ci];
          // 单元格值自带 zh / en；色调按中文值判定，显示按当前语言
          const zh=(cell&&typeof cell==="object")?cell.zh:String(cell);
          const txt=(cell&&typeof cell==="object")
            ?((cell[LANG_KEY()]!==undefined)?cell[LANG_KEY()]:cell.zh)
            :String(cell);
          if(c[0]==="st"||c[0]==="res"){
            const st=URM_ST[zh];
            const tone=st?st.c:(URM_CELL_TONE[zh]||"ok");
            return `<td><span class="bdg b-${tone}">${txt}</span></td>`;
          }
          return `<td>${txt}</td>`;
        }).join("")}</tr>`).join("")}
      </tbody></table></div>
    </div>

    <div class="card">
      <div class="card-h"><h3>${LANG==="zh-CN"?"条款与证据":"Clause & Evidence"}</h3></div>
      <div class="vdetail-b" style="padding:16px">
        <div class="vrow"><div class="k">${LANG==="zh-CN"?"UR 条款":"UR Clause"}</div><div class="v">
          <code>${m.cl}</code> ${cl?L(cl):""}</div></div>
        <div class="vrow"><div class="k">${LANG==="zh-CN"?"所属分组":"Group"}</div><div class="v">${L(g.n)}</div></div>
        <div class="vrow"><div class="k">${LANG==="zh-CN"?"检验须提交":"Survey evidence"}</div><div class="v">
          <div class="rem">${L(m.req)}</div></div></div>
        <div class="vrow"><div class="k">${LANG==="zh-CN"?"证据条目":"Evidence items"}</div><div class="v">
          <b class="mono">${m.ev}</b> ${LANG==="zh-CN"?"条可导出证据":"exportable evidence items"}</div></div>
        <div class="vrow"><div class="k">${LANG==="zh-CN"?"操作审计":"Audit"}</div><div class="v">
          ${LANG==="zh-CN"?"本模块的每次新增、修改与导出都会留痕；敏感读取同样记录。":
                      "Every create, edit and export in this module is recorded; sensitive reads are recorded too."}</div></div>
        <div class="vrow"><div class="k">${LANG==="zh-CN"?"同组其他子模块":"Sibling modules"}</div><div class="v">
          ${others.map(o=>`<a class="link" href="#" data-go="urm:${o.id}" style="display:block;margin-bottom:4px">${L(o.n)} <span class="mono muted">${o.cl}</span></a>`).join("")}</div></div>
      </div>
      <div class="foot"><b>${LANG==="zh-CN"?"导出":"Export"}</b><div>${
        LANG==="zh-CN"?"该模块可单独导出为检验证据包 —— 台账快照 + 审计日志自动装配。":
                    "This module can be exported on its own as survey evidence — the register snapshot and audit trail are assembled automatically."}</div></div>
    </div>
  </div>`;
}
'''

# ══════════════════════════════════════════════════════════════
# 3) 字符串包（中英）
# ══════════════════════════════════════════════════════════════
STRINGS = r'''const URM_STR = {
  "urm.k1":{zh:"台账记录条数",en:"Register records"},
  "urm.k2":{zh:"可导出证据条目",en:"Exportable evidence items"},
  "urm.k3":{zh:"对应 UR 条款",en:"Mapped UR clause"},
  "urm.k4":{zh:"同组子模块",en:"Sibling modules in group"},
  "urm.d1":{zh:"台账当前记录的条目",en:"rows currently in the register"},
  "urm.d2":{zh:"可单独导出为检验证据",en:"exportable as survey evidence"},
  "urm.d3":{zh:"对应 IACS UR 条款",en:"maps to an IACS UR clause"},
  "urm.d4":{zh:"同组其他子模块",en:"other modules in this group"}
};
'''

CSS = '''
/* ── UR 条款追溯：组卡 / 子模块卡 ───────────────────────────── */
.urgrp{display:block;border:1px solid var(--border);border-radius:10px;padding:15px;
  background:var(--bg);color:inherit;text-decoration:none;transition:border-color .15s,box-shadow .15s}
.urgrp:hover{border-color:var(--c2);box-shadow:0 2px 10px rgba(30,58,138,.08)}
.urgrp-f,.urmod-f{display:flex;gap:14px;margin-top:11px;padding-top:9px;
  border-top:1px solid var(--border);font-size:11px;color:var(--muted-fg)}
.urgrp-go,.urmod-go{margin-left:auto;color:var(--c2);font-weight:700}
.urmod{display:block;border:1px solid var(--border);border-radius:10px;padding:15px;
  background:var(--bg);color:inherit;text-decoration:none;transition:border-color .15s,box-shadow .15s}
.urmod:hover{border-color:var(--c4);box-shadow:0 2px 10px rgba(5,150,105,.10)}
'''


def main() -> int:
    src = HTML.read_text(encoding="utf-8")

    # 数据注入
    if "const URM = " in src:
        i = src.index("/* ══════════════════════════════════════════════════════════════\n   UR 条款追溯 —— 子模块注册表")
        j = src.index("const URM_BY_ID")
        j = src.index("\n", src.index("let URG = null;", j)) + 1
        src = src[:i] + DATA_JS + src[j:]
        print("URM 数据已更新")
        # 字符串包也要跟着更新（首次注入时是与数据一起放的）
        if "const URM_STR = {" in src:
            a = src.index("const URM_STR = {")
            b = src.index("\n};", a) + 3
            src = src[:a] + STRINGS.strip() + src[b:]
    else:
        anchor = "/* ══════════════════════════════════════════════════════════════\n   国际化"
        assert anchor in src, "找不到注入锚点"
        src = src.replace(anchor, DATA_JS + STRINGS + anchor, 1)
        print("URM 数据已注入")

    # 视图替换 —— 必须可重复执行：先抹掉上次注入的块，再放新的
    MARK_A = "/* ══════════════════════════════════════════════════════════════\n   UR 条款追溯：组 → 子模块 → 独立页面"
    MARK_B = "VIEWS.ur12=()=>`"
    if MARK_A in src:
        i = src.index(MARK_A)
        j = src.index(MARK_B, i)
        src = src[:i] + VIEWS_JS.strip() + "\n\n" + src[j:]
    else:
        i = src.index("VIEWS.urtrace=()=>`")
        j = src.index(MARK_B, i)
        src = src[:i] + VIEWS_JS.strip() + "\n\n" + src[j:]

    # 路由：为每个子模块注册独立视图与标题
    ROUTE = r'''
/* ── 子模块独立路由：urm:<id> ───────────────────────────────── */
URM.modules.forEach(m=>{
  const key="urm:"+m.id;
  VIEWS[key]=()=>urmPage(m);
  // 标题在**渲染时**再算 —— 注册时算一次的话，切换语言后标题还停在旧语言
  TITLES[key]=null;   // 标记为动态标题，由 go() 解析
});
URM_TITLE_CACHE={};

/* 子模块标题按当前语言实时解析（注册时算一次会停在旧语言） */
function urmTitle(key){
  const m=URM_BY_ID[key.slice(4)];
  if(!m) return null;
  const g=URM_GROUPS.find(x=>x.id===m.g);
  const zh=LANG==="zh-CN";
  return [zh?m.n.zh:m.n.en,
          `${zh?"船舶网络安全和韧性计划":"Ship Cyber Security & Resilience Plan"} / ${zh?"UR 条款追溯":"UR Clause Traceability"} / ${zh?g.n.zh:g.n.en}`];
}
'''
    # 路由块必须可重复执行：先抹掉旧的，再放新的
    # 用明确的 END 哨兵来界定整块，**不要按长度切** ——
    # 按长度切过一次，把后面的 VIEWS.fleet 开头一起切掉了。
    RMARK = "/* ── 子模块独立路由：urm:<id> ───────────────────────────────── */"
    REMARK = "/* ── end 子模块独立路由 ─────────────────────────────────────── */"
    body = ROUTE.strip()
    if RMARK in src:
        i = src.index(RMARK)
        if REMARK in src[i:]:
            j = src.index(REMARK, i) + len(REMARK)
            src = src[:i] + src[j:]
        else:
            raise RuntimeError("找到了路由块但找不到结束哨兵 —— 拒绝猜测边界")
    anchor = "const VIEWS={};"
    assert anchor in src
    src = src.replace(anchor, anchor + "\n\n" + body + "\n" + REMARK + "\n", 1)

    # 样式
    css_anchor = "/* ── 审计日志 ─────────────────────────────────────────────── */"
    if ".urgrp{" not in src:
        assert css_anchor in src, "找不到 CSS 锚点"
        src = src.replace(css_anchor, CSS + "\n" + css_anchor, 1)

    HTML.write_text(src, encoding="utf-8")
    print(f"追溯页 + {DATA['total']} 个子模块独立页面已注入")
    return 0


if __name__ == "__main__":
    sys.exit(main())
