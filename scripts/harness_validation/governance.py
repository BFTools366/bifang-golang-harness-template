"""校验 Harness 仓库结构、文档契约与 Go 工程硬规则。"""

from __future__ import annotations

import json
import re
from pathlib import Path

from .context import (
    ADR_DIR,
    AGENT_POLICY,
    CHANGELOG_DIR,
    ENGINEERING_RULES,
    GO_COMMENT_CHECKER,
    GO_SCAFFOLD_ASSET,
    GO_WEB_TEMPLATE,
    INITIALIZE_SKILL,
    INSTANTIATE_FORM,
    LINE_LIMIT_CHECKER,
    PRODUCT_SPEC,
    PRODUCT_STATUS,
    REQUIRED_FILES,
    ROOT,
    SKILLS_ROOT,
    VERIFICATION_DOC,
    VERSION_FILE,
    WORK_PLAN,
    WORKFLOW,
    display_path,
    latest_matching_file,
    read_text_cached,
    read_text_or_empty,
    require_fragments,
)


# 处理器上的 swag 路由注解，形如 `@Router /healthz [get]`；它是文档的事实源。
ROUTER_ANNOTATION_PATTERN = re.compile(r"@Router\s+(?P<path>\S+)\s+\[[A-Za-z]+\]")

# 会随实例化复制进下游产品面的受维护文档。这些文件没有 `//go:build tools` 之类的
# 豁免，字面量会直接被下游 `no-desktop-capabilities` 扫描命中。
DOWNSTREAM_DOC_SURFACE = (
    "README.md",
    "AGENTS.md",
    "docs/GO_WEB_TEMPLATE.md",
    "docs/ENGINEERING_RULES.md",
    "docs/AGENT_POLICY.md",
    "docs/RELEASE.md",
    "docs/TECH_DEBT.md",
)

# 与下游 `verify_initialization_contract.py` 的 `FORBIDDEN_MARKERS` 对应的文档侧子集。
# 只保留会被普通 Markdown 正文命中的条目；Go 源码有 build tag 豁免，不在此列。
DOC_FORBIDDEN_MARKERS = (
    ("cobra", "CLI 框架"),
    ("urfave/cli", "CLI 框架"),
    ("bubbletea", "TUI 框架"),
    ("tview", "TUI 框架"),
    ("mcp-go", "MCP 框架"),
    ("modelcontextprotocol", "MCP 框架"),
    ("internal/mcp", "MCP 适配器目录"),
    ("tauri", "桌面 GUI 运行时"),
    ("tray-icon", "系统托盘"),
)


def validate_required_files(errors: list[str]) -> None:
    """要求全部必需文件存在且不是符号链接。"""

    for relative in REQUIRED_FILES:
        path = ROOT / relative
        if path.is_symlink():
            errors.append(f"必需文件不得是符号链接: {relative}")
            continue
        if not path.is_file():
            errors.append(f"缺少必需文件: {relative}")


def validate_skills(errors: list[str]) -> None:
    """要求 skills 目录只包含期望的 skill，且每个 skill 都有 SKILL.md。"""

    from .context import EXPECTED_SKILLS

    if not SKILLS_ROOT.is_dir():
        errors.append(f"缺少 skills 根目录: {display_path(SKILLS_ROOT)}")
        return
    actual = {
        path.name
        for path in SKILLS_ROOT.iterdir()
        if path.is_dir() and not path.name.startswith(".")
    }
    for missing in sorted(EXPECTED_SKILLS - actual):
        errors.append(f"缺少 skill 目录: .agents/skills/{missing}")
    for unexpected in sorted(actual - EXPECTED_SKILLS):
        errors.append(f"存在未登记的 skill 目录: .agents/skills/{unexpected}")
    for name in sorted(EXPECTED_SKILLS & actual):
        skill_file = SKILLS_ROOT / name / "SKILL.md"
        if not skill_file.is_file():
            errors.append(f"skill 缺少 SKILL.md: .agents/skills/{name}")


def validate_markdown_links(errors: list[str]) -> None:
    """校验仓库内 Markdown 的相对链接目标存在。"""

    link_pattern = re.compile(r"\[[^\]]*\]\(([^)\s]+)\)")
    for path in sorted(ROOT.rglob("*.md")):
        relative = path.relative_to(ROOT).as_posix()
        if any(part.startswith(".") for part in path.parts):
            continue
        if not path.is_file():
            continue
        try:
            body = read_text_cached(path)
        except (OSError, UnicodeDecodeError) as error:
            errors.append(f"无法读取 Markdown {relative}: {error}")
            continue
        # 代码围栏内的内容不是链接语义，剥离后再匹配以避免误判。
        body = re.sub(r"^```.*?^```", "", body, flags=re.MULTILINE | re.DOTALL)
        for target in link_pattern.findall(body):
            # 锚点片段不参与文件系统解析，只校验目标文件本身。
            target = target.split("#", 1)[0]
            if not target or target.startswith(("http://", "https://", "mailto:")):
                continue
            resolved = (path.parent / target).resolve()
            try:
                resolved.relative_to(ROOT.resolve())
            except ValueError:
                errors.append(f"{relative} 的链接越过仓库根: {target}")
                continue
            if not resolved.exists():
                errors.append(f"{relative} 的链接目标不存在: {target}")


def validate_workflow(errors: list[str]) -> None:
    """要求发布候选工作流存在且声明 Go 构建矩阵。"""

    if not WORKFLOW.is_file():
        errors.append(f"缺少发布候选工作流: {display_path(WORKFLOW)}")
        return
    text = read_text_or_empty(WORKFLOW)
    require_fragments(
        errors,
        WORKFLOW,
        ("GOOS", "GOARCH", "go build"),
        label="发布候选工作流",
    )
    for forbidden in ("x86_64-apple-darwin", "aarch64-apple-darwin", "tauri", "pnpm"):
        if forbidden in text:
            errors.append(f"发布候选工作流残留桌面栈配置: {forbidden}")


def validate_release_contract(errors: list[str]) -> None:
    """校验版本、发布上下文与双语发布日志的对外契约。"""

    require_fragments(
        errors,
        VERSION_FILE,
        ("YYYYMMDDHHMM", "Asia/Shanghai"),
        label="Version.md",
    )
    require_fragments(
        errors,
        ROOT / ".harness" / "release-context.json",
        ('"schemaVersion"', '"gitPublication"', '"version"', '"defaultBranch"'),
        label="release-context.json",
    )
    require_fragments(
        errors,
        ROOT / "release-notes.json",
        ('"schemaVersion"', '"featureOptimizations"', '"bugFixes"', "zh-CN", "en-US"),
        label="release-notes.json",
    )


def validate_git_lifecycle_contract(errors: list[str]) -> None:
    """校验 Git 生命周期契约文档与 skills 一致。"""

    from .context import GIT_LIFECYCLE_SKILL, GIT_LIFECYCLE_SCRIPT

    require_fragments(
        errors,
        GIT_LIFECYCLE_SKILL,
        ("git-lifecycle.json", "agent-first-harness", "publish", "release"),
        label="Git 生命周期 skill",
    )
    require_fragments(
        errors,
        GIT_LIFECYCLE_SCRIPT,
        ("agent-first-harness", "git-lifecycle.json"),
        label="Git 生命周期脚本",
    )
    engineering = read_text_or_empty(ENGINEERING_RULES)
    for fragment in ("feature-", "YYYYMMDD"):
        if fragment not in engineering:
            errors.append(f"docs/ENGINEERING_RULES.md 缺少分支命名约定: {fragment}")


def validate_upgrade_contract(errors: list[str]) -> None:
    """校验 Harness 升级器契约与所有权清单一致。"""

    from .context import UPGRADE_OWNERSHIP, UPGRADE_POLICY, UPGRADE_SCRIPT

    require_fragments(
        errors,
        UPGRADE_OWNERSHIP,
        ('"schema_version"', '"rules"', "tombstone", "go-instantiate-project"),
        label="升级器所有权清单",
    )
    require_fragments(
        errors,
        UPGRADE_POLICY,
        ("harness", "ownership"),
        label="升级器所有权策略",
    )
    text = read_text_or_empty(UPGRADE_SCRIPT)
    if "harness_upgrade_core" not in text:
        errors.append("升级器入口未引用 harness_upgrade_core")


def validate_initialization_contract(errors: list[str]) -> None:
    """校验初始化 skill 的 Go 脚手架资产与形态契约。"""

    from .architecture_requirements import (
        GO_SCAFFOLD_REQUIRED_DIRECTORIES,
        GO_SCAFFOLD_REQUIRED_FILES,
    )

    require_fragments(
        errors,
        INITIALIZE_SKILL / "SKILL.md",
        ("go.mod", "cmd", "internal"),
        label="Go 初始化 skill",
    )
    require_fragments(
        errors,
        INSTANTIATE_FORM,
        ("ASCII", "snake_case"),
        label="初始化表单",
    )
    if not GO_SCAFFOLD_ASSET.is_dir():
        errors.append(f"缺少 Go 脚手架资产目录: {display_path(GO_SCAFFOLD_ASSET)}")
        return
    for relative in GO_SCAFFOLD_REQUIRED_DIRECTORIES:
        if not (GO_SCAFFOLD_ASSET / relative).is_dir():
            errors.append(f"Go 脚手架缺少目录: {relative}")
    for relative in GO_SCAFFOLD_REQUIRED_FILES:
        if not (GO_SCAFFOLD_ASSET / relative).is_file():
            errors.append(f"Go 脚手架缺少文件: {relative}")
    # Swagger 自动展示是初始化完成的硬交付：路由注册与文档包必须同时在场。
    require_fragments(
        errors,
        GO_SCAFFOLD_ASSET / "internal" / "api" / "router.go",
        ("swaggerFiles", "ginSwagger", "/swagger/*any"),
        label="Go 脚手架 Swagger 路由",
    )
    require_fragments(
        errors,
        GO_SCAFFOLD_ASSET / "cmd" / "server" / "main.go",
        ("_ \"project_id/docs\"",),
        label="Go 脚手架 Swagger 文档注册",
    )
    require_fragments(
        errors,
        INSTANTIATE_FORM,
        ("Swagger", "swagger/index.html", "health-check"),
        label="初始化表单 Swagger 展示流程",
    )
    validate_go_scaffold_swagger_document(errors)
    validate_downstream_doc_surface(errors)
    validate_initialization_form_fields(errors)


def validate_downstream_doc_surface(errors: list[str]) -> None:
    """校验会复制进下游产品面的文档不含禁用能力字面量。

    下游 `no-desktop-capabilities` 会扫描 `docs/*.md`，而这些文档没有
    `//go:build tools` 之类的豁免。历史上 `docs/GO_WEB_TEMPLATE.md` 在解释
    gqlgen 代码生成器依赖时写出了 CLI 框架的包路径，导致每一次新实例化都在
    契约检查阶段失败——描述能力依赖必须用文字，不得写包路径字面量。
    """

    for relative in DOWNSTREAM_DOC_SURFACE:
        text = read_text_or_empty(ROOT / relative)
        if not text:
            continue
        for marker, label in DOC_FORBIDDEN_MARKERS:
            if marker in text:
                errors.append(f"{relative} 含{label}字面量（{marker}），会让下游契约检查失败")


def validate_go_scaffold_swagger_document(errors: list[str]) -> None:
    """校验基线资产的 Swagger 文档与脚手架 `@Router` 注解同步。

    `docs/` 是 `swag init` 的产物，事实源是处理器注解。模板自身的两者脱节时，
    下游会继承一份错误文档，而条件资产落地后是否重新生成就更难判断——启用用户
    API 的下游会因此在 `/swagger/index.html` 里看不到任何认证接口。这里把模板源
    也纳入同样的双向比对，让漂移在 Harness 校验阶段就失败关闭。
    """

    document_path = GO_SCAFFOLD_ASSET / "docs" / "swagger.json"
    system_path = GO_SCAFFOLD_ASSET / "internal" / "api" / "v1" / "system.go"
    # 文件缺失本身由必需文件清单负责，这里不重复报错。
    if not document_path.is_file() or not system_path.is_file():
        return
    try:
        document = json.loads(read_text_cached(document_path))
    except json.JSONDecodeError as error:
        errors.append(f"Go 脚手架 docs/swagger.json 不是合法 JSON: {error}")
        return
    paths = document.get("paths")
    documented = set(paths) if isinstance(paths, dict) else set()
    annotated = {
        match.group(1).rstrip("/") or "/"
        for match in ROUTER_ANNOTATION_PATTERN.finditer(read_text_cached(system_path))
    }
    missing = sorted(annotated - documented)
    if missing:
        errors.append(
            "Go 脚手架 docs/swagger.json 未覆盖 @Router 注解: " + "、".join(missing)
        )
    orphans = sorted(documented - annotated)
    if orphans:
        errors.append(
            "Go 脚手架 docs/swagger.json 收录了没有 @Router 注解的路径: " + "、".join(orphans)
        )


def validate_initialization_form_fields(errors: list[str]) -> None:
    """锁定初始化表单的暴露范围：五项基础字段加一项条件字段，其余全部关闭。

    表单曾把「接口组合」「Agent 策略模式」同时称为基础字段和已关闭字段，
    又曾把只服务客户端打包的「目标平台」列为基础字段，导致问询范围漂移，
    因此在门禁层机械校验清单本身。
    """

    text = read_text_or_empty(INSTANTIATE_FORM)
    if not text:
        errors.append(f"缺少初始化表单: {display_path(INSTANTIATE_FORM)}")
        return

    required_fields = (
        "中文项目展示名称",
        "英文项目展示名称",
        "`project_id`",
        "项目路径",
        "负责人",
        "用户 API",
        "GraphQL",
    )
    for field in required_fields:
        if field not in text:
            errors.append(f"初始化表单缺少基础字段: {field}")

    expose_contract = "本模板**只有七项**"
    if expose_contract not in text:
        errors.append("初始化表单缺少「只有七项」的暴露范围声明")

    template = text.split("## 首轮基础问题模板", 1)[-1].split("## 固定策略", 1)[0]
    numbered = [line for line in template.splitlines() if line[:2].rstrip(".").isdigit()]
    if len(numbered) != 7:
        errors.append(f"首轮问题模板必须恰好列出七项，实际 {len(numbered)} 项")
    for banned in ("接口组合", "Agent 策略模式", "目标平台"):
        if any(banned in line for line in numbered):
            errors.append(f"首轮问题模板不得把已关闭字段列为可选项: {banned}")

    # 唯一开放的条件字段必须默认启用，且关闭路径必须是「不复制」而不是「复制后删除」。
    if "默认启用" not in text:
        errors.append("初始化表单的 user_api 条件字段必须声明默认启用")
    for fragment in ("assets/go-service-user-api/", "AllModels()", "Modules()"):
        if fragment not in text:
            errors.append(f"初始化表单缺少 user_api 关闭/启用契约说明: {fragment}")

    # GraphQL 条件字段默认关闭，且硬依赖 user_api，不得被写成可独立启用。
    if "默认关闭" not in text:
        errors.append("初始化表单的 graphql 条件字段必须声明默认关闭")
    for fragment in ("assets/go-service-graphql/", "user_api=disabled"):
        if fragment not in text:
            errors.append(f"初始化表单缺少 graphql 依赖契约说明: {fragment}")


def validate_core_first_contract(errors: list[str]) -> None:
    """校验 core-first 规则在文档与检查器两侧一致。"""

    engineering = read_text_or_empty(ENGINEERING_RULES)
    for fragment in ("Core-first", "依赖方向", "仓储"):
        if fragment not in engineering:
            errors.append(f"docs/ENGINEERING_RULES.md 缺少 core-first 表述: {fragment}")
    go_template = read_text_or_empty(GO_WEB_TEMPLATE)
    for fragment in ("service", "repository", "model", "middleware"):
        if fragment not in go_template:
            errors.append(f"docs/GO_WEB_TEMPLATE.md 缺少分层表述: {fragment}")


def validate_go_chinese_comments(errors: list[str]) -> None:
    """要求 Go 中文注释门禁脚本存在并声明稳定退出码语义。"""

    if not GO_COMMENT_CHECKER.is_file():
        errors.append(f"缺少 Go 中文注释门禁: {display_path(GO_COMMENT_CHECKER)}")
        return
    text = read_text_or_empty(GO_COMMENT_CHECKER)
    for fragment in ("--json", "inspect_project"):
        if fragment not in text:
            errors.append(f"Go 中文注释门禁缺少接口: {fragment}")


def validate_http_only_interfaces(errors: list[str]) -> None:
    """接口形态收敛为 HTTP API 后，禁止 CLI/TUI/MCP 契约回归。

    `docs/adr/` 与 `docs/work_plan/` 是历史记录，允许描述源模板的 CLI 事实，
    因此只扫描活动事实源文档与 skills。
    """

    forbidden = ("docs/CLI_CONTRACT.md", "go-add-cli-adapter", "go-add-tui-adapter", "go-add-mcp-adapter")
    for source in (ENGINEERING_RULES, VERIFICATION_DOC, AGENT_POLICY, GO_WEB_TEMPLATE):
        text = read_text_or_empty(source)
        for fragment in forbidden:
            if fragment in text:
                errors.append(f"{display_path(source)} 出现已废弃的接口形态引用: {fragment}")
    for skill in ("go-test-final-artifact-e2e", "go-verify-delivery"):
        skill_text = read_text_or_empty(SKILLS_ROOT / skill / "SKILL.md")
        for fragment in ("CLI 四字段", "go-add-cli-adapter", "go-add-tui-adapter", "go-add-mcp-adapter"):
            if fragment in skill_text:
                errors.append(f"{skill} 出现已废弃的接口形态引用: {fragment}")


def validate_test_helpers_match_cli_contracts(errors: list[str]) -> None:
    """拒绝测试与辅助脚本引用已重命名的 CLI 参数或非 Go 构建命令。

    参数改名后测试辅助脚本不跟着改，会让整批测试失败且原因难以定位，
    因此在门禁层机械拦截。
    """

    stale_fragments = (
        "macos-signing-selection",
        "macos-signing-source",
        "macosSigningSource",
        "cargo test",
        "cargo build",
        "cargo clippy",
    )
    for source in sorted(SKILLS_ROOT.glob("*/scripts/*.py")):
        text = read_text_or_empty(source)
        for fragment in stale_fragments:
            if fragment in text:
                errors.append(f"{display_path(source)} 引用已废弃的命令或参数: {fragment}")


def validate_engineering_contract(errors: list[str]) -> None:
    """校验工程规则文档的行数门禁与 Go 基线表述。"""

    require_fragments(
        errors,
        ENGINEERING_RULES,
        ("801", "2001", "internal/pkg/idgen", "go.sum"),
        label="工程规则",
    )
    for forbidden in ("Rust", "Tauri", "Mantine", "Cargo.toml", "MSRV"):
        text = read_text_or_empty(ENGINEERING_RULES)
        if forbidden in text:
            errors.append(f"docs/ENGINEERING_RULES.md 残留桌面栈表述: {forbidden}")


def validate_streamlined_development_and_build(errors: list[str]) -> None:
    """校验开发与构建命令在文档中统一为 Go 工具链。"""

    require_fragments(
        errors,
        GO_WEB_TEMPLATE,
        ("go build", "go test", "go vet", "GOOS", "GOARCH"),
        label="Go 基线文档",
    )
    verify = read_text_or_empty(ROOT / "docs" / "VERIFICATION.md")
    for forbidden in ("DMG", "notarization", "Tauri", "pnpm"):
        if forbidden in verify:
            errors.append(f"docs/VERIFICATION.md 残留桌面栈验证项: {forbidden}")


def validate_current_descriptions(errors: list[str]) -> None:
    """校验当前描述文件不残留桌面栈术语。"""

    for relative in ("README.md", "AGENTS.md"):
        path = ROOT / relative
        if not path.is_file():
            errors.append(f"缺少当前描述文件: {relative}")
            continue
        text = read_text_or_empty(path)
        for forbidden in ("Tauri", "desktop-harness", "pnpm", "Medusa", "Mantine"):
            if forbidden in text:
                errors.append(f"{relative} 残留桌面栈术语: {forbidden}")


def validate_version_contract(errors: list[str]) -> None:
    """校验 Harness 自身时间版本与下游 SemVer 双轨制表述。"""

    require_fragments(
        errors,
        ROOT / "docs" / "RELEASE.md",
        ("YYYYMMDDHHMM", "SemVer", "0..99", "release-notes.json"),
        label="发布规则",
    )
    version_text = read_text_or_empty(VERSION_FILE)
    match = re.search(r"(\d{12})", version_text)
    if match is None:
        errors.append("Version.md 缺少 YYYYMMDDHHMM 版本号")


def validate_product_versioning_contract(errors: list[str]) -> None:
    """校验下游版本号按 base-100 进位规则描述完整。"""

    release_text = read_text_or_empty(ROOT / "docs" / "RELEASE.md")
    for fragment in ("MINOR", "PATCH", "base-100"):
        if fragment not in release_text:
            errors.append(f"docs/RELEASE.md 缺少下游版本规则: {fragment}")


def validate_line_limits(errors: list[str]) -> None:
    """调用行数检查器，把硬超限写入 errors、重构候选写入 warnings。"""

    from .line_limits import inspect_repository

    report = inspect_repository(ROOT)
    errors.extend(f"行数门禁: {error}" for error in report["errors"])
    for violation in report["violations"]:
        errors.append(
            f"行数超限: {violation['path']} ({violation['lines']} lines, "
            f"profile={violation['profile']}, limit={violation['limit']})"
        )


def validate_agent_policy(errors: list[str], *, require_source_defaults: bool = True) -> None:
    """校验 Agent 策略文件保留必要契约字段。"""

    require_fragments(
        errors,
        AGENT_POLICY,
        ("schema_version", "go-", "提交"),
        label="Agent 策略",
    )
    if not require_source_defaults:
        return
    text = read_text_or_empty(AGENT_POLICY)
    for forbidden in ("desktop-", "Rust", "Tauri"):
        if forbidden in text:
            errors.append(f"docs/AGENT_POLICY.md 残留桌面栈术语: {forbidden}")


def validate_release_documents(errors: list[str]) -> None:
    """要求日期目录中的最新正文存在且日期命名合法。"""

    for directory, path, label in (
        (ADR_DIR, latest_matching_file(ADR_DIR, re.compile(r"^\d{8}_ADR\.md$")), "ADR"),
        (
            CHANGELOG_DIR,
            latest_matching_file(CHANGELOG_DIR, re.compile(r"^\d{8}_CHANGELOG\.md$")),
            "变更记录",
        ),
        (ROOT / "docs" / "product_spec", PRODUCT_SPEC, "产品规格"),
        (ROOT / "docs" / "project_status", PRODUCT_STATUS, "项目状态"),
        (ROOT / "docs" / "work_plan", WORK_PLAN, "工作计划"),
    ):
        if not directory.is_dir():
            errors.append(f"缺少日期目录: {display_path(directory)}")
            continue
        if not path.is_file():
            errors.append(f"缺少最新{label}正文: {display_path(path)}")


def validate_work_plan_contract(errors: list[str]) -> None:
    """校验工作计划正文含待办清单与状态列。"""

    require_fragments(
        errors,
        WORK_PLAN,
        ("状态", "Todo"),
        label="工作计划",
    )


def validate_daily_project_memory(errors: list[str]) -> None:
    """校验记忆目录存在；缺失工作记忆不阻塞模板验证。"""

    memory_root = ROOT / ".workbuddy-ai" / "memory"
    if memory_root.exists() and not memory_root.is_dir():
        errors.append(f"记忆路径不是目录: {display_path(memory_root)}")


def validate_optional_release_review(errors: list[str], enabled: bool = False) -> None:
    """校验可选发布评审；模板默认关闭，仅结构必须自洽。"""

    import json

    context_path = ROOT / ".harness" / "release-context.json"
    if not context_path.is_file():
        errors.append("缺少 release-context.json，无法判定发布评审状态")
        return
    try:
        payload = json.loads(read_text_or_empty(context_path))
    except json.JSONDecodeError as error:
        errors.append(f"release-context.json 不是合法 JSON: {error}")
        return
    review = payload.get("releaseReview")
    if not isinstance(review, dict):
        errors.append("release-context.json 缺少 releaseReview 对象")
        return
    selection = review.get("selection")
    if not isinstance(selection, dict) or "enabled" not in selection:
        errors.append("release-context.json 缺少 releaseReview.selection.enabled")
        return
    if selection["enabled"] is not enabled:
        errors.append(
            "releaseReview.selection.enabled 与调用方期望不一致: "
            f"文件={selection['enabled']!r}, 期望={enabled!r}"
        )
