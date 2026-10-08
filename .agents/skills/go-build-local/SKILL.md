---
name: go-build-local
description: 在当前宿主构建仅供本机试跑的 Go 二进制，不升级为发布候选，也不触发提交、发布日志、候选目录或 E2E。
---

# 构建本地试跑二进制

为开发中的 Go 服务生成一个明确非发布、非候选的本机二进制。用户只说“构建”“本地跑一下”“先编一个试试”或“本地二进制”，且没有明确提出发布、候选、分发或交付时，使用本 Skill；不得把该意图升级为 `$go-prepare-release` 或 `$go-build-release`。

## 工作流程

1. 读取根 `go.mod` 的模块路径与 `go` 指令，要求其对应产品版本事实存在且当前宿主具备 Go 工具链；缺失、无法解析或与请求冲突时停止，不从旧对话、目录名或当前宿主猜测。要求项目根是独立 Git 顶层目录且存在可解析 HEAD。记录 HEAD 与 `git status --porcelain=v1 --untracked-files=all` 是否为空；允许从 dirty 工作树生成本地试跑二进制，但必须在结果中明确列出 `sourceTreeState: dirty` 和不可复现风险，不得自动暂存、提交、清理或改写用户变化。
2. 本地试跑不进入发布流程：不得调用 `$go-prepare-release`，不得生成、读取、校验或改写 `release-notes.json`，不得创建、刷新或写入项目根 `release/`，不得生成候选 manifest、Changelog、Product Status、Work Plan 或 Verification，也不得计算或提升版本。
3. 初始化后的构建不做例行环境预检。先用当前环境运行真实命令；只有命令已经失败且脱敏诊断明确指向受管 Git 或 Go 工具链缺失或不兼容时，才调用 `$go-check-development-environment` 的精确恢复路线并重试原失败命令一次。代码、测试、依赖解析、网络或配置错误不得伪装成环境问题。
4. 打包前运行全部非空单元测试。先用 `go test ./... -list '.*'` 或等价方式确认至少发现一个测试，再运行 `go test ./... -race`。不得自动追加格式、lint、全仓治理、冒烟或 E2E。
5. 在当前宿主原生执行一次未签名的本地构建，禁止交叉编译其他目标，也禁止 `-ldflags` 注入发布版本：

   ```text
   go build -trimpath -o bin/<product>-local ./cmd/server
   ```

   从真实构建输出确认唯一二进制路径，不猜测产品名。不得启动服务、安装二进制、请求管理员权限或写入系统目录；真实运行和交互测试需要用户另行明确请求，并进入适用的 E2E/验收边界。
6. 报告真实命令、测试数量、HEAD、`sourceTreeState`、二进制绝对路径、大小和 SHA-256，并固定标注 `artifactPurpose: local-run-test`、`releaseCandidate: false`、`signingStatus: unsigned`、`E2E: Not run`、`runtimeVerification: Not run`。不得使用 `pending`/`accepted` 候选状态，不得声称可发布、可分发、已安装、已验收或已验证运行时。

## 边界

- 本 Skill 不询问 E2E 开/关；该选择只属于明确的发布候选流程。
- 本 Skill 不授权 Git 提交、签名、上传、发布、安装或运行。构建成功只表示得到了本机未签名二进制。
- 用户明确要求“发布候选”时转到 `$go-build-release`；用户明确要求“准备并构建发布”时转到 `$go-prepare-release`，不得把普通本地试跑称为任务升级。
