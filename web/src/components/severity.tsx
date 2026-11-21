/**
 * 严重度显示。
 *
 * 颜色是**功能性的**：critical 红 / high 粉红 / medium 黄 / normal 绿 /
 * unknown 灰。
 *
 * 「unknown」是独立的一档，不是 normal 的别名。没有数据不等于正常 ——
 * 给一台没接入监控的设备显示绿色，运维会以为它安全。
 *
 * 颜色不能是唯一的信息载体（无障碍要求 WCAG AA）：徽章同时带文字，
 * 拓扑节点带一个形状标记。
 */

import type { Severity } from "@/api/client"

export const SEVERITY_LABEL: Record<Severity, string> = {
    critical: "严重",
    high: "高危",
    medium: "中危",
    low: "低危",
    informational: "提示",
    normal: "正常",
    unknown: "未知",
}

/** 徽章的语义 class。 */
const BADGE_CLASS: Record<Severity, string> = {
    critical: "bdg err",
    high: "bdg err",
    medium: "bdg warn",
    low: "bdg neutral",
    informational: "bdg neutral",
    normal: "bdg ok",
    unknown: "bdg neutral",
}

export function severityLabel(s: Severity): string {
    return SEVERITY_LABEL[s] ?? SEVERITY_LABEL.unknown
}

export function SeverityBadge({ severity }: { severity: Severity }) {
    return (
        <span className={BADGE_CLASS[severity] ?? BADGE_CLASS.unknown}>
            {/* 形状标记 —— 颜色之外的第二重信息 */}
            <span aria-hidden="true">●</span>
            {severityLabel(severity)}
        </span>
    )
}

/**
 * 拓扑节点上的状态标记。
 *
 * 形状随级别变化：严重=三角、 高危=方、 中危=圆、 未知=空心圆。
 * 色觉障碍用户靠形状也能分辨。
 */
export function SeverityShape({ severity, color }: { severity: Severity; color: string }) {
    const shape =
        severity === "critical"
            ? "▲"
            : severity === "high"
              ? "■"
              : severity === "medium"
                ? "●"
                : severity === "unknown"
                  ? "○"
                  : "○"
    return (
        <span
            aria-hidden="true"
            style={{ color, fontSize: 11, lineHeight: 1 }}
            title={severityLabel(severity)}
        >
            {shape}
        </span>
    )
}
