# 本地人工评测：从标注到验证

旧 160 条参考标签的来源已由用户确认为“模型生成，或尚未逐条人工核对”。保留它们有助于排查历史分歧，但它们不能证明准确率提升。目前完成人工复核的只有首批 20 条，而且是 AI 辅助复核（见下文）；盲审页、160 条完整集和新的 60 条仍为 0。助手生成更多标签仍不等于人工标注。

## 从首批 20 条开始

**AI 预标注已完成。** 应用户请求，助手逐条填写了首批 20 条的动作、严重程度、类别、中文理由及原文依据：允许 5 条、交人工 14 条、删除 1 条；另标记 5 条边界疑点。这里“交人工”是建议的评论审核动作，不是数据标注完成状态。

**人工复核已完成（20/20，2026-09-22）。** 19 条原样确认 AI 建议；1 条（中餐馆／烧烤店／游泳池气味投诉）由复核人改为交人工 / 1 / identity_hate。这条原文没有上下文，意图不明，是唯一与 AI 意见不同的条目。最初导出的理由仍是 AI 的“允许”，与新标签矛盾，因此保留为 `reviewed-export.initial.json`，但不用于评分。改写理由后的最终导出为 `first-20/ai-assisted/reviewed-export.json`（`revisions` 字段记录修改经过），导入结果为 `human-review-v2/first20-human-assisted.jsonl`。

需要省去从空白填写的工作，可以打开 [AI 辅助复核页面](../eval/experiments/human-review-v2/first-20/ai-assisted/review.html)，或在本地服务运行时访问 `http://127.0.0.1:8767/ai-assisted/review.html`。按钮“下一个疑点”可以定位优先确认项。建议已预填，但只有你点击“确认本条并继续”的条目才进入人工复核导出。改动 AI 建议的动作、严重程度或类别后，必须同时改写理由，否则页面不允许确认。尚未确认的建议保存在 [AI 预标注 JSON](../eval/experiments/human-review-v2/first-20/ai-assisted/ai-preannotations.json)，来源为 `ai_preannotation`，人工作业声明为 false。

AI 辅助页不属于独立盲审，使用独立批次 ID 与进度。其人工复核导出需使用 `first-20/ai-assisted/packet.json` 导入，导入结果会保留 `annotation_method=ai_assisted` 和 AI 草稿哈希；即使最终人工确认，也不应描述为未见模型建议的独立标注。原盲审页保留；新的 40 条 holdout 未被预标注。

打开 [首批 20 条盲审页](../eval/experiments/human-review-v2/first-20/review.html)，填写复核人标识，然后逐条选择动作、严重程度、类别并写明原文依据。页面有中文概要，也有从共享政策直接生成的完整英文规则和六类定义。没有旧参考答案或模型预测。

保存会进入下一条；无法确定可跳过。浏览器允许时进度存于本地。勾选“亲自逐条检查”后导出 JSON 作为备份；同一批次可以导入继续。页面不会向 API 发送评论或写入生产判例库。导入脚本只验证声明和数据一致性，不能自动证明填写者的身份或标注质量。

保存后会跳到下一条未确认项，到末尾时会返回前面跳过的项目。页首显示还剩多少条，也可以点击“继续未确认项”。全部确认后会显示完成提示并定位到导出区域；刷新会恢复保存的标签并打开第一条未确认项。完成确认不会自动勾选声明或下载文件。

可以直接用浏览器打开 HTML；如浏览器限制本地存储，在项目根目录运行：

```powershell
.venv/Scripts/python.exe -m http.server 8767 --bind 127.0.0.1 --directory eval/experiments/human-review-v2/first-20
```

然后访问 `http://127.0.0.1:8767/review.html`。服务器只绑定本机；关闭终端会停止服务，已导出的 JSON 保留。

| 批次 | 数量 | 用途 |
|---|---:|---|
| [旧实验首批](../eval/experiments/human-review-v2/first-20/review.html) | 20 | 优先复核方案分歧，统一政策理解 |
| [旧实验完整集](../eval/experiments/human-review-v2/all-cases/review.html) | 160 | 重新审计历史参考标签，包含首批 20 条 |
| [自然裁决探针](../eval/results/adjudicator-v2-probe/human-review/review.html) | 8 | 判断这次裁决纠正了什么、改错了什么 |
| [新 calibration](../eval/experiments/fresh-human-v2/calibration/review.html) | 20 | 人工完成后用于选择配置或门槛 |
| [新 holdout](../eval/experiments/fresh-human-v2/holdout/review.html) | 40 | 选项冻结后才用于最终复验 |

各批次的保存和导出独立，首批 20 条的 JSON 不能直接导入 160 条页面。首批是政策对齐的试标批次；整集标注前可决定是否需修改政策。若政策改变，应建立新版本批次并重新检查标签，不能悄悄修改冻结的 `packet.json`。

新 60 条按来源分数分层，并非总体的随机代表样本。排除旧实验、旧探针和种子草稿，并用标准化文本、三词组 Jaccard ≥ 0.8 排除近重复；这不保证语义层面完全去重。分层分数不是审核答案，尚未对新样本调用模型。

## 导入已完成的人工标签

以下 `reviewed-first20.json` 代表你从页面导出的文件，先放到项目根目录，或替换为实际绝对路径。命令要求全批完成，且拒绝覆盖已有输出：

```powershell
.venv/Scripts/python.exe scripts/import_review_labels.py `
  --packet eval/experiments/human-review-v2/first-20/packet.json `
  --reviewed reviewed-first20.json `
  --output eval/experiments/human-review-v2/first20-human.jsonl `
  --require-complete
```

其他批次替换对应 `packet.json`、导出文件及输出名即可。校验包括批次哈希、政策版本、原文哈希、动作/严重程度、类别、理由、复核时间和声明。部分标注可以备份；不能用部分完成的批次冒充完整评测。

如果使用 AI 辅助页面，导出后的对应命令为：

```powershell
.venv/Scripts/python.exe scripts/import_review_labels.py `
  --packet eval/experiments/human-review-v2/first-20/ai-assisted/packet.json `
  --reviewed reviewed-assisted.json `
  --output eval/experiments/human-review-v2/first20-human-assisted.jsonl `
  --require-complete
```

若多人参与，建议独立复核分歧项后讨论，保留最终修改理由。不要为了使模型结果看起来更好而改标签。评测样本不能插入生产判例库，否则后续检索可能泄露答案。

## 用已保存的消融预测给复核标签打分

首批 20 条都来自旧受控实验的 development／holdout／stress 阶段，可以直接对照已保存的四个方案预测，不需要调用模型：

```powershell
.venv/Scripts/python.exe scripts/score_reviewed_system.py `
  --packet eval/experiments/human-review-v2/first-20/ai-assisted/packet.json `
  --reviewed eval/experiments/human-review-v2/first-20/ai-assisted/reviewed-export.json `
  --output-dir eval/results/human-review-v2-first20
```

脚本要求每条、每个方案都有与阶段报告指纹和原文哈希一致的缓存预测；如果标签改了但理由仍是 AI 原文，脚本会拒绝打分。结果见 [首批 20 条对照报告](../eval/results/human-review-v2-first20/REPORT.zh-CN.md)。这些预测生成于政策 2026-09-22.2 定稿之前，且案例按分歧优先挑选；数字只说明旧系统的判断与新标签有多大差距，不能作为当前系统的准确率。

用当前代码重跑这 20 条（80 次真实调用，全部 gpt-5.4-mini）的结果见 [当前代码重跑报告](../eval/results/human-review-v2-first20/CURRENT-CODE.zh-CN.md)。多 agent 方案一致数从 6–8 升到 11–13；在同一上游输出上重放，裁决 agent 没有改变任何动作；唯一应删除的案例仍无方案删除。看过这 20 条的结果后，它们只能用作开发集。

## 对已保存的裁决做前后评分

8 条自然裁决探针完成后，不需要再次调用模型。脚本对齐同一条原文、同一政策和同一模型，输出纠正/改错数量、追加耗时以及不同门槛的重放结果：

```powershell
.venv/Scripts/python.exe scripts/score_reviewed_adjudication.py `
  --packet eval/results/adjudicator-v2-probe/human-review/packet.json `
  --reviewed reviewed-adjudicator.json `
  --model gpt-5.4-mini --kind natural `
  --output eval/results/adjudicator-v2-probe/human-scored.json
```

这 8 条是诊断案例，即使完成标注，也不能变成独立、代表总体的准确率评测。门槛重放发生在裁决调用之后，不会节省已发生的调用耗时；程序不会自动修改生产门槛。

## 新样本复验顺序

1. 先按冻结政策完成新 calibration 的人工标签，再用上述导入工具验证并输出 JSONL。
2. 用 `scripts/run_system_eval.py` 对 calibration 运行受控配置；只对真正完成复核的文件使用 `--annotation-status human-confirmed`。具体参数见 [系统评测说明](./system-eval.md)。
3. 在 calibration 上比较质量、自动处理量和追加延迟，记录最终选择的模型、提示版本、政策、触发条件、门槛、代码版本及选择理由。小样本可能不足以支持改门槛，保留原值也是有效结论。
4. 配置冻结后，再运行已完成人工标注的 holdout。不要在查看其预测后继续用它调参；如需再改，记录探索性质并另准备新测试集。

新 calibration 和 holdout 还没有人工标签，因此没有执行这组新数据的模型评测，也没有选出“最优”门槛。真实调用的已知结果见 [裁决报告](../eval/results/adjudicator-v2-probe/REPORT.zh-CN.md)。
