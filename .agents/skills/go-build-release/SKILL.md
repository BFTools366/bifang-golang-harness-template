---
name: go-build-release
description: 从固定 clean HEAD 为下游 Go 产品构建可审计的发布候选，按 GOOS 与 GOARCH 交叉编译、注入版本与提交、生成相邻 SHA-256 和候选 manifest，并原子提交到 release/。用于用户明确要求构建发布候选、交叉编译发布制品或按原生矩阵构建时。
---

# 构建发布候选

只从已复核、已提交的 clean HEAD 构建候选，把结果暂存成精确文件集后原子提交到项目根 `release/`。本 Skill 不准备发布范围、不提升版本、不签名渠道发布、不运行 E2E。

## 工作流程

1. 读取产品规格、当前构建请求、`docs/AGENT_POLICY.md`、`docs/GO_WEB_TEMPLATE.md`、`docs/RELEASE.md`、`go.mod`、`Version.md` 与 `.harness/release-context.json`。要求发布范围已经由 `$go-prepare-release` 封存；缺失上下文时停止，不在本 Skill 内补写。
2. 要求用户显式请求构建候选、项目根是独立 Git 顶层，并以 `git status --porcelain=v1 --untracked-files=all` 复核工作树 clean。普通构建不自动提交；dirty 时停止并交回用户，绝不自动暂存、提交或清理用户变化。
3. 运行发布上下文校验，锁定 clean 当前 HEAD、`releaseContextSha256`、`gitPublication`、默认主分支、`expectedTag`、`releaseReview` 与 `candidateSelections`：

   ```text
   python3 .agents/skills/go-prepare-release/scripts/release_context.py verify --project-root . --expected-version <version>
   ```

   要求返回的 `sourceCommit` 等于当前 HEAD，版本等于 `$go-manage-version check --phase build` 的目标版本。上下文与 HEAD 不一致时停止。
4. 用 `$go-manage-version check --phase build` 核对版本一致性；本 Skill 不得提升、重置或回退版本，也不得改写 `release-notes.json`。
5. 按 `gitPublication` 选择路线：
   - `local`：在当前宿主本机构建，只生成当前 `GOOS`/`GOARCH` 制品，不访问 provider，也不推送。
   - `remote`：先只读确认下游 `.github/workflows/release-candidate.yml` 与 [assets/github-release-candidate.yml](assets/github-release-candidate.yml) 逐字节相同，再用 `$go-prepare-release` 的固定矩阵派发 `GOOS` × `GOARCH` 原生构建。

   缺失或漂移在矩阵启动前判定 provider unavailable；已启动作业失败不得改判为回退条件。
6. 在测试与构建前原子刷新 `release/`，拒绝符号链接与重解析点：

   ```text
   bash .agents/skills/go-build-release/scripts/prepare-release-directory.sh <project-root>
   ```

   Windows 原生路线改用同一目录下的 `prepare-release-directory.ps1 -ProjectRoot <project-root>`；Windows 原生路线不得调用 `.sh` helper。刷新要求项目根是独立 Git 顶层、HEAD 可解析为 40 位小写提交、工作树 clean，并在完成后复核 HEAD 与工作树未变。
7. 运行全部非空单元测试与静态检查，并在测试后复核 clean 与 HEAD：

   ```text
   go vet ./...
   go test ./... -race
   go build -trimpath -ldflags "-s -w -X main.version=<version> -X main.commit=<40-hex>" -o bin/<product> ./cmd/server
   ```

   交叉编译时通过环境变量指定目标，不复用宿主默认值：

   ```text
   GOOS=linux GOARCH=amd64 CGO_ENABLED=0 go build -trimpath -ldflags "-s -w -X main.version=<version> -X main.commit=<40-hex>" -o bin/<product>-<version>-linux-amd64 ./cmd/server
   ```

   制品命名固定为 `<product>-v<version>-<platform>-<arch>[.exe]`，其中 `platform` 取 `GOOS`、`arch` 取 `GOARCH`。不得启动二进制、注入额外链接参数或混入格式/lint/E2E。
8. 按批准配置探测并执行非交互签名钩子。签名开始后失败必须失败；条件不存在且策略允许时记录 `unsigned` 与原因。不得暴露凭据或接受任意签名命令输入。
9. 在项目根同级安全暂存目录生成确定性制品、相邻 `.sha256` 和 manifest；归档包含最终二进制与原样 `release-notes.json`。写 manifest 前再次运行发布上下文 `verify`，证明 HEAD、clean、上下文 bytes/hash、默认分支 ref 与版本 tag 未漂移。
10. 用本 Skill 的制品校验器复核暂存集合，再提交：

    ```text
    python3 .agents/skills/go-build-release/scripts/verify_go_artifacts.py verify --release-root <stage-path> --version <version> --source-commit <40-hex> --release-context-sha256 <sha256>
    ```

    该命令要求每个制品存在、为非符号链接普通文件、命名匹配 `<product>-v<version>-<platform>-<arch>[.exe]`、相邻 `.sha256` 与其字节一致、`.manifest.json` 字段自洽且绑定同一 `sourceCommit`、`releaseContextSha256` 与 `releaseTag`，并拒绝缺失、额外、重复、空与越界路径。
11. manifest 至少记录 `project`、`version`、`sourceCommit`、`releaseContextSha256`、`buildRun`/`buildMode`、`platform`/`architecture`/`target`/`host`、`goVersion`、`artifactKind`、归档/摘要、测试、`e2eSelection`、完整 `releaseReview`/`candidateSelections` 及其审查投影、更新日志版本/摘要/路径、签名状态/原因/证据和 `milestoneAcceptance: pending`。所有选择只从上下文复制。
12. 验证暂存目录精确文件集后，以不跟随链接的目录级原子替换提交到项目根 `release/`。全部作业成功后由 `$go-collect-release-artifacts` 原子合并结果；不得逐个平台直接污染调用方 `release/`。

## 固定候选契约

- 候选阶段只能只读确认下游 workflow 与该资产逐字节一致，不得修改 ref、创建 tag 或执行渠道发布。
- 在执行任何 `go test` 或 `go build` 前，必须先运行 `release_notes.py check --file release-notes.json --expected-version <version>`；本 Skill 不得生成或改写更新日志。
- manifest 的 `sourceCommit` 是实际构建 HEAD，绝不能写成审查 `sourceHead`；审查关闭时只复制 `reviewReason`/`reviewRemainingRisk`。
- 候选 `candidateSelections` 必须与上下文一致；本 Skill 不改变 `gitPublication`。
- 每个非 Windows 制品使用 `.tar.gz`，Windows 制品使用 `.zip`；每个归档都带相邻 `.sha256`，且不得包含凭据、绝对本机路径、缓存或未遮盖的环境转储。
- 不得把暂存目录放进工作树或依赖 ignore 隐藏；完整精确集合验证后，把项目根同级暂存目录原子重命名到 `release/`。
- 不得创建或更新 Product Spec、ADR、Changelog、Product Status、Work Plan 或 Verification；候选 E2E 与完整验收只把结构化证据和状态原子写入忽略的 `release/` manifest 及其声明证据。

## 失败条件

- 授权缺失、缺少或漂移的发布上下文、dirty、HEAD/sourceCommit 不同、上下文摘要/schema/版本不同、`go vet`/`go test`/`go build`/签名失败、制品命名或校验和不一致、manifest 字段缺失或冲突、候选缺失或取回不完整都必须失败。
- 不检查分支祖先、合并类型、线性历史、feature 分支是否仍存在，也不检查或创建名为 `Release` 的分支。
- 构建不创建、移动或推送 tag；它只验证 `$go-manage-git-lifecycle` 已经成功推送的 tag。
- 矩阵只生成 `pending` 候选；构建本身不得运行 E2E、验收或渠道发布，也不更新项目记忆。

## 完成输出

报告 `gitPublication`、构建路线、workflow 路径与 action 固定引用、`sourceCommit`、`releaseContextSha256`、版本/tag、全量非空单元测试、制品/摘要/manifest、签名、`pending` 状态与下一步；不更新项目记忆。
