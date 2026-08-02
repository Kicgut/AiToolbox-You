# 供应商余额、额度与用量连接器调研

> 调研日期：2026-08-01。仅采纳厂商官方文档、官方开源仓库或厂商维护的公开 issue；未把网页控制台、逆向端点或第三方工具的实现当作可接入契约。未写入或读取任何用户凭据。

## 结论速览

| 服务 | 可确认的正式可读数据 | 是否可作为“订阅剩余额度” | 建议 |
| --- | --- | --- | --- |
| DeepSeek API | API 账户余额 | 否 | 支持原生只读余额连接器 |
| 阿里云 / DashScope | 阿里云账户可用余额；单请求/单任务 usage | 否 | 可选连接器，须额外 RAM/STS 只读授权 |
| OpenCode Go | 无已发布的个人订阅用量 API | 否 | 不接入；仅可展示本工具观测到的调用 |
| Kimi / Moonshot API | API 账户余额；单次请求 usage | 否，且 Kimi 会员/Code 与 API 独立 | 支持原生只读余额连接器，配置平台变体 |
| 智谱 / GLM | 普通调用可产生响应 usage；未确认余额或 Coding Plan 额度查询 API | 否 | 不实现原生余额/套餐查询；等官方文档 |
| CC Switch | 官方开源应用已实现额度展示/缓存，但未发现稳定、公开、文档化的本地 API 或数据契约 | 可作可选显示来源，但不可依赖/抓库 | 仅在安装且其公开接口将来明确时启用；否则走用户配置或原生连接器 |

“余额”是预付费 API 可用资金；“单次 usage”是某一次请求的 token 计量；两者都不是订阅窗口（5 小时/周/月）的剩余比例，UI 和数据模型不得混用。

## DeepSeek

- **正式端点：**`GET https://api.deepseek.com/user/balance`，使用 `Authorization: Bearer <API Key>`。返回 `is_available`，并按 CNY / USD 分组返回 `total_balance`、`granted_balance` 与 `topped_up_balance`；余额数值为字符串，应以 decimal/原字符串及币种保存，禁止跨币种相加。[官方余额 API](https://api-docs.deepseek.com/api/get-user-balance/)
- **语义：**API 账户余额，不是订阅套餐额度，也不是历史总用量。普通 Chat Completion 的响应 `usage` 只代表该请求；流式请求需 `stream_options.include_usage=true` 才会在末尾块获得完整 usage。[官方 Chat API](https://api-docs.deepseek.com/api/create-chat-completion/)
- **约束：**余额端点没有公布独立 TTL/RPM。官方限流页仅说明模型调用的并发限制和 429；建议仍沿用产品的 15 分钟刷新、手动刷新与 429 退避，不能声称这是厂商指定的余额刷新间隔。[官方限流说明](https://api-docs.deepseek.com/quick_start/rate_limit/)

## 阿里云 / DashScope（百炼）

- **账户余额：**使用阿里云费用中心 BssOpenAPI 的 `QueryAccountBalance`，而非 DashScope API Key。该接口返回 `AvailableAmount`、`AvailableCashAmount`、`CreditAmount`、`Currency` 等；`QuotaLimit` 的文档语义是生态客户额度上限，不能解释为百炼模型套餐余量。[官方接口参考](https://help.aliyun.com/zh/user-center/developer-reference/api-bssopenapi-2017-12-14-queryaccountbalance)
- **鉴权：**需阿里云 OpenAPI 的 RAM/STS 签名凭据与相应只读权限（文档列出 `bss:DescribeAcccount`）；因此用户须另行配置只读 RAM/STS，`DASHSCOPE_API_KEY` 不能代替它。[官方调用授权](https://help.aliyun.com/zh/user-center/developer-reference/api-calling-authorization)；[请求签名](https://help.aliyun.com/zh/sdk/product-overview/v3-request-structure-and-signature)
- **用量与新鲜度：**DashScope 的调用/异步任务响应可带该次任务的 `usage`，并非账户累计或套餐余量。异步任务查询为 `GET https://dashscope.aliyuncs.com/api/v1/tasks/{task_id}`；官方说明已完成任务通常保留 24 小时，任务查询限速为每阿里云账号 20 QPS。[异步任务官方文档](https://help.aliyun.com/en/model-studio/manage-asynchronous-tasks)
- **未确认能力：**未发现 DashScope 原生的 API 账户余额、订阅剩余或账户累计模型用量 endpoint。BSS 账单 API 属账单消费，通常有约一天延迟，不能作为实时额度。[账单接口说明](https://help.aliyun.com/en/user-center/developer-reference/api-queryinstancebill)

## OpenCode Go

- **已确认：**官方 Go 页面公开的是订阅价格及按模型计算的“每 5 小时请求数”上限，不是当前用户的剩余比例或余额 API。[OpenCode Go 官方页](https://dev.opencode.ai/go)
- **未确认/不接入：**截至调研日，未找到官方文档化的个人 Go 订阅用量或余额 API。OpenCode 官方仓库中仍处于 Open 状态的功能请求明确称 dashboard 有滚动、周、月比例和重置时间，但“没有 API endpoint”；该 issue 不是 API 契约，反而说明不能据此猜测端点或抓取网页数据。[官方仓库 issue #16017](https://github.com/anomalyco/opencode/issues/16017)
- **结论：**不保存 cookie、不调用未文档化 dashboard 请求；只能聚合本工具实际观察到的 OpenCode 会话用量并标注范围，或等待官方发布 API。

## Kimi / Moonshot

- **`.ai` 平台余额：**`GET https://api.moonshot.ai/v1/users/me/balance`，使用 `Authorization: Bearer <MOONSHOT_API_KEY>`；返回 USD 的 `available_balance`、`voucher_balance`、`cash_balance`。这是 API 余额，非订阅套餐额度。[官方余额 API](https://platform.kimi.ai/docs/api/balance)
- **平台隔离：**`platform.kimi.ai` 和 `platform.kimi.com` 的 Key 彼此独立；`.com` 官方概览也列出对应 `/v1/users/me/balance`，其 base URL 为 `https://api.moonshot.cn/v1`。连接器必须让用户明确选平台，不能跨域自动回退。[`.com` 官方概览](https://platform.kimi.com/docs/api/overview)
- **单次 usage：**Chat 响应可带 prompt/completion/total/cached token；流式时在最终块获得 usage。未找到账户级历史累计 usage API，因此仅可累计本工具自身观察到的请求并明确范围。[`.ai` 官方 Chat API](https://platform.kimi.ai/docs/api/chat)
- **订阅边界：**Kimi API 开放平台按量付费，且官方说明它与 Kimi Membership/Kimi Code 独立；严禁把上述 API 余额显示成会员或 Code 套餐剩余。[官方说明](https://www.kimi.com/help/kimi-api/api-overview)

## 智谱 / GLM

- **已确认：**通用 GLM API 使用 Bearer API Key；Coding Plan 使用专属 Key 和专属 OpenAI 兼容 base URL `https://open.bigmodel.cn/api/coding/paas/v4`（另有 Anthropic 端点）。Coding Plan Key 与平台其他 API Key 不通用。[Coding Plan 快速开始](https://docs.bigmodel.cn/cn/coding-plan/quick-start)
- **错误信号不是查询接口：**官方错误码把“账户余额已用完”和“GLM Coding Plan 套餐已到期”列为调用错误情形；它们只适合作为失败状态提示，不能反推出当前余额或 5h/7d 配额。[官方错误码](https://docs.bigmodel.cn/cn/faq/api-code)
- **未确认/不接入：**未发现官方公开的余额、账户累计 usage 或 GLM Coding Plan 剩余窗口查询 API。普通请求响应的 usage 最多用于本工具观测统计；不得伪造账户级/订阅级数据。待官方发布正式接口后再增加连接器。

## CC Switch（可选来源）

- CC Switch 的官方开源仓库发布说明确认其有“官方订阅额度、余额”和托盘缓存用量展示，也说明托盘刷新会节流且仅限当前可见应用，以减少上游调用。[官方发布说明](https://github.com/farion1231/cc-switch/releases)；[官方源码仓库](https://github.com/farion1231/cc-switch)
- 但截至调研日，未发现官方承诺的稳定本地 HTTP/IPC API、SQLite schema 或可供第三方读取的 5h/7d 数据格式。因此**不读取其数据库、会话或凭据，不把它作为运行依赖**；这也符合项目的只读、可选集成边界。
- 产品策略：检测到 CC Switch 后可在 UI 标明“来自 CC Switch 的缓存/展示数据（非本项目直接向厂商查询）”，并优先展示其未来公开、稳定的只读接口；没有该接口时，让用户自行配置已确认的原生连接器。刷新与过期语义仍由本项目统一处理。

## 连接器安全与刷新规则

- 凭据只存操作系统凭据库；不得进入 Workbench 数据库、迁移、日志、诊断 payload、CC Switch 数据库或任何导出。
- 余额、套餐额度、账户历史用量、会话观测用量必须作为不同 `kind` 保存并分别标注来源、币种、读取时间和过期状态。
- 没有厂商专属刷新限制时，采用已确认的产品策略：运行中 15 分钟刷新、允许手动刷新；失败保留上次成功值并标记过期，首次失败显示未连接/不可用，不显示为零。
