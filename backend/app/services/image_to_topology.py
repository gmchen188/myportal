"""
图片 → 拓扑图（AI 识别）。

## 这条路为什么绕到 networktopology 去

「导入一张架构图，AI 还原成可编辑的 draw.io 图」的能力在 networktopology
那个应用里（它有 VLM 凭据、画图规范和形状库）。myPortal 这边**没有**模型
配置，也不该再实现一遍 —— 画图规范（样式表、区域/设备的坐标约定、图标名）
都在 networktopology 的工具链里，自己写提示词只会得到质量更差的图。

所以这里做的是**代理**：把图片转给 networktopology 的 `/api/chat`，把它
生成的 XML 取回来。

## 协议（实测，不是猜的）

`POST {NT_BASE}/api/chat`

    {"messages":[{"id":"...","role":"user","parts":[
        {"type":"text","text":"..."},
        {"type":"file","mediaType":"image/png","filename":"a.png",
         "url":"data:image/png;base64,..."}]}]}

响应是 **SSE 流**（`text/event-stream`），每行 `data: {json}`：

    {"type":"text-delta","id":"0","delta":"..."}
    {"type":"tool-input-available","toolCallId":"...","toolName":"display_diagram",
     "input":{"xml":"<mxStyle .../><mxCell .../>"}}

**模型画完图后调 `display_diagram` 工具，XML 就在那个工具调用的 `input.xml` 里。**
取**最后一个** —— 模型可能改好几次，后一次才是完整的。

`/api/chat` 不需要登录态（access code 没配就不校验），服务端直调没问题。

## 返回的 XML 是什么格式

**片段**：`<mxStyle .../>` 和 `<mxCell .../>` 的序列，**没有** `<mxfile>` 包装。

这正好和 myPortal 存的一模一样（`Topology.xml` 存的就是这种片段，
由 `services/topology_parse.py` 解析）—— 所以**不用包装**，直接存。
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass

# networktopology 的地址。
#
# 默认指向本机的 dev 端口；生产部署时用环境变量指到实际托管它的地址。
NT_BASE = os.getenv("MP_NT_BASE_URL", "http://127.0.0.1:6002/networktopology").rstrip("/")

# 有配 access code 的话必须带上（networktopology 的 ACCESS_CODE_LIST）。
NT_ACCESS_CODE = os.getenv("MP_NT_ACCESS_CODE", "")

# 图生图要跑一会儿（模型读图 + 画图 + 改图），给足时间。
DEFAULT_TIMEOUT = int(os.getenv("MP_NT_IMAGE_TIMEOUT", "240"))

# 提示词：明确要求调用工具，并把图里的名字原样保留。
#
# **要提工具名** —— 不提的话模型会用文字描述这张图（实测过：它会说
# 「这张截图里画布是空白的」），而不是把图画出来。
DEFAULT_PROMPT = (
    "请根据这张网络拓扑截图生成一张可编辑的 draw.io 拓扑图。\n"
    "要求：\n"
    "1. 保留截图里所有的区域名与设备名，一个字都不要改写或翻译；\n"
    "2. 区域用方框表示，设备用图标表示，连线保留；\n"
    "3. 直接把图调用 display_diagram 工具画出来。"
)


class ImageToTopologyError(Exception):
    """图片转拓扑失败。`detail` 是给人看的说明。"""


@dataclass
class TopologyFromImage:
    xml: str
    """draw.io 片段（mxStyle + mxCell），与 `Topology.xml` 的格式一致"""

    message: str
    """模型的说明文字 —— 给用户看「AI 说了什么」"""

    tool_calls: list[str]
    """模型调过的工具名（排错用）"""


def _parse_sse(sse_text: str) -> tuple[str | None, str, list[str]]:
    """从 SSE 里取出 XML、模型的文字、工具名。

    **取最后一个 XML** —— 模型可能画完再改一次，后一次才是完整的。
    """
    xml: str | None = None
    text = ""
    tools: list[str] = []
    for raw in sse_text.splitlines():
        line = raw.strip()
        if not line.startswith("data: "):
            continue
        payload = line[6:]
        if payload == "[DONE]":
            break
        try:
            obj = json.loads(payload)
        except (ValueError, TypeError):
            continue
        if not isinstance(obj, dict):
            continue
        kind = obj.get("type")
        if kind == "text-delta":
            text += str(obj.get("delta") or "")
        elif kind == "tool-input-available":
            name = str(obj.get("toolName") or "")
            if name and name not in tools:
                tools.append(name)
            inp = obj.get("input")
            if isinstance(inp, dict):
                candidate = inp.get("xml")
                # 只有含 mxCell 的才算图 —— 别的工具也可能带 xml 字段
                if isinstance(candidate, str) and "<mxCell" in candidate:
                    xml = candidate
    return xml, text, tools


def generate_from_image(
    image_base64: str,
    mime: str = "image/png",
    prompt: str = "",
    timeout: int = DEFAULT_TIMEOUT,
) -> TopologyFromImage:
    """把一张图片交给 networktopology 的 AI，换回 draw.io XML。

    失败时抛 `ImageToTopologyError`，`str(e)` 是给用户看的话。
    """
    if not image_base64.strip():
        raise ImageToTopologyError("图片内容为空")

    body = {
        "messages": [
            {
                "id": "myportal-image-1",
                "role": "user",
                "parts": [
                    {"type": "text", "text": prompt or DEFAULT_PROMPT},
                    {
                        "type": "file",
                        "mediaType": mime,
                        "filename": "architecture.png",
                        "url": f"data:{mime};base64,{image_base64}",
                    },
                ],
            }
        ],
        "sessionId": "myportal-image-to-topology",
    }

    headers = {"content-type": "application/json"}
    if NT_ACCESS_CODE:
        headers["x-access-code"] = NT_ACCESS_CODE

    req = urllib.request.Request(
        f"{NT_BASE}/api/chat",
        data=json.dumps(body).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", errors="replace")[:300]
        raise ImageToTopologyError(
            f"画图服务返回 {e.code} —— {detail}"
        ) from e
    except urllib.error.URLError as e:
        raise ImageToTopologyError(
            f"连不上画图服务（{NT_BASE}）—— {e.reason}"
        ) from e
    except TimeoutError as e:
        raise ImageToTopologyError("画图超时了 —— 图太复杂或服务太慢，再试一次") from e

    xml, text, tools = _parse_sse(raw)
    if not xml:
        # 模型只说了话、没画图 —— 把它的话带出来，用户能看懂为什么
        hint = (text or "").strip().replace("\n", " ")[:300]
        raise ImageToTopologyError(
            "AI 没有画出图来"
            + (f" —— 它说：{hint}" if hint else "")
            + "。换一张更清晰的截图（区域和设备名要能看清）再试。"
        )
    return TopologyFromImage(xml=xml, message=text.strip(), tool_calls=tools)
