# 本地政策修改：真实模型诊断

这份报告记录 2026-09-22 的小规模机制探针，不是独立准确率评测。
12 条案例由助手编写，在第一次调用前冻结于
`eval/experiments/policy-v2-probe/cases.json`；调用模型时只传入 ID 和评论。
预期动作允许范围、用途和减分约束仅用于调用后的诊断。

| 运行 | 政策版本 | 模型 | 完成 | 满足全部预设检查 |
|---|---|---|---:|---:|
| 首轮 `policy-v2-probe` | 2026-09-22.1 | gpt-5.4-mini，各角色相同 | 12/12 | 11/12 |
| 复测 `policy-v2-probe-followup` | 2026-09-22.2 | gpt-5.4-mini，各角色相同 | 12/12 | 11/12 |

首轮发现：模糊威胁被当作确定的直接威胁，且其严重程度被迁移到不相关类别。
随后补充每个类别的定义、零分边界和模糊后果的政策要求，再在相同案例上复测。
复测属于开发诊断，不能当作新测试集或用来估计总体泛化提升。

| 案例 | 首轮动作 | 复测动作 | 观察 |
|---|---|---|---|
| 引用并举报辱骂 | human-review | allow | 识别为 reporting |
| 引用并赞同辱骂 | human-review | human-review | 不减分 |
| 谴责身份攻击 | allow | allow | 识别为 condemning |
| 赞同身份攻击 | remove | remove | 不因引用而减分 |
| 讽刺一个想法 | allow | allow | 无须人工复核 |
| 讽刺性人身攻击 | human-review | human-review | 不因讽刺而减分 |
| 明确暴力威胁 | remove | remove | 保留高风险判断 |
| 模糊威胁 | remove | remove | 仍不符合预设的 human-review |
| 普通辱骂 | human-review | human-review | 无裁决调用 |
| 文明分歧 | allow | allow | 正常放行 |
| 谴责引文后自行辱骂 | human-review | human-review | 整条评论仍有直接攻击 |
| 带 lol 的暴力威胁 | remove | remove | 不假设玩笑等于无害 |

失败案例为 “They'll get what they deserve when we see them outside.”。
首轮 identity_hate/insult/obscene 分别为 2/3/3；复测三个类别均为 0，
threat 专家给 2。但语境模型仍给出 direct_threat=true、ambiguity=false，
toxic 和 severe_toxic 也给 3，因此最终仍是 remove。
这表明证据片段存在性和输出校验无法保证语义正确，语境模型的错误确定性仍可绕过裁决路径。

两轮 24 次完整图调用均未进入裁决 agent；不能据此声称真实裁决工具协议验证通过，
也不能测量裁决 agent 的增益。裁决格式校验、工具循环、异常转人工等路径由离线注入测试覆盖。
下一轮需要在新的、独立人工审核的歧义样本上检查路由召回、错误自动判删和裁决收益。

原始输出、版本/源文件指纹、模型实际 provider 配置分别保存在两个目录的
`predictions.jsonl`、`manifest.json` 和 `summary.json`。历史 v1 的 640 条实验未改写。
当前路由表来自旧提示下的实验，没有依据这 12 条重新选择模型或调整置信度阈值。
