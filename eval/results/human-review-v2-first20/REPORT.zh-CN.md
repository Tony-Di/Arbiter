# 20 条复核标签对照已保存的消融预测

本报告只重放已保存的预测，不调用模型。由 `scripts/score_reviewed_system.py` 生成。

## 解读限制

- 这批案例按旧实验的方案分歧优先挑选，并非随机样本；数字只用于诊断，不代表总体准确率。
- 标签为 `ai_assisted`：复核人确认时能看到 AI 建议，不属于独立盲审。
- 预测来自 holdout, development, stress 阶段的受控实验缓存（模型：gpt-5.4-mini），生成于政策 2026-09-22.2 定稿之前；反映旧系统判断与新标签的差异，不评估当前代码。
- stress 阶段为高风险富集样本。

## 标签来源

- 复核人：`project-owner`；20 条全部完成。
- 与 AI 草稿完全一致 19 条；修改 1 条：civil-comments-5b142f3abb8ecc79fa07。
- 旧参考标签与复核标签动作一致 9/20。
- 导出修订 `civil-comments-5b142f3abb8ecc79fa07`：Only case where the reviewer disagreed with the AI draft. No surrounding context; the reviewer may have read discrimination into it, so the label records unclear intent rather than a confirmed attack.

## 各方案

| 方案 | 与复核动作一致 | Action macro-F1 | 漏放（应审/删却允许） | 误删 | 交人工 |
|---|---:|---:|---:|---:|---:|
| single_call | 13/20 | 0.420 | 2/16 | 2/19 | 14/20 |
| specialists_only | 8/20 | 0.300 | 8/16 | 3/19 | 5/20 |
| specialist_panel | 8/20 | 0.276 | 7/16 | 3/19 | 8/20 |
| policy_agent | 6/20 | 0.222 | 8/16 | 4/19 | 6/20 |

相邻方案的配对变化（按复核标签计算，不是显著性检验）：

- `single_call` → `specialists_only`：纠正 3，改错 8，动作变化 11。
- `specialists_only` → `specialist_panel`：纠正 2，改错 2，动作变化 5。
- `specialist_panel` → `policy_agent`：纠正 2，改错 4，动作变化 6。

逐条结果见同目录 `cases.csv`。
