# Arbiter — 架构评审与升级路线图

> 日期：2026-06-04 ｜ 类型：评审 + 路线图（非 spec / 非 plan）
> 一句话：**现在最该做的不是加新功能，而是把还没跑起来的核心差异化（跨模型评测）跑通**；
> 在此基础上挑几个「高信号、低范围风险」的增强，其余一律推迟。

本文基于对实际代码的逐文件阅读得出（含 `file:line` 证据），不是泛泛建议。

---

## ⚠️ 更新 2026-06-05 — 目标锁定 **AI Engineer / Agent Engineer**：优先级重排（取代 §G 排序）

> 作者澄清：求职目标是 **AI Engineer / Agent Engineer**，**不是** evaluator / Trust&Safety / responsible-AI。
> 因此本文原先把「评测的统计严谨性（§C）」当成最高信号是 **对错了对象**。下面重排，并取代 §G 的顺序。

**信号权重（对 AI/Agent Engineer）：**
- 🔝 **多 agent 编排（LangGraph，§A 产品路径）= 皇冠明珠。** Agent Engineer 看的就是：并行 specialist + 聚合 + **动态路由 / 条件边** + 失败重试 + 状态管理。
- **高：可 demo 的上线产品 + live URL。** AI Engineer 要 ship。
- **降级：跨模型评测** 从「主菜」退为「配角」—— 它的价值是 **驱动路由表** + 证明「我用测量选模型」，**跑一遍即可，不深挖统计**。

**取代 §G 的推荐顺序：**
1. **修 `context.py` prompt 正确性 bug（§A）** —— agent 判决不能是垃圾，任何运行前的闸门。
2. **多 agent 管线用 3 个真模型（DeepSeek/GPT/Gemini，Claude 暂缓）跑通端到端** —— 核心信号上线。
3. **eval 跑一遍出真路由表**（§B1 并发 + §B2 缓存 adapter 让它跑得动）—— 精简版：点估计 + 公平性切片即可，**跳过 §C 的 bootstrap/McNemar/bias-AUC**（对本目标属过度投资）。
4. **部署上线（live URL）。**
5. **逐 agent 判决流式推到 UI（SSE，§D2）** + **条件升级边（§D3 escalation）** —— 从原 stretch **升级为核心 agentic 卖点**。
6. 有余力：注入鲁棒性切片（§E）。

**对照原文要点的调整：**
- §C（统计严谨性）：保留为「可信度小加分」，**不再是最高优先级**，别投太多。
- §D3（条件升级边）/ §D2（流式 UI）：从 stretch **提到核心**——它们才是 Agent-Eng 的故事。
- §F 的范围陷阱依然全部有效（别微调开源模型、别 pgvector、别 bias-AUC）。

---

## 0. 当前状态（事实）

- 结构已搭好，单测全绿（74 passed），但 **真正的多模型运行链路 + 多模型评测都还没跑过**。
- 只接了 DeepSeek；**Claude / Gemini 适配器不存在**；`routing_table.json` 是「6 类全 deepseek」的占位 stub。
- 也就是说：你说「缺的多 AI 分析链路」——**那恰恰就是这个项目的本体**，不是一个可选增强。

---

## A. 架构现状：并发那件事（最重要的结论）

**产品侧的并行是真的、你搭对了；评测侧是纯串行，那才是真正的瓶颈。**

### 产品路径（OK）
- `graph.py:22-26`：6 个 specialist + context 节点从 `START` 同一 super-step 扇出。
- `state.py:17-18`：`raw_verdicts` / `routing_snapshot` 带了 `merge_verdicts` reducer，并行写不会冲突（LangGraph 没有 reducer 会抛 `InvalidUpdateError`——你处理了）。
- LangGraph 对同一 super-step 的 **同步** 节点用线程池跑；而 `openai_compat.py:22` 的阻塞 HTTP 调用在网络等待时会释放 GIL → 6+1 个调用 **真正重叠**。
- 单请求延迟 ≈ **最慢的那一个调用**，不是 7 个相加。
- 端点是同步 `def`（`main.py:54`），FastAPI 把它丢到 worker 线程，不阻塞事件循环。
- ✅ **零成本验证法**：在 `tests/product/test_graph.py` 里把假的 `classify_fn` 改成 `time.sleep(1)`，给 `graph.invoke(...)` 计时。≈1s = 并发（符合预期）；≈7s = 串行。先验证再信。

### 评测路径（真正的问题）
- `collect.py:26-31` 是裸的 `for row in sample_rows: classify_fn(...)` —— **一次一个阻塞调用**。
- 计划规模 ≈ 2–3k 评论 × 4 模型 ≈ 8–12k 次调用。每次 ~1–2s 串行 = **一次跑要好几个小时**。
- 这是唯一一个无歧义的性能黑洞。

### 另外两个代码里能直接看到的问题
- **每次调用都新建 HTTP client**：`registry.py` 的 `get_adapter` 每次 `classify` 都新建 `OpenAICompatAdapter` → 新 `OpenAI()` → 新连接池 → 每次都 TLS 握手。评测上千次调用时尤其浪费。
- **`context.py` 有潜在 prompt bug**：`build_context_prompt`（`context.py:26-47`）是从「严重度」prompt 复制过来的——讲的是 0–3 评分、"judge for each category"，但这个节点实际输出的是 5 个 **上下文 flag**（sarcasm/quotation/…），而 flag 的含义根本没对模型解释。这些 flag 又驱动 aggregator 的降级/升级逻辑 → 会悄悄产出垃圾 flag、污染每一条判决。**跑任何真实评测前必须修。**

---

## B. 结构 / 性能改动（按优先级）

| # | 改动 | 为什么 | 位置 | 工作量 |
|---|---|---|---|---|
| 1 | **评测 collect 加有界并发 + 重试/退避** | 几小时 → 几分钟；让多模型跑变得可行；真实的系统工程故事 | `eval/collect.py`（ThreadPoolExecutor 或 asyncio，信号量 ~8–16，429 上指数退避） | **M** |
| 2 | **缓存 adapter / client** | 跨调用复用连接池，免费提速 | `registry.py`（对 `get_adapter` 加 `@lru_cache`） | **S** |
| 3 | **修 context prompt** | 正确性——坏 flag 会污染每条聚合结果 | `context.py:26-47` | **S** |
| 4 | （次要）DB 写出热路径 | `moderate()` 现在 return 前先 commit；改成后台任务 | `main.py:56` | **S** |

> 注意：**不要**把产品路径改成 async——LangGraph 已经帮你线程池化了。并发的活儿属于 **评测**，不在请求路径上。

---

## C. 性价比最高的「新增」：评测的统计严谨性

现在 `score.py` 只给点估计 P/R/F1。但这个项目的整个论点是「模型 A 比 B 更准/更公平」——**点估计是轶事，不是证据**。加上：

- 对每个类别 F1 的 **bootstrap 95% 置信区间**；
- "A vs B 在类别 X" 的 **McNemar 配对检验**（或配对 bootstrap）。

这是 **对缓存里的 JSONL 预测做纯离线计算——额外 API 成本 $0**——却能把
*"DeepSeek 0.82 vs GPT 0.79"* 变成
*"DeepSeek 在 threat 上显著优于 GPT，p<0.05，F1 CI [0.78, 0.86]"*。

这一项是「排行榜」和「严谨评测」的分水岭——对评测 / T&S 岗是最高信号。⚠️ 但作者目标是 **AI / Agent Engineer**（见顶部 2026-06-05 更新）：对该目标这只是 **可信度小加分，不是头牌，别过度投资**。若做：扩展 `eval/score.py`（+ 一个小 `eval/stats.py`）。

**配套且同样便宜：跨模型分歧挖掘。** 你本来就有每个模型每条评论的缓存判决 → 把「模型之间分歧最大」的评论挑出来。那就是「难例」，是极好的 dashboard 面板 + 关于模型可靠性/不确定性的面试故事。位置：对缓存做只读遍历。

---

## D. 其他「有界 + 高信号」的新增（按优先级）

1. **模型对比 + 公平性 dashboard**（Web）：带 CI 的逐类别 F1 表 + 身份过度标记（FPR-gap）图。**这才是招聘官真正会点开的那张截图。** 数据是现成的结果文件，纯渲染活。(M)
2. **逐类别判决流式推送到 UI**（`main.py` 出 SSE，`engine.ts` 消费）：把「多 agent」这件事 **可视化**，demo 冲击力强。(M)
3. **置信度门控的升级（escalation）**：只在 specialist 之间分歧、或贴近阈值时才跑 context / 更强推理模型——LangGraph 的 **条件边**。既是性能优化，又是真正「agentic」的故事（动态路由，而非静态 DAG）。(M，stretch)

---

## E. 前沿但要克制

**审核器自身的 prompt-injection 鲁棒性**——"这条评论是否试图越狱裁判？" 是 T&S 热点、信号高。但要封顶：只做一个 **小评测切片**（几条注入式测试评论，量一下每个模型会不会被操纵），**不要**做成一整个子系统。(stretch)

---

## F. 要避免 / 推迟的范围陷阱

| 诱惑 | 为什么跳过 |
|---|---|
| 微调一个「开源模型」当第 4 个选手 | NOTES 已标 out-of-scope；几周工作量，还稀释评测故事 |
| pgvector「相似历史案例」 | NOTES 已点名——会让 Arbiter 看起来像 DocSense（你的 RAG 项目），毁掉区分度 |
| 完整 Jigsaw bias-AUC（Subgroup/BPSN/BNSP） | 重且不直观；你计划的 FPR-gap 已经把过度标记的故事讲清楚了 |
| 成本/延迟感知的 Pareto 路由 | 花哨，但把路由叙事搞复杂；F1 + recall + 公平性覆盖已经是好故事 |
| 任何把它变成通用分类器 / 政策-RAG 的东西 | 直接摧毁整个差异化 |

---

## G. 元建议 + 推荐顺序

你自己的 NOTES 说得最对：*已交付的小项目 > 没做完的大项目，因为它的使命就是被看见。* 所以对「该加什么牛逼东西」最诚实的回答是——**现在最能加分的不是新功能，而是把你还没跑的核心差异化做完。** 今天只有 DeepSeek 接了，Claude/Gemini 适配器不存在，路由表是占位 stub，跨模型评测从没跑过。**你说缺的「多 AI 分析链路」就是这个项目本身。**

**推荐顺序**（锚定你已锁定的 eval-core-first 构建顺序）：

1. **collect 加并发 + 缓存 adapter**（B1、B2）——让评测跑得动。
2. **修 context prompt**（B3）——任何真实运行前的正确性闸门。
3. **接 Claude + Gemini 适配器** → 跑真正的 4 模型评测 → 产出真实路由表 + metrics/公平性报告。*差异化正式上线。*
4. **加统计严谨性**（C）——全项目里每块钱买到的可信度最高的一项。
5. **做对比 + 公平性 dashboard**（D1）——招聘官截图。
6. *有余力再做：* 流式 UI、置信度门控升级、注入切片。

1–5 全都是 **有界** 的，每一步都在强化核心论点，而不是向外摊大。

---

## 附：本次评审已读文件清单（证据来源）

`product/graph.py`、`product/nodes.py`、`product/state.py`、`product/context.py`、`product/aggregator.py`、
`classify/core.py`、`classify/adapters/openai_compat.py`、`classify/registry.py`、`classify/schema.py`、
`api/main.py`、`api/db.py`、`eval/collect.py`、`eval/score.py`、`eval/route.py`、`web/src/App.tsx`、`web/src/lib/engine.ts`、`NOTES.md`。
