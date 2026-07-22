# CC Switch Responses API 支持分析

## 概述

本文档分析了 CC Switch 工具如何处理不同 AI 编程工具的 API 格式差异，特别是 MiMo 等供应商原生支持 Responses API 后的变化。

## 背景

### API 格式差异

不同的 AI 编程工具使用不同的 API 格式：

| 工具 | API 格式 | 说明 |
|------|----------|------|
| **Codex** | OpenAI Responses API | 新一代 API，扁平化 input/output 结构 |
| **Claude Code** | Anthropic Messages API | Anthropic 原生格式 |
| **Gemini CLI** | Gemini Native API | Google 原生格式 |
| **第三方供应商** | OpenAI Chat Completions API | 传统格式，广泛兼容 |

### 核心问题

当 Codex（使用 Responses API）连接到只支持 Chat Completions API 的供应商时，需要格式转换。

## CC Switch 解决方案

### 架构设计

```
用户请求 → Codex CLI → CC Switch 本地代理 → 目标提供商
                     ↓
              Responses API 格式
                     ↓
              检测目标提供商支持的格式
                     ↓
         ┌───────────┴───────────┐
         ↓                       ↓
   支持 Responses API      只支持 Chat Completions
         ↓                       ↓
    直接透传                 格式转换
         ↓                       ↓
    返回原始响应            转换回 Responses 格式
         ↓                       ↓
         └───────────┬───────────┘
                     ↓
              返回给 Codex CLI
```

### 核心模块

CC Switch 通过 Rust 实现的本地代理服务器处理格式转换：

**源代码位置**：`cc-switch/src-tauri/src/proxy/providers/`

关键文件：
- `transform_codex_chat.rs` - Responses API → Chat Completions 转换
- `transform_responses.rs` - Chat Completions → Responses API 转换
- `streaming_responses.rs` - 流式响应转换
- `streaming_codex_chat.rs` - Chat 流式响应转换

## API 格式判断机制

### 配置文件位置

**主配置文件**：`cc-switch/src/config/codexProviderPresets.ts`

这是 CC Switch 的前端 TypeScript 代码，定义了所有供应商预设。

### 判断方式：静态配置

**关键发现**：CC Switch 使用**静态配置**，而非运行时自动检测。

```typescript
// 小米 MiMo 官方 Codex 文档已声明原生支持 Responses API
// （wire_api=responses 对自家 base_url），无需路由接管转换
apiFormat: "openai_responses",

// 阿里百炼 DashScope 原生支持 OpenAI Responses API
// （/compatible-mode/v1/responses，同一 base_url），无需路由接管转换
apiFormat: "openai_responses",

// 火山方舟主数据面 /api/v3 原生支持 Responses API
// （/api/v3/responses），无需路由接管转换
apiFormat: "openai_responses",

// 美团 LongCat 官方 Codex 文档用 wire_api=responses 对自家 base_url
// 原生 Responses，无需路由接管转换
apiFormat: "openai_responses",
```

### 判断依据来源

完全依赖供应商的**官方文档声明**：

1. **官方 Codex 配置文档**
   - MiMo: `mimo.mi.com/.../codex-configuration`
   - MiniMax: `platform.minimaxi.com/docs/token-plan/codex-cli`

2. **API 参考文档**
   - 端点定义（如 `/v1/responses`）
   - wire_api 配置声明

3. **官方公告**
   - 供应商发布支持声明
   - CC Switch 团队跟进更新

### 更新机制

**随版本发布手动更新**，不是自动检测。

从 CHANGELOG (v3.16.5, 2026-07-01) 可以看到：

```markdown
### Changed
- **Native Responses API for CN Codex Providers**: 
  几个中国供应商（Qwen/DashScope 百炼、小米 MiMo、火山方舟 Doubao、
  美团 LongCat、MiniMax CN/intl）现在暴露原生 OpenAI Responses 端点，
  所以它们的 Codex 预设切换到 `apiFormat: "openai_responses"`，
  直接到达上游，而不是通过 Responses->Chat 路由接管转换。
```

## 供应商支持状态

### 原生支持 Responses API（无需转换）

| 供应商 | 配置 | 备注 |
|--------|------|------|
| **小米 MiMo** | `apiFormat: "openai_responses"` | 官方文档声明支持 |
| **阿里百炼 DashScope** | `apiFormat: "openai_responses"` | `/compatible-mode/v1/responses` |
| **火山方舟** | `apiFormat: "openai_responses"` | `/api/v3/responses` |
| **美团 LongCat** | `apiFormat: "openai_responses"` | 官方 Codex 文档支持 |
| **MiniMax (CN/Intl)** | `apiFormat: "openai_responses"` | `/v1/responses` 端点 |
| **Qiniu (七牛)** | `apiFormat: "openai_responses"` | 聚合器支持 |
| **APINebula** | `apiFormat: "openai_responses"` | 聚合器支持 |
| **Sudocode** | `apiFormat: "openai_responses"` | 聚合器支持 |
| **APIKEY.FUN** | `apiFormat: "openai_responses"` | 聚合器支持 |

### 仅支持 Chat Completions（需要转换）

| 供应商 | 配置 | 备注 |
|--------|------|------|
| **火山方舟 Agentplan** | `apiFormat: "openai_chat"` | 旧版端点 |
| **DeepSeek** | `apiFormat: "openai_chat"` | 仅 Chat Completions |
| **智谱 GLM** | `apiFormat: "openai_chat"` | 仅 Chat Completions |
| **百度千帆** | `apiFormat: "openai_chat"` | 仅 Chat Completions |
| **Kimi** | `apiFormat: "openai_chat"` | 仅 Chat Completions |
| **StepFun** | `apiFormat: "openai_chat"` | 仅 Chat Completions |
| **SiliconFlow** | `apiFormat: "openai_chat"` | 第三方聚合器 |

## 转换逻辑详解

### Responses API → Chat Completions API

**文件**：`transform_codex_chat.rs`

```rust
fn responses_to_chat_completions(body: Value) -> Result<Value, ProxyError> {
    // 1. instructions → system message
    // 2. input array → messages array
    // 3. custom tools → function tools
    // 4. reasoning parameters 映射
}
```

**示例转换**：

```json
// Responses API 格式（Codex 发送）
{
  "model": "mimo-v2.5-pro",
  "instructions": "你是一个编程助手",
  "input": [
    {"role": "user", "content": "写一个排序算法"}
  ],
  "tools": [
    {"type": "custom", "name": "apply_patch", "input": "..."}
  ]
}

// 转换为 Chat Completions 格式
{
  "model": "mimo-v2.5-pro",
  "messages": [
    {"role": "system", "content": "你是一个编程助手"},
    {"role": "user", "content": "写一个排序算法"}
  ],
  "tools": [
    {
      "type": "function",
      "function": {
        "name": "apply_patch",
        "description": "...",
        "parameters": {...}
      }
    }
  ]
}
```

### Chat Completions API → Responses API

**文件**：`transform_responses.rs`

```rust
fn anthropic_to_responses(body: Value) -> Result<Value, ProxyError> {
    // 1. system message → instructions
    // 2. messages array → input array
    // 3. 工具定义反向转换
}
```

## 用户对话流程示例

### 场景：使用 Codex + MiMo 编写代码

#### 步骤 1：配置阶段

CC Switch 写入配置文件：

```toml
# ~/.codex/config.toml
model_provider = "custom"
model = "mimo-v2.5-pro"

[model_providers.custom]
name = "xiaomi_mimo"
base_url = "https://api.xiaomimimo.com/v1"
wire_api = "responses"
```

```json
// ~/.codex/auth.json
{
  "OPENAI_API_KEY": "sk-xxx..."
}
```

#### 步骤 2：用户发送请求

```
用户输入："写一个 Python 快速排序算法"
```

#### 步骤 3：Codex CLI 处理

```json
{
  "model": "mimo-v2.5-pro",
  "instructions": "You are MiMo, an AI assistant developed by Xiaomi...",
  "input": [
    {"role": "user", "content": "写一个 Python 快速排序算法"}
  ],
  "tools": [...],
  "stream": true
}
```

#### 步骤 4：CC Switch 代理处理

```
1. 接收请求
2. 检测配置：MiMo (apiFormat: "openai_responses")
3. 决策：原生支持，无需转换
4. 直接转发到 https://api.xiaomimimo.com/v1/responses
```

#### 步骤 5：MiMo 处理并返回

```json
{
  "id": "resp-xxx",
  "output": [
    {
      "type": "message",
      "content": [
        {
          "type": "output_text",
          "text": "def quicksort(arr):\n    if len(arr) <= 1:\n        return arr\n    pivot = arr[len(arr) // 2]\n    left = [x for x in arr if x < pivot]\n    middle = [x for x in arr if x == pivot]\n    right = [x for x in arr if x > pivot]\n    return quicksort(left) + middle + quicksort(right)"
        }
      ]
    }
  ],
  "usage": {
    "input_tokens": 45,
    "output_tokens": 128
  }
}
```

#### 步骤 6-7：透传响应并展示

CC Switch 直接将响应返回给 Codex，Codex 解析并展示代码。

## 关键优势

### 原生支持 Responses API 后的改进

1. **性能提升**
   - 减少一次格式转换，降低延迟
   - 减少 CPU 和内存开销

2. **可靠性提高**
   - 转换逻辑复杂（约 1000+ 行代码）
   - 原生支持避免转换错误
   - 减少边界情况处理

3. **功能完整**
   - 原生支持所有 Responses API 特性
   - 包括新特性无需更新转换逻辑

4. **配置简化**
   - `apiFormat: "openai_responses"` 标识符
   - CC Switch 自动跳过转换

5. **维护成本降低**
   - 无需为每个新供应商编写转换逻辑
   - 减少测试和调试工作

## 技术细节

### CodexCatalogToolProfile 枚举

```rust
/// Codex 工具表面配置
/// - `ProxyChat`: CC Switch 代理接管并转换 Responses<->Chat
///   目录保持 Codex 默认工具集（包括 freeform apply_patch）
/// - `NativeResponses`: Codex 直接连接供应商的原生 /responses 端点
///   此类网关拒绝 type=="custom" 工具，目录必须抑制 freeform apply_patch
pub enum CodexCatalogToolProfile {
    ProxyChat,
    NativeResponses,
}
```

### MiMo 特殊处理

```typescript
{
  name: "Xiaomi MiMo",
  apiFormat: "openai_responses",
  modelCatalog: modelCatalog([
    {
      model: "mimo-v2.5-pro",
      displayName: "MiMo V2.5 Pro",
      contextWindow: 1048576,
      inputModalities: ["text"],
      baseInstructions: "You are MiMo, an AI assistant developed by Xiaomi..."
    }
  ])
}
```

## 总结

| 方面 | 答案 |
|------|------|
| **配置位置** | CC Switch 自己的源代码 (`codexProviderPresets.ts`) |
| **判断机制** | 静态配置（硬编码） |
| **信息来源** | 供应商官方文档 |
| **更新方式** | 随 CC Switch 版本发布更新 |
| **运行时检测** | ❌ 没有 |
| **自动探测** | ❌ 没有 |

## 参考资料

- CC Switch GitHub: https://github.com/farion1231/cc-switch
- MiMo 官方文档: https://platform.xiaomimimo.com
- OpenAI Responses API: https://platform.openai.com/docs/api-reference/responses
- CC Switch CHANGELOG: `cc-switch/CHANGELOG.md`

## 版本历史

- **v3.16.5** (2026-07-01): 多个中国供应商切换到原生 Responses API 支持
- **v3.16.4**: 初始 Responses API 支持实现
