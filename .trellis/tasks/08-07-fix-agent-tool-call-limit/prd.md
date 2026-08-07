# 修复 Agent 检索与回答收敛

## Goal

让普通知识库问答在真实 provider 行为下确定性收敛：检索到证据时返回带真实 citation 的总结，答案
分散在多个视频或章节时返回按相关度排序的 Top 5 视频列表；模型无法完成总结时仍返回真实证据列表。
用户不应再因为工具批次、citation 格式重试或累计输出 token 而看到误导性的“检索步骤已达到上限”。

## Background

- 2026-08-07 的第一条真实脱敏轨迹 `request_id=bef82b304c66469ca87ce0bbfec6cc5b` 显示，一个普通
  概念问题在 4 个工具轮次内执行了 10 次检索工具，下一批 2 次调用使 PydanticAI projected usage
  变为 12，超过 `AGENT_TOOL_CALLS_LIMIT=10`。当时的关键代码位于 `app/agent/runtime.py:32-46` 与
  `app/agent/runtime.py:331-342`；完整审计见 `research/root-cause.md`。
- 第一版修复增加了 5/2/3 检索预算、动态 tool prepare、`parallel_tool_calls=false` 和 Top-5 来源分组。
  自动测试全部通过，但真实 provider 证明两个核心假设不成立。
- 第二条真实轨迹中，模型仍在两次响应里分别批量提出 2 次搜索和 3 次扩展。5 次 backend retrieval
  完成后，第一次答案草稿没有通过 citation validator，下一次响应使整个 Agent run 的累计输出 token
  达到 2066，超过 `AGENT_OUTPUT_TOKEN_LIMIT=2000`，最终仍失败。
- PydanticAI 2.15.0 的 `output_tokens_limit` 统计整个 run 的累计模型输出，不是只约束最终答案；
  `parallel_tool_calls=false` 在当前 `openai:deepseek-v4-flash` 路径上是 provider 提示，不是应用边界。
- 第二条轨迹两次搜索共返回 12 个片段，但全部属于同一个视频。当前 segment-level top-k 允许一个视频
  挤满候选窗口，最终按 `item_id` 分组无法补回从未召回的其他视频。
- 第二次失败与测试缺口详见 `research/second-live-failure.md`。
- 第一轮部署 smoke 已到达独立 composer，但它的首次 provider 请求在约 20.2 秒后以
  `ModelHTTPError` 失败并进入 evidence fallback。现有日志丢弃了异常中安全的数字
  `status_code`，无法区分 400/422、429 与 500/503；官方文档研究与两次无用户数据的最小 live probe
  见 `research/composer-http-error-analysis.md`。

## Requirements

### R1 — 应用层强制检索收敛

- 每个模型响应最多实际执行 1 次 `search_segments`、`get_neighbors`、`get_item` 或 `open_at` backend
  retrieval。provider 同一响应发出的其余检索调用必须得到稳定的 skipped 结果，不触发 embedding、SQL
  或存储访问，也不能伪装成“搜索无结果”。
- PydanticAI 本地工具执行必须串行；当前 model step、总预算和分阶段预算必须在同一个锁内原子预留，
  不能依赖并发工具函数稍后更新计数。
- 普通知识检索最多实际执行 5 次 backend retrieval：普通搜索最多 2 次，邻居/元数据/定位扩展合计
  最多 3 次。动作和 pending-confirmation 工具不消耗检索预算。
- `parallel_tool_calls=false` 继续发送以减少支持该字段的 provider 批次，但不得作为 correctness 前提。
- `AGENT_TOOL_CALLS_LIMIT=10` 继续作为模型异常批次/配置错误的最后熔断器，不通过提高它解决收敛。
- 有足够证据时模型可以提前结束；预算耗尽或任何 usage limit 在已经持有可信证据时触发，检索阶段应
  以现有证据结束并进入回答阶段，不返回或持久化未验证草稿。

### R2 — 搜索候选必须支持 Top 5 视频与多章节

- `search_segments` 内部必须 over-fetch segment 候选并按 `item_id` 做有界多样化，避免同一视频的
  多个高分片段占满公开候选窗口。
- 候选顺序先为最多 5 个相关视频各保留一个最强代表片段，再用剩余位置补充已入选视频中的其他相关
  片段。完全重复 segment 去重；同一视频中时间相距较远且语义不同的章节证据必须保留。
- 正常搜索返回最多 10 个 bounded candidates；内部候选池有固定上限，不做全库无界扫描。
- 同一 run 的两次改写查询若命中相同 segment，证据缓存只保留一次；重复命中不增加最终来源数量。
- 模型根据 excerpt、标题、真实来源和可选邻居上下文判断相关度。最终答案最多引用 5 个不同
  `item_id`，顶层一个视频只出现一次，但其下可显示多个真实时间链接。
- Citation 当前没有章节标题，不能从正文猜测或编造章节名。若未来需要正式章节标题，应单独扩展
  ingestion/service contract。

### R3 — 检索与回答使用两个独立阶段

- 第一阶段只负责动作路由、检索与证据收集；知识问答的模型字符串草稿不直接成为用户答案，也不再
  通过 citation mismatch 机械触发一次 fresh search。
- 第二阶段是无工具 answer composer，接收用户问题和有界可信 Citation，使用新的 `RunUsage` 与独立
  `AGENT_OUTPUT_TOKEN_LIMIT`，不继承检索规划已消耗的 output tokens。
- composer 使用 `PromptedOutput(AnswerDraft)` 生成并校验 JSON 文本，不得通过 output tool 发送
  `tool_choice=required`，以兼容拒绝 required tool choice 的 provider Thinking mode。
- composer 输出结构化 sections；每个 section 包含文本和 segment ID 列表。应用验证 ID 属于当前
  evidence allow-list、跨 section 最多 5 个 item，并负责渲染 `[S…]` marker 和分组来源。
- citation 缺失、未知或超过 Top 5 时，只允许 composer 在同一 evidence allow-list 上重试 1 次；
  不新增 embedding/search，不允许机械替换伪造 ID。
- composer 的 request budget 固定为首次生成加 1 次结构化修复。检索阶段和 composer 各自有独立
  usage 计数，原始 request/tool/output-token limits 继续 fail closed。

### R4 — 回答失败时返回确定性证据列表

- composer 在结构化重试后仍无效，或 composer 遇到 timeout、provider/output-token failure 时，丢弃
  所有模型草稿，返回应用生成的相关证据列表。
- fallback 使用 `status=ok`、真实 Citation、视频标题、真实时间链接和 bounded excerpt，并明确说明
  “自动总结未完成，以下是最相关证据”；不得生成新的事实性总结、章节标题或 citation。
- fallback 按候选相关顺序最多显示 5 个视频；同一视频保留已选中的不同时间位置。
- 只有没有可信证据时才返回 `not_found/no_evidence`；embedding 或数据库失败仍分别返回
  `embedding_unavailable` / `retrieval_unavailable`，不得伪装成证据 fallback。

### R5 — 用户结果、历史和诊断边界保持安全

- 有效 composer 输出和 evidence fallback 都只使用 tenant-scoped tools 返回的 Citation。
- 知识回答只持久化规范化后的用户问题/最终可见答案消息，不持久化检索工具 payload、无效模型草稿
  或 composer retry；conversation turn 的 sources 继续保存真实公开 Citation。
- 动作工具、pending confirmation、terminal action outcome、tenant isolation、消息幂等与单条入站
  消息只回复一次的行为不变；动作完成后不得进入 composer。
- 诊断必须区分 retrieval 与 answer phase，并继续只记录固定阶段、计数、limit kind/value 和异常类。
  生产日志不得新增问题、证据、citation ID、工具 payload、模型输出或异常消息。
- provider 抛出 `ModelHTTPError` 时，诊断必须额外记录整数 `http_status`，且只接受 100–599。
  生产环境不得记录 `ModelHTTPError.body`、`str(exception)`、provider 响应正文、请求 schema
  或认证信息。显式 `development` 环境为了本地排障，必须额外记录完整异常文本、provider
  model 和原始 response body；不主动序列化认证头或 API key。
- `request`、`tool_calls`、`output_tokens` 的用户文案必须与实际阶段一致。特别是 output-token failure
  不得显示成“检索步骤已达到上限”；有证据的 composer failure 应静默转为 evidence fallback。

### R6 — 回归必须复现两条真实失败链

- 使用 `FunctionModel` 在一个响应中发出 2 次搜索、下一响应发出 2 次邻居读取和 1 次 metadata 读取，
  即使 `parallel_tool_calls=false` 已设置，也证明每个 step 最多只有 1 次 backend retrieval。
- fake responses 必须提供真实非零 `RequestUsage.output_tokens`，复现累计 2066/2000；检索 usage 不得
  消耗 composer 的新预算。
- 覆盖 composer 正常结构化答案、一次 citation 修复、修复耗尽 evidence fallback、composer timeout/
  output-token fallback，以及无证据/embedding/retrieval failure。
- 构造一个视频拥有大量最高分 segment、另外至少 5 个视频拥有较弱相关 segment 的 service/数据库
  场景，验证候选多样化、Top 5、重复 segment 和同视频远距离章节。
- 运行 Agent/service 定向测试、动作/持久化/tenant/diagnostics 回归和完整测试套件；不调用真实模型或
  embedding provider。
- 构造带 body sentinel 的 `ModelHTTPError`，分别覆盖 retrieval 与 answer phase；断言生产日志只包含
  phase、异常类和安全 status，开发日志还包含完整 message/model/body。非法 status 不得进入日志。

## Acceptance Criteria

- [ ] AC1：忽略 `parallel_tool_calls=false` 的批量 fake provider 每个模型响应最多触发 1 次 backend
  retrieval；extra calls 有明确 skipped outcome，embedding/SQL 调用数不增加。
- [ ] AC2：正常检索最多实际执行 5 次，其中搜索不超过 2、扩展不超过 3；预算耗尽后进入 composer，
  不出现 user-visible `tool_calls limit`。
- [ ] AC3：连续零命中在搜索预算内结束为 `not_found/no_evidence`，不调用 composer，不返回 usage limit。
- [ ] AC4：带非零 `RequestUsage` 的 fake model 复现 retrieval 累计 2066/2000 后，composer 仍使用新的
  2000-token budget 生成有效答案或 evidence fallback。
- [ ] AC5：composer 输出的每个 section 只引用当前 allow-list 中的 segment ID，跨 section 最多 5 个
  item；应用渲染真实 `[S…]` 和来源，模型草稿不能直接进入回答。
- [ ] AC6：composer 第一次 citation 无效时只做 1 次 answer-only retry，不新增 search/embedding；
  第二次仍失败时返回 `ok` evidence fallback，且无效草稿不持久化。
- [ ] AC7：一个视频的高分 segments 不会挤掉其他相关视频；候选覆盖最多 5 个视频，并可在同一视频项
  下保留两个相距较远的真实时间位置。
- [ ] AC8：最终用户结果按相关度最多列出 5 个视频，一个 item 只有一个顶层项，不编造章节标题。
- [ ] AC9：request/tool/output-token limits 分别记录正确 phase/kind/value；output-token failure 不再显示
  “检索步骤已达到上限”。
- [ ] AC10：知识成功/降级 turn 只保存规范化用户与最终回答消息及真实 sources；工具 payload、无效
  draft 和 retry prompt 不进入 conversation history。
- [ ] AC11：动作、pending confirmation、tenant isolation、conversation persistence、诊断隐私、消息
  幂等和单回复回归全部通过。
- [ ] AC12：部署后用原问题“请为我解释强连通向量的含义” smoke，得到结构化总结或 evidence fallback，
  不得到任何 usage-limit 文案。
- [ ] AC13：部署后用至少两个视频、多个章节含相关证据的知识库 smoke，验证多视频 Top 5、同视频多
  时间点和真实 citation。
- [ ] AC14：provider HTTP failure 日志包含 100–599 的 `http_status`、phase、error class、request/trace
  ID；生产日志不包含异常正文、response body、prompt、schema、证据或 secret，开发日志额外
  包含完整 exception message、provider model 和 response body。

## Out of Scope

- 单纯提高 `AGENT_TOOL_CALLS_LIMIT`、`AGENT_REQUEST_LIMIT`、`AGENT_OUTPUT_TOKEN_LIMIT` 或 timeout
  作为主要修复。
- 更换模型、embedding provider、向量 schema 或引入新的 ML reranker。
- 修改字幕 chunking/tokenization 或新增正式章节标题字段。
- 在生产日志中记录问题正文、检索词、模型输出、tool arguments/result、证据、citation ID 或异常原文。
- 保证知识库一定包含某个术语，或在没有可信证据时使用模型记忆补答。

## Risks and Constraints

- 两阶段路径通常多一次 composer provider request，但它消除了检索规划与最终答案争抢累计输出预算；
  fallback 保证 composer failure 不再丢掉已检索证据。
- over-fetch 会增加 BM25/pgvector 候选读取量，因此内部池必须固定有界，并通过数据库测试观察查询行为。
- provider 仍可能发出异常大的工具批次；应用 gate 阻止额外 backend side effects，全局 tool-call limit
  继续拒绝超大批次。
- 规范化 conversation history 不得携带工具结果，否则会放大上下文并可能让下一轮误用旧证据。
