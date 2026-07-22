## 常用

[developers.openai.com/codex/cli/reference](https://developers.openai.com/codex/cli/reference)

codex -a never -s workspace-write

/goal

/subagents

AGENTS.md写这个类似CLAUDE.md

--dangerously-bypass-approvals-and-sandbox 跳过所有授权和沙箱限制，赋予codex完全权限

codex -h

--sandbox workspace-write

--ask-for-approval never

## 问题

.codex\config.toml和全局的config.toml写的全自动配置没用不知道为什么

实测现在是codex --sandbox workspace-write 然后/permissions选择never

### 配置了权限还是无法写入

• 已经定位到关键证据：Codex 的沙盒 ACL helper 正在以 read-acl-only mode 注入保护规则；项目配置虽然写着 sandbox_mode = "workspace-write"，但这只允许沙盒可写范围，不会覆盖平台注入的路径白名单。现在我再确认本机 CLI 是否提供
  可切换的 Windows 沙盒模式，避免盲改配置。

• 您好 yyh，你这次将直接修改架构，请确保本次修改能保证整个项目所有检测项点都能正常运行。

  已确认：这是 Codex 启动时的沙盒 ACL helper 注入的，不是项目配置造成的。

  证据：

  read-acl-only mode: applying read ACLs

  同时本机 Codex CLI 支持三种模式：

  read-only
  workspace-write
  danger-full-access

  当前项目配置：


  但 workspace-write 只允许平台分配的可写范围，当前 .agents 没有被加入该范围，所以项目配置无法覆盖它。
  codex -s workspace-write `
    --add-dir D:\Algorithm\wuhan360\.agents

  如果仍被 ACL helper 拦截，使用完整权限模式：

  codex -s danger-full-access `
    --add-dir D:\Algorithm\wuhan360

  自动化、完全跳过审批时才使用：

  codex --dangerously-bypass-approvals-and-sandbox



## 基础知识

/approve 选full（codex-cli似乎没有选择，指示查看之前允许的请求）

应该是/permissions 选full


**approval_policy策略**

untrusted

on-request

never

**sandbox_mode模式**

read-only

workspace-write 修改当前项目工作目录下的文件，这是推荐的开发模式

danger-full-access 完全权限，等于关闭沙箱


