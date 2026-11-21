/**
 * FortiSIEM 分段诊断。
 *
 * 「连不上」有太多种原因 —— 网络不通、证书不对、凭据过期、接口没权限。
 * 合成一句「未连接」等于让运维自己猜。这里把后台的四段探测**逐段摊开**，
 * 失败的那一段标红并把原因写在旁边。
 *
 * ## 颜色不是唯一的信息载体
 *
 * 与 severity.tsx 同样的规矩：每段同时带**文字**（通过 / 失败 / 未到达）
 * 与**形状**（● / ▲ / ○）。色觉障碍用户靠形状也能分辨是哪一段出的问题。
 * 徽章用的是样式表里已有的 bdg 语义类（bdg ok / err / neutral），
 * 颜色来自设计令牌，不在组件里硬编码。
 */

import { type SiemProbe, type SiemStage, type SiemStatus, STAGE_LABEL } from "@/api/client"

/** 四段探测的固定顺序 —— 与后台的探测顺序一致。 */
const STAGE_ORDER: Exclude<SiemStage, "ok">[] = ["tcp", "tls", "auth", "api"]

// STAGE_LABEL 从 @/api/client 引入 —— 中文标签只有一份，
// 错误文案那边也要用。

/** 一段的状态。`skipped` = 前面已经断了，没走到这一段。 */
export type StageState = "ok" | "fail" | "skipped"

export interface StageRow {
    key: Exclude<SiemStage, "ok">
    label: string
    state: StageState
    detail: string
}

/**
 * 把后台的 status 摊成四行。
 *
 * 判定顺序：**后台的 `stage` 是权威**（「卡在哪一段」），`probes[段].ok`
 * 是实测结果。两者一致时结论相同；不一致时以 stage 为准 —— 那是后台
 * 明确告诉前端的失败位置。
 */
export function stageRows(status: SiemStatus): StageRow[] {
    return STAGE_ORDER.map((key) => {
        const probe: SiemProbe | undefined = status.probes[key]
        const failedHere = status.stage === key

        if (!probe) {
            // 没走到这一段 —— 前面的段已经断了
            return {
                key,
                label: STAGE_LABEL[key],
                state: failedHere ? "fail" : "skipped",
                detail: failedHere
                    ? (status.error ?? "未取得探测结果")
                    : "未探测到（连接在此前已中断）",
            }
        }

        return {
            key,
            label: STAGE_LABEL[key],
            state: probe.ok && !failedHere ? "ok" : "fail",
            // 失败的那段，**顶层的 error 是权威的失败原因**（契约里的
            // error 字段），probe.detail 是这一段的实测细节。
            // 两者不同时以 error 为准 —— 它才是后台给出的结论。
            // **只有权威段才用顶层 error** ——
            // 顶层 error 是「卡在哪一段」的结论，只对 status.stage
            // 指的那一段成立。别的段失败时借用它，会显示成别段的原因。
            // 非权威段失败就用它自己的 probe.detail。
            detail: failedHere ? (status.error ?? probe.detail) : probe.detail,
        }
    })
}

const STATE_META: Record<StageState, { text: string; shape: string; pill: string }> = {
    ok: { text: "通过", shape: "●", pill: "bdg ok" },
    fail: { text: "失败", shape: "▲", pill: "bdg err" },
    skipped: { text: "未到达", shape: "○", pill: "bdg neutral" },
}

/** 四段诊断。失败的那一段标红，原因写在旁边。 */
export function SiemStageList({ status }: { status: SiemStatus }) {
    const rows = stageRows(status)

    return (
        <ul style={{ listStyle: "none", margin: 0, padding: 0 }}>
            {rows.map((row) => {
                const meta = STATE_META[row.state]
                return (
                    <li
                        key={row.key}
                        style={{
                            display: "flex",
                            alignItems: "flex-start",
                            gap: 10,
                            padding: "10px 14px",
                            borderBottom: "1px solid var(--border)",
                            background:
                                row.state === "fail"
                                    ? "color-mix(in srgb, var(--color-sev-critical) 6%, transparent)"
                                    : "transparent",
                            borderLeft:
                                row.state === "fail" ? "3px solid var(--color-sev-critical)" : "3px solid transparent",
                        }}
                    >
                        {/* 形状标记 —— 颜色之外的第二重信息 */}
                        <span
                            aria-hidden="true"
                            style={{
                                fontSize: 12,
                                lineHeight: "20px",
                                color:
                                    row.state === "ok"
                                        ? "var(--color-sev-normal)"
                                        : row.state === "fail"
                                          ? "var(--color-sev-critical)"
                                          : "var(--color-sev-unknown)",
                            }}
                        >
                            {meta.shape}
                        </span>

                        <span style={{ minWidth: 92, fontWeight: 600, fontSize: 13 }}>{row.label}</span>

                        <span className={meta.pill}>{meta.text}</span>

                        <span
                            className="mono muted"
                            style={{
                                flex: 1,
                                minWidth: 0,
                                fontSize: 12,
                                wordBreak: "break-word",
                                color: row.state === "fail" ? "var(--color-sev-critical)" : undefined,
                            }}
                        >
                            {row.detail}
                        </span>
                    </li>
                )
            })}
        </ul>
    )
}
