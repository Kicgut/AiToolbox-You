## 下面用一个具体场景说明“Profile 复制与设备交接”的完整流程。

  先强调：这是规划中的 Phase 5 能力，目前还没有正式实现；它是“一次性复制和交接”，不是两台设备持续双向同步。

  ## 场景

  你正在开发一个名为 MyApp 的应用，有两台电脑：

  设备 A：办公室台式机
  代码目录：E:\Projects\MyApp
  Codex Profile：codex-work
  会话：实现登录功能

  设备 B：家用笔记本
  代码目录：D:\Projects\MyApp
  Codex Profile：codex-home

  你白天在设备 A 上工作，晚上想在设备 B 上继续同一项任务。

  这里涉及两种内容：

   内容             迁移方式
  ━━━━━━━━━━━━━━━  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
   项目代码         Git commit/push/pull
  ───────────────  ─────────────────────────────────
   AI 会话上下文    Workbench 的 Profile 复制与交接

  Workbench 不会用会话复制代替 Git。代码和会话必须分别处理。

  ———

  # 一、白天在设备 A 开发

  你在设备 A 中打开：

  E:\Projects\MyApp

  然后通过 codex-work Profile 启动 Codex。

  这次会话可能包含：

  用户：为 MyApp 实现登录功能。
  Codex：分析了前后端结构。
  Codex：修改 auth.py、LoginView.vue。
  Codex：运行 pytest，发现两个测试失败。
  用户：先不要继续，晚上我换电脑处理。

  此时有两个事实：

  1. 代码修改存在于 E:\Projects\MyApp。
  2. AI 对话存在于设备 A 的 Codex 原生会话文件中。

  例如：

  C:\Users\You\.codex-work\sessions\2026\07\23\session-abc.jsonl

  Workbench 会把它索引为：

  ConversationFamily: MyApp 登录功能
  └── SessionCopy A
      tool: Codex
      profile: codex-work
      device: 办公室台式机
      native_session_id: abc
      transcript: session-abc.jsonl

  ———

  # 二、先交接代码

  离开办公室前，需要先处理项目代码。

  例如：

  git status
  git add app/auth.py frontend/LoginView.vue tests/test_auth.py
  git commit -m "wip: implement login flow"
  git push origin feature/login

  也可以使用临时分支：

  feature/login-handoff

  这样设备 B 才能获得与 AI 会话描述相匹配的代码状态。

  如果只复制 AI 会话而没有推送代码，设备 B 上的 Codex 会看到对话中提到了 auth.py 的修改，但本地代码却不存在这些变化，后续判断很容易出错。

  ———

  # 三、在设备 A 发起“复制并交接”

  你在 Workbench 中打开这场会话，选择：

  复制到其他设备/Profile

  选择：

  源设备：办公室台式机
  源 Profile：codex-work
  源会话：MyApp 登录功能

  目标设备：家用笔记本
  目标 Profile：codex-home
  操作模式：复制并交接

  Workbench 会显示交接摘要：

  源工具：Codex
  目标工具：Codex
  源项目：E:\Projects\MyApp
  目标项目：D:\Projects\MyApp
  Git 仓库：同一个 remote
  源分支：feature/login
  目标会话处理：创建新副本
  源会话处理：保留，不删除

  注意：“交接”不会删除或锁死源会话。

  它表达的是：

  > 复制完成后，建议把设备 B 作为新的活动写入位置，不要继续在设备 A 的原会话中追加内容。

  ———

  # 四、Workbench 执行复制前检查

  正式复制之前，Workbench 应执行一系列安全检查。

  ## 1. 检查源会话

  检查内容包括：

  - 源文件是否存在
  - 原生 Session ID 是否可识别
  - 会话最后一行是否完整
  - 文件是否仍在被 Codex 写入
  - 文件大小、mtime 和内容哈希
  - 会话当前是否存在 Workbench writer lease

  例如记录：

  source_hash: 73ac...
  source_mtime: 2026-07-23 18:02:13
  source_size: 428 KB

  如果 Codex 仍在生成回复，Workbench 不会立即复制，而是等待当前 Turn 完成或要求你先中止。

  ## 2. 检查目标 Profile

  确认：

  - codex-home 是真实有效的 Codex Profile
  - 目标会话目录可用
  - 目标没有同名冲突
  - 目标 Codex 版本具备读取该会话的能力
  - 没有其他迁移任务正在写入目标目录

  ## 3. 检查代码关联

  Workbench 会比较源项目和目标项目，例如：

  源仓库 remote：
  github.com/example/MyApp.git

  目标仓库 remote：
  github.com/example/MyApp.git

  并提示目标设备应检出：

  feature/login
  commit: a92f31c

  Workbench 可以检查这些信息，但不应默认替你提交或推送代码。

  ## 4. 隐私提示

  即使都是 Codex，也需要显示会话内容将复制到哪个 Profile。

  例如：

  本次操作将把完整会话内容复制到：
  设备：家用笔记本
  Profile：codex-home

  会话可能包含：
  - 用户 Prompt
  - AI 回复
  - 文件路径
  - 命令输出
  - 代码 Diff
  - 项目名称

  如果目标 Profile 使用不同账号或 Provider，提示需要更加明确。

  ———

  # 五、将会话传输到设备 B

  Workbench 不应该直接跨网络修改另一个 Workbench 实例，而需要一个明确、可审计的传输方式。

  一种可能的流程是生成迁移包：

  myapp-login-handoff.zip
  ├── manifest.json
  ├── transcript.jsonl
  ├── metadata.json
  ├── checksums.json
  └── README.txt

  其中不包含：

  - Codex 登录凭据
  - API Key
  - OAuth Token
  - Cookie
  - 完整环境变量
  - Profile 的认证文件

  迁移包只包含完成会话复制所需的数据和校验信息。

  传输可以由用户通过以下方式完成：

  - 加密 U 盘
  - SSH/SCP
  - 用户自己的加密云盘
  - 局域网安全传输
  - 未来专门设计的设备传输机制

  “复制与交接”不意味着 Workbench 自动建设一个互联网同步服务器。

  ———

  # 六、设备 B 导入会话

  回家后，你在设备 B 上先同步代码：

  cd D:\Projects\MyApp
  git fetch origin
  git switch feature/login
  git pull

  Workbench 检查当前代码状态：

  目标仓库：MyApp
  当前分支：feature/login
  当前 commit：a92f31c
  与交接清单匹配：是

  然后导入迁移包，选择目标：

  工具：Codex
  Profile：codex-home
  目标项目：D:\Projects\MyApp
  操作：创建新副本

  Workbench 不会直接覆盖已有会话，而是先创建备份并准备临时文件：

  Workbench backups/
  └── migration-20260723-001/

  临时文件：
  session-abc.importing.jsonl

  写入流程应当是：

  验证迁移包哈希
          ↓
  转换设备相关路径
          ↓
  写入临时文件
          ↓
  flush / fsync
          ↓
  再次检查目标目录状态
          ↓
  原子移动为正式文件
          ↓
  重新索引
          ↓
  让 Codex 只读验证能否识别

  只有全部通过，导入才算成功。

  ———

  # 七、处理设备路径差异

  源会话可能出现：

  E:\Projects\MyApp

  但设备 B 使用：

  D:\Projects\MyApp

  这里不能无脑替换会话中的所有文本。

  Workbench 应当区分：

  1. 会话元数据中的工作目录

     可以映射为设备 B 的目录。

  2. AI 回复中的普通历史文本

     应保留原文，不能把历史对话内容静默篡改。

  3. 工具事件中的绝对文件路径

     可以保存原始路径，同时增加目标路径映射。

  例如：

  original_cwd: E:\Projects\MyApp
  target_cwd: D:\Projects\MyApp
  repository_identity: github.com/example/MyApp.git

  这样既保留历史真实性，又能让目标工具从正确目录继续。

  ———

  # 八、导入后形成两个会话副本

  导入成功后，Workbench 的统一模型变成：

  ConversationFamily：MyApp 登录功能
  ├── SessionCopy A
  │   device: 办公室台式机
  │   profile: codex-work
  │   status: handoff_source
  │   head_hash: 73ac...
  │
  └── SessionCopy B
      device: 家用笔记本
      profile: codex-home
      status: active
      copied_from: SessionCopy A
      head_hash: 73ac...

  此时两个副本内容一致：

  divergence_status = in_sync

  但它们不是同一个联网同步文件，而是两个独立物理副本。

  ———

  # 九、在设备 B 继续开发

  你在设备 B 打开 SessionCopy B，点击“继续”。

  Workbench 通过 codex-home Profile 调用 Codex：

  resume_session(SessionCopy B)

  然后你发送：

  继续处理昨天剩下的两个登录测试失败问题。
  先检查当前 Git commit 与交接时是否一致。

  Codex 能看到之前的历史，并在设备 B 的项目目录中继续工作。

  随后产生新内容：

  SessionCopy B
  ├── 原有历史
  ├── 用户：继续处理测试失败
  ├── Codex：检查当前代码
  ├── Codex：修复测试
  └── pytest：全部通过

  这时 B 比 A 多出后续事件：

  SessionCopy A: 原始交接点
  SessionCopy B: 原始交接点 + 新事件

  divergence_status = ahead

  准确地说，是 B 相对 A 领先。

  ———

  # 十、第二天回到设备 A

  第二天回办公室后，有两种合理选择。

  ## 选择一：继续在设备 B 对应的活动副本工作

  把设备 B 上的最新代码推送：

  git add .
  git commit -m "fix login tests"
  git push origin feature/login

  设备 A 拉取代码：

  git pull

  如果还要在设备 A 继续相同 AI 上下文，则执行一次新的反向交接：

  源：设备 B / codex-home / SessionCopy B
  目标：设备 A / codex-work
  操作：复制并交接

  完成后产生新副本，或者在经过严格验证后替换先前的非活动副本。

  首版更安全的方式是创建新副本，不直接覆盖旧副本。

  ## 选择二：只同步代码，不复制最新 AI 会话

  你也可以仅拉取 Git 代码，然后在设备 A 新建一场会话：

  代码已经包含设备 B 的修改
  但新 Codex 会话不继承完整历史

  可以给新会话一段简短交接说明：

  登录功能已完成，当前分支为 feature/login。
  最新 commit 为 b31d8a2。
  请重新检查相关代码和测试。

  这种方式更简单，但会失去完整 AI 对话上下文。

  ———

  # 十一、如果两台设备同时继续原会话

  假设交接后，你本应只在设备 B 继续，但设备 A 上又有人继续了 SessionCopy A。

  设备 A 新增：

  请重新设计登录页面。

  设备 B 新增：

  请修复登录接口测试。

  此时：

  共同历史
  ├── 设备 A：重新设计登录页面
  └── 设备 B：修复登录接口测试

  Workbench 会判断：

  divergence_status = diverged

  不会自动合并成：

  重新设计页面
  然后修复接口测试

  因为仅凭时间戳无法知道两条分支的正确语义顺序，而且两边对应的代码也可能不同。

  Workbench 应当提供：

  - 查看共同前缀
  - 查看 A 新增内容
  - 查看 B 新增内容
  - 选择某一个副本继续
  - 从其中一个副本再创建 Fork
  - 手动整理交接摘要

  但不做自动双向会话合并。

  ———

  # 十二、不同 Profile 但在同一设备的例子

  Profile 复制并不一定跨设备。

  例如同一台电脑上：

  Profile A：codex-personal
  Profile B：codex-company

  你想把个人 Profile 中的会话复制到公司 Profile。

  流程仍然类似：

  选择源会话
      ↓
  确认目标 Profile
      ↓
  提示内容将暴露给公司账号/Provider
      ↓
  检查源文件和目标目录
      ↓
  创建目标副本
      ↓
  验证目标 Codex 可以读取
      ↓
  从目标 Profile 继续

  这类操作的隐私风险甚至可能比跨设备更高，因为它涉及不同账号或组织的数据边界。

  例如原会话中包含个人项目代码，就不应该未经确认复制到公司 Profile。

  ———

  # 十三、Codex 转 Claude 的情况

  假设：

  源：设备 A / Codex / codex-work
  目标：设备 B / Claude / claude-home

  这不是简单复制原生文件，因为 Claude 无法直接把 Codex JSONL 当成原生 Claude 会话。

  可能采用的是“导入上下文”模式：

  Codex 原生会话
          ↓
  Workbench 统一事件模型
          ↓
  生成经过选择和脱敏的交接上下文
          ↓
  通过 Claude 正式接口建立新的 Claude 会话

  例如生成：

  项目：MyApp
  目标：完成登录功能
  已完成：
  - 登录接口
  - 登录页面基础实现

  待处理：
  - 两个测试失败

  关键决策：
  - 使用 JWT
  - Refresh token 存在 HttpOnly Cookie

  相关文件：
  - app/auth.py
  - frontend/LoginView.vue

  源会话：
  Codex Session abc

  然后用这份交接上下文启动新的 Claude 会话。

  此时不会声称“Claude 原生续接了 Codex 会话”，而应表示：

  Claude Session B
  relation: imported_from Codex Session A

  跨工具导入风险更高，因此架构计划中会比同工具复制更晚开放。

  ———

  # 十四、完整操作时间线

  整个跨设备开发流程可以概括为：

  设备 A 开发
      ↓
  提交并推送代码
      ↓
  冻结当前 AI Turn
      ↓
  生成会话迁移包
      ↓
  记录源哈希和 Git commit
      ↓
  安全传输到设备 B
      ↓
  设备 B 拉取相同代码 commit
      ↓
  导入到目标 Profile
      ↓
  验证目标工具能读取
      ↓
  将设备 B 标记为活动副本
      ↓
  设备 B 继续开发
      ↓
  提交并推送新代码
      ↓
  需要换回设备 A 时再次执行交接

  最重要的规则是：

  > Git 管代码，Workbench 管 AI 会话上下文；每次交接都确定一个新的活动写入位置，不进行持续双向原生文件同步。

  这样既能让你在不同设备和 Profile 上延续开发上下文，也能避免两台设备同时修改同一个逻辑会话后被错误自动合并。

## 原生和本项目

 你的理解方向是对的。需要明确区分：

  - 原生会话复制：真正让目标 Codex/Claude 能够继续会话。
  - 本项目统一会话模型：用于识别、比较、校验、记录关系和展示，不替代原生会话。
  - Profile：本项目的统一抽象，底层对应一个真实的 Codex/Claude 配置环境。
  - 登录凭据/API Key：始终留在各自设备和目标 Profile，不随会话传播。

  ## 1. 原生会话如何跨设备或 Profile 交接

  ### Codex → Codex

  这是 Phase 5 计划中相对明确的场景，例如：

  源设备 A
  CODEX_HOME = C:\AIProfiles\codex-work

  目标设备 B
  CODEX_HOME = D:\AIProfiles\codex-home

  源设备有一个 Codex 原生会话：

  C:\AIProfiles\codex-work\sessions\...\rollout-abc.jsonl

  交接并不是只把本项目数据库里的统一事件复制过去，而是最终要让目标 Codex 能识别真实的 Codex 原生会话。

  计划中的流程是：

  源 Codex 原生会话
          ↓
  本项目读取并建立统一索引
          ↓
  确认源 SessionCopy、共同前缀、事件哈希
          ↓
  复制/调整 Codex 原生 rollout 文件
          ↓
  更新目标 CODEX_HOME 的 session_index.jsonl
          ↓
  通过目标 Codex App Server/CLI 只读验证
          ↓
  目标 Codex 可以 list/read/resume

  也就是说，真正交给目标 Codex 的仍然是 Codex 自己可以识别的原生数据。

  本项目的统一会话模型会参与整个过程，但它主要负责：

  - 确定复制的是哪个物理会话
  - 识别源和目标是否已经有同一会话
  - 比较共同事件前缀
  - 判断 in_sync/ahead/diverged
  - 计算内容哈希
  - 保存迁移关系
  - 记录源副本和目标副本的 lineage
  - 迁移后重新索引和校验
  - 在 UI 中展示“已交接”

  它不是目标 Codex 的运行格式。

  ### 更准确的数据路径

  源 Codex 原生文件
          │
          ├──→ Workbench 统一模型
          │    用于识别、预检、哈希、比较、审计
          │
          └──→ Codex 原生复制/转换流水线
                       ↓
               目标 Codex 原生文件
                       ↓
               目标 Codex 读取验证

  不是：

  Workbench 统一 Event
          ↓
  随便重新拼成 Codex JSONL

  因为从统一模型反向重建原生文件可能丢失未知字段、工具状态、内部元数据和版本信息。

  所以同工具迁移应当尽量保留原始原生记录，只在经过验证时修改必须修改的字段，例如目标 model_provider 或索引信息。

  ———

  ## 2. 统一会话模型是否是交接的中间格式

  是“中间管理模型”，但不一定是“文件传输格式”。

  它参与：

  发现 → 识别 → 预检 → 比较 → 迁移计划
  → 迁移后验证 → 建立副本关系 → 分叉检测

  但实际写入目标 Profile 时，使用的是目标工具能够识别的原生格式或官方导入接口。

  如果未来 Codex 提供官方安全导入 API，设计要求优先使用官方 API：

  源原生会话
      ↓
  Workbench 迁移计划
      ↓
  Codex 官方 import/clone API
      ↓
  目标原生会话

  只有官方导入能力不存在时，才考虑经过严格验证的文件级复制。

  ———

  ## 3. 跨设备如何传输文件

  目前 Phase 5 尚未实施，而且设备之间的具体传输通道还没有最终确定。

  之前举例的 ZIP 迁移包是一种可能方案，不是已经确认的唯一架构。

  无论最终采用：

  - 本地迁移包
  - SCP/SSH
  - 用户指定目录
  - 加密存储介质
  - 未来的设备传输机制

  都必须满足：

  只传会话所需数据
  不传认证信息
  有 manifest 和哈希
  目标写入前备份
  写入后让目标 CLI 验证
  失败可以回滚

  本项目不会默认建设一个云端账号同步服务器。

  ———

  ## 4. Claude → Claude 是否相同

  原则相同，但当前没有承诺一定能安全实现。

  Phase 5 明确要求先验证：

  - Claude Session ID 的语义
  - 项目目录编码
  - CLAUDE_CONFIG_DIR 隔离方式
  - resume 搜索范围
  - 附件引用
  - Subagent 记录
  - File history
  - 权限引用
  - 目标 Claude CLI 能否通过官方方式恢复

  如果验证结果是：

  只复制原生文件无法可靠 resume

  那么项目必须明确宣布：

  暂不支持 Claude 跨 Profile 原生会话复制

  而不是猜测性修改 Claude 的内部文件。

  因此当前规划是：

   交接类型                          规划状态
  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  ━━━━━━━━━━━━━━━━━━━━━━━━
   Codex → Codex，不同 CODEX_HOME    明确计划实现
  ────────────────────────────────  ────────────────────────
   Codex → Codex，跨设备             建立在同一迁移流水线上
  ────────────────────────────────  ────────────────────────
   Claude → Claude                   先做可行性验证
  ────────────────────────────────  ────────────────────────
   Codex → Claude                    不是原生会话复制
  ────────────────────────────────  ────────────────────────
   Claude → Codex                    不是原生会话复制

  ———

  ## 5. Codex → Claude 能否“交接原生会话”

  不能按“原生会话复制”理解。

  Codex 和 Claude 的原生格式不同：

  Codex rollout JSONL ≠ Claude session JSONL

  Claude 不会原生 resume 一个 Codex Session ID。

  未来如果支持跨工具交接，应该表示为：

  Codex SessionCopy A
          ↓
  提取经过选择的上下文
          ↓
  在 Claude 中创建新的原生会话 B
          ↓
  记录 imported_from 关系

  结果是：

  Claude 会话 B imported_from Codex 会话 A

  而不是：

  Claude 续接了 Codex 原生会话 A

  目标 Claude 只会把它当作一个新 Claude 会话，只是初始上下文来自 Codex 历史。

  ———

  # 6. codex-work 和 codex-home 是什么

  它们是示例显示名称，属于本项目的 ToolProfile 记录。

  例如：

  ToolProfile:
    display_name: codex-work
    tool: codex
    config_root: C:\AIProfiles\codex-work
    session_root: C:\AIProfiles\codex-work\sessions

  以及：

  ToolProfile:
    display_name: codex-home
    tool: codex
    config_root: D:\AIProfiles\codex-home
    session_root: D:\AIProfiles\codex-home\sessions

  codex-work、codex-home 不是要求 Codex 原生必须存在这两个名字。

  更准确地说：

  > Profile 是本项目对“一套独立 Codex/Claude 配置与会话环境”的统一称呼。

  底层环境是真实存在的，例如不同的：

  CODEX_HOME
  CLAUDE_CONFIG_DIR
  配置文件
  原生会话目录
  已登录账号状态
  Provider 配置
  工具能力

  本项目给它建立一个名字和数据库记录，方便统一管理。

  ———

  ## 7. Codex 原生有没有 Profile

  不能简单回答“完全没有”，但本项目的 ToolProfile 不等于 Codex 某个固定的原生 Profile 文件。

  在本项目设计里，Codex Profile 主要表示：

  一个独立的 CODEX_HOME 环境

  例如：

  $env:CODEX_HOME = "C:\AIProfiles\codex-work"
  codex

  另一次：

  $env:CODEX_HOME = "C:\AIProfiles\codex-personal"
  codex

  这两次 Codex 运行会读取不同的配置、认证状态和会话目录。

  Workbench 将它们统一登记成两个 ToolProfile：

  codex-work
  codex-personal

  因此：

  - 独立的 Codex 环境是真实的。
  - codex-work 这个人类可读名称主要由本项目管理。
  - 本项目不会声称 Codex 原生一定存在一个同名的 Profile 对象。

  Claude 也是类似：

  不同 CLAUDE_CONFIG_DIR
          ↓
  Workbench 中不同 ToolProfile

  ———

  # 8. 登录凭据和 API Key 会不会随交接传播

  不会，而且架构明确禁止。

  不应该复制的内容包括：

  - Codex 登录凭据
  - Claude 登录凭据
  - API Key
  - OAuth Token
  - Cookie
  - 完整环境变量
  - CC Switch Provider 密钥
  - Cockpit Tools 账号文件
  - 系统凭据存储内容

  设备 B 的目标 Profile 必须提前独立完成登录或配置。

  例如：

  设备 A / codex-work
  登录账号：company@example.com

  设备 B / codex-home
  登录账号：personal@example.com

  交接操作只复制会话内容，不复制：

  company@example.com 的登录状态

  目标 Codex 会使用设备 B 上 codex-home 已经存在的认证状态继续运行。

  ———

  ## 9. 如果目标 Profile 没有登录怎么办

  迁移可以分成“复制成功”和“能够继续运行”两种状态。

  例如：

  原生会话文件复制成功
  目标 Codex 能只读列出会话
  但目标 Profile 没有有效认证

  此时可以显示：

  会话已导入，但目标 Profile 尚未具备执行能力。
  请在目标设备通过 Codex 自身登录流程完成认证。

  Workbench 不会替你从源设备提取凭据，也不会偷偷复制认证文件。

  只有用户通过目标工具自己的正式登录方式完成认证后，才能执行 resume。

  ———

  ## 10. 不同账号继续同一会话意味着什么

  假设：

  源 Profile：
  codex-work
  公司账号

  目标 Profile：
  codex-home
  个人账号

  如果把源会话复制到目标 Profile 后继续，后续 Prompt 和相关历史上下文可能发送给个人账号对应的 Provider。

  因此迁移前必须明确提示：

  源账号/Provider：公司账号
  目标账号/Provider：个人账号

  本次操作可能使目标 Provider 接触：
  - 历史 Prompt
  - AI 回复
  - 代码片段
  - 文件路径
  - 命令输出
  - Diff

  用户确认后才能继续。

  但实际的公司账号 Token 不会发送到设备 B。

  传播的是“会话内容”，不是“源账号身份凭据”。

  ———

  # 11. Profile 记录会保存哪些内容

  本项目计划保存：

  tool
  display_name
  config_root
  session_root
  provider
  account_ref
  discovery_source
  capabilities_json
  enabled
  last_probe_at

  其中 account_ref 只是归属标识，例如：

  公司 Codex
  个人 Claude
  账号未知

  它不应保存：

  API Key
  OAuth Token
  Cookie
  认证文件内容

  账号归属还会带可信度：

  exact
  likely
  unknown

  例如，历史会话没有足够证据时，只显示“账号未知”，不会为了提高识别率去读取明文 Token。

  ———

  # 12. 最准确的交接结构

  设备 A
  ┌─────────────────────────────┐
  │ Codex 原生环境              │
  │ CODEX_HOME A                │
  │ 配置、认证、原生会话 A      │
  └─────────────┬───────────────┘
                │
                │ 只读取会话，不读取/传播凭据
                ▼
  ┌─────────────────────────────┐
  │ Workbench                   │
  │ ConversationFamily          │
  │ 哈希、迁移计划、审计、关系  │
  └─────────────┬───────────────┘
                │
                │ 复制经过确认的原生会话内容
                │ 不复制认证和账号文件
                ▼
  设备 B
  ┌─────────────────────────────┐
  │ Codex 原生环境              │
  │ CODEX_HOME B                │
  │ 设备 B 自己的配置和认证     │
  │ 新的原生会话副本 B          │
  └─────────────┬───────────────┘
                │
                ▼
  ┌─────────────────────────────┐
  │ Workbench                   │
  │ ToolProfile B               │
  │ SessionCopy B               │
  │ copied_from A / 已交接       │
  └─────────────────────────────┘

  ## 最终结论

  1. 跨设备/Profile 交接最终复制的是目标工具能够识别的原生会话，而不是只复制本项目的统一数据库记录。
  2. 统一会话模型会参与识别、比较、预检、哈希、分叉判断、迁移关系和验证，但不应作为反向重建原生会话的唯一数据源。
  3. codex-work 和 codex-home 是本项目中的 Profile 显示名称，底层分别指向真实的独立 CODEX_HOME 环境。
  4. 本项目的 Profile 是统一管理抽象，不等于 Codex 必须具有的某个同名原生 Profile 对象。
  5. 登录凭据、API Key、OAuth Token、Cookie 和认证文件不会随会话复制。
  6. 目标设备/Profile 必须使用自己的认证状态。会话内容可以交接，账号身份不能交接。
  7. Codex → Codex 原生复制是明确规划；Claude → Claude 必须先验证；Codex ↔ Claude 只能视为上下文导入并创建新会话，不能称为原生续接。

## 原生会话管理和本项目会话交接

  • 1. 交接范围

  当前架构设计的基本操作单位是“某一个物理会话副本 SessionCopy”，不是默认迁移某账号全部会话，也不是默认迁移某项目全部会话。

  也就是用户明确选择：

  源 Profile
  → 某个具体会话
  → 目标 Profile
  → copy / fork / 交接

  未来可以增加批量选择，例如筛选某个项目后勾选多个会话，但“账号全部迁移”和“项目全部迁移”目前没有确定，且不应默认执行。

  2. Codex、Claude 如何区分会话

  - Codex：主要通过原生 Session/Thread ID 区分会话，同时记录 cwd、项目和时间等元数据。会话存放于相应 CODEX_HOME 的会话目录。账号/Provider 属于运行配置和认证环境，历史会话通常没有可靠的账号归属信息。
  - Claude Code：主要通过 Session ID 区分会话，并按项目路径编码后的目录组织 JSONL，因此项目目录关联更明显。账号/API Provider 同样主要来自当前 Claude 配置和运行环境，不是会话身份本身。

  会话身份 = Session ID + 原生文件
  项目关联 = cwd / 项目目录
  账号归属 = 当前配置环境或启动证据，历史记录可能无法确定

  3. Claude → Claude 可以参考 CC Switch 吗

  可以，而且这是很有价值的参考方向。

  CC Switch 的做法本质上不是给不同账号复制一套会话，而是把“本地会话文件”和“当前 Provider/API 认证配置”分开：

  - Claude 会话仍保存在本地会话目录。
  - 切换账号/API 时，CC Switch 修改 Claude 的 settings.json 中的 API Key、Base URL 等运行配置。
  - 恢复会话时，CC Switch扫描本地 Claude 会话、取得 Session ID，然后在对应或用户重新选择的项目目录中启动 Claude 恢复命令。CC Switch 会话管理器
    (https://github.com/farion1231/cc-switch/blob/main/docs/user-manual/zh/3-extensions/3.4-sessions.md)

  - Claude 配置目录和 Provider 配置是独立管理的。CC Switch 配置说明 (https://github.com/farion1231/cc-switch/blob/main/docs/user-manual/en/5-faq/5.1-config-files.md)

  这说明同一台设备、同一个 Claude 会话目录下，切换不同账号/API 后，通常可以尝试继续访问相同本地会话，因为认证配置和会话存储是分离的。

  对本项目的启发是：

  复制 Claude 原生会话到目标配置目录
          ↓
  不复制源账号/API Key
          ↓
  使用目标 Profile 已有的账号/API 配置
          ↓
  调用目标 Claude CLI resume
          ↓
  验证是否能够读取和继续

  但跨设备仍需要复制对应的 Claude 原生会话文件；CC Switch 的 Provider 切换本身不等于跨设备会话复制。另外附件、子代理、文件历史和项目路径是否完整可迁移，仍需要 Phase 5 实测后才能确认。


## 切换账号看不到 

那为什么当我使用codex-cli时，登录不同账号或者切换别的api，在相同目录下启动codex时，resume看不到其他账号的会话，据说会通过model_provider区分，这种区分是codex存储会话时就区分，还是codex加载时？

ccswitch有一个历史会话统一功能，介绍如下：统一 Codex 会话历史 开启后，官方订阅将以共享的 custom 供应商标识运行，官方与第三方会话出现在同一历史列表中，并可选择把现有官方会话一并迁入（迁移前自动备份）。关闭开关时可按备份恢复迁入的会话。注意：跨供应商继续旧会话时，对方后端可能无法解密会话中的 encrypted_content 推理内容，导致继续失败


• 我会以你补充的这段真实功能说明为准，核对 Codex 与 CC Switch 源码后解释其原理；不修改项目。


• 这是“写入时记录归属 + 加载时按归属过滤”两部分共同造成的。

  ## 1. model_provider 在什么时候生效

  Codex 创建会话时，就会把当时的 model_provider 写入：

  - 原生 rollout JSONL 第一条 session_meta.model_provider
  - ~/.codex/state_5.sqlite 的 threads.model_provider

  例如：

  会话 A：model_provider = openai
  会话 B：model_provider = azure
  会话 C：model_provider = my-api

  之后运行 codex resume 时，Codex 加载会话列表还会按“当前激活的 model_provider”过滤。甚至 resume --all 在部分版本中也只是忽略项目目录限制，并没有忽略 Provider 限制。因此文件仍在磁盘上，只是列表隐藏了。Codex Issue #19318
  (https://github.com/openai/codex/issues/19318)

  所以答案是：

  存储时：记录 model_provider
  加载列表时：按当前 model_provider 过滤
  恢复会话时：还要决定实际使用哪个 provider

  这是三个相关但独立的环节。

  ## 2. 为什么切换账号也可能看不到

  如果相同 CODEX_HOME、相同 model_provider=openai，理论上仅更换认证账号不应该删除本地文件。但仍可能出现：

  - CC Switch 为不同 API 生成了不同的 model_provider ID。
  - state_5.sqlite 中线程被记录到了不同 Provider 桶。
  - 当前 Codex/App Server 列表请求默认带了 Provider 过滤。
  - 会话可见，但换账号后原有 encrypted_content 无法被新账号/后端解密，导致无法继续。
  - 实际切换时同时切换了 CODEX_HOME，因此读取的是另一套会话目录。

  因此“看不到”通常不等于文件消失，而是索引或列表过滤；“能看到但不能继续”则更多是 Provider、账号或加密上下文不兼容。

  ## 3. CC Switch“统一 Codex 会话历史”的原理

  它采用“把不同 Provider 统一映射到一个稳定 Provider 桶”的办法。

  开启后，CC Switch 会让官方订阅和受管第三方 API 都以：

  model_provider = custom

  这个共同标识运行。

  大致过程是：

  官方 OpenAI 会话：openai ─┐
  第三方 API 会话：api-A  ──┼→ custom
  第三方 API 会话：api-B  ──┘

  这样 Codex 执行：

  当前 provider = custom

  列表过滤时，所有被标记为 custom 的会话都会出现在同一个 resume 列表中。

  CC Switch 发布说明明确提到，它会：

  - 在 live config.toml 中把官方运行映射到共享的 custom Provider。
  - 保持官方 auth.json 不变。
  - 可选迁移已有历史。
  - 修改历史 JSONL 中的 session_meta.model_provider。
  - 修改 state_5.sqlite 中 threads.model_provider。
  - 迁移前备份，并用迁移账本支持精确恢复。CC Switch Changelog (https://github.com/farion1231/cc-switch/blob/main/CHANGELOG.md)

  因此它不是让 Codex“取消 Provider 区分”，而是把多个实际 Provider伪装/归一到同一个 Codex Provider 标识：

  Codex 看见的逻辑 Provider：custom
  CC Switch 实际路由的上游：官方账号、第三方 API A、第三方 API B

  ## 4. 切换实际 API 时如何继续路由

  custom 只是 Codex 本地会话分类标识。真正请求发送到哪里，仍由当前 config.toml、认证配置或 CC Switch 本地代理决定。

  例如：

  会话元数据：model_provider = custom
  当前 CC Switch Provider：API A
  → 请求发给 API A

  切换后：
  会话元数据：仍然是 custom
  当前 CC Switch Provider：官方订阅
  → 请求发给官方订阅

  因此历史列表统一了，但实际后端可以动态切换。

  ## 5. 为什么会有 encrypted_content 风险

  统一 model_provider 只能解决“列表可见性”，不能解决加密兼容性。

  某些推理内容由原 Provider 或账号加密：

  encrypted_content

  如果会话最初由 Provider A 产生，之后改由 Provider B 继续：

  Provider A 生成的 encrypted_content
          ↓
  发送给 Provider B
          ↓
  Provider B 没有对应密钥或上下文
          ↓
  invalid_encrypted_content / 恢复失败

  所以 CC Switch 的统一功能实际解决的是：

  - 会话在 resume 列表中的可见性
  - 不同 Provider ID 导致的历史分桶
  - Provider 切换造成的“历史消失”

  它不保证：

  - 任意 Provider 都能继续任意旧会话
  - 不同账号能解密对方的推理内容
  - 模型、工具、缓存和 Responses 协议完全兼容

  ## 6. 对本项目的启发

  本项目不能只判断“文件复制成功”，还必须分开记录：

  可发现：目标能看到会话
  可读取：目标能解析完整历史
  可恢复：目标 CLI 接受 resume
  可继续：目标后端能成功完成新 Turn

  可以参考 CC Switch 的做法统一历史列表，但不应直接把“改写为 custom”视为交接成功。更安全的流程应该是：

  备份
  → 同时修改 JSONL 和 SQLite 索引
  → 验证目标能够列出和读取
  → 检查 Provider/账号兼容性
  → 用户单独批准后进行低成本 resume 验证
  → 失败则恢复备份

  简而言之：Codex在创建会话时保存 model_provider，在列出会话时再次按当前 Provider 过滤；CC Switch通过把多个 Provider 统一改写成 custom 来消除列表分桶，但加密推理内容仍可能阻止真正的跨账号或跨 Provider续接。