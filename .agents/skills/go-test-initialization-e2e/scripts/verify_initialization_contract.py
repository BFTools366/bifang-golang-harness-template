#!/usr/bin/env python3
"""只读校验 Go 下游初始化脚手架的结构契约。

检查器不修改任何文件，只读取目标根目录并输出机器可读结果。
任何契约缺失都返回非零状态，供初始化 E2E 在创建基线提交前阻断。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path


SNAKE_CASE = re.compile(r"^[a-z][a-z0-9]*(?:_[a-z0-9]+)*$")

# 接口事实文件相对于项目根目录的固定位置。
PROFILE_RELATIVE = Path(".harness") / "go-service-profile.json"
PROFILE_SCHEMA_VERSION = 1
DELIVERY_PLATFORM = "linux"
ALLOWED_INTERFACES = ["http-api"]
ALLOWED_USER_API = ["enabled", "disabled"]
ALLOWED_GRAPHQL = ["enabled", "disabled"]

# 用户 API 条件资产的标志性文件；enabled 时必须全部在场，disabled 时必须全部缺席。
USER_API_FILES = [
    "internal/dto/account.go",
    "internal/dto/auth.go",
    "internal/model/account.go",
    "internal/model/org.go",
    "internal/repository/account.go",
    "internal/repository/org.go",
    "internal/service/account.go",
    "internal/service/auth.go",
    "internal/service/org.go",
    "internal/api/v1/account.go",
    "internal/middleware/auth.go",
    "internal/pkg/token/token.go",
    "internal/pkg/hash/password.go",
]

# GraphQL 条件资产的标志性文件；enabled 时必须全部在场，disabled 时必须全部缺席。
#
# 本资产硬依赖用户 API：schema 的 me 查询语义就是「当前登录账号及其默认组织」，
# 没有账号实体时无从实现，所以组合约束在 load_profile 里强制。
GRAPHQL_FILES = [
    "gqlgen.yml",
    "tools.go",
    "internal/graphql/schema.graphqls",
    "internal/graphql/generated.go",
    "internal/graphql/resolver.go",
    "internal/graphql/schema.resolvers.go",
    "internal/graphql/auth.go",
    "internal/graphql/convert.go",
    "internal/graphql/error.go",
    "internal/graphql/scalar/time.go",
    "internal/graphql/gqlctx/context.go",
    "internal/graphql/model/models_gen.go",
    "internal/api/v1/graphql.go",
    "internal/api/v1/graphql_test.go",
]

# 共享核心必须存在的相对路径。
REQUIRED_FILES = [
    "go.mod",
    "go.sum",
    "README.md",
    "cmd/server/main.go",
    "internal/bootstrap/container.go",
    "internal/bootstrap/server.go",
    "internal/api/router.go",
    "internal/api/v1/module.go",
    "internal/api/v1/routes.go",
    "internal/api/v1/system.go",
    "internal/apperr/apperr.go",
    "internal/config/config.go",
    "internal/constant/constant.go",
    "internal/database/database.go",
    "internal/model/base.go",
    "internal/model/models.go",
    "internal/repository/repository.go",
    "internal/middleware/middleware.go",
    "internal/middleware/request_id.go",
    "internal/middleware/locale.go",
    "internal/middleware/logger.go",
    "internal/middleware/error_handler.go",
    "internal/middleware/cors.go",
    "internal/middleware/ratelimit.go",
    "internal/pkg/contextx/contextx.go",
    "internal/pkg/convert/convert.go",
    "internal/pkg/i18n/i18n.go",
    "internal/pkg/logger/logger.go",
    "internal/pkg/query/query.go",
    "internal/pkg/request/request.go",
    "internal/pkg/response/response.go",
    "internal/pkg/snowflake/snowflake.go",
    # 版本门禁读取的产品身份事实；缺失会让 `$go-manage-version init` 失败。
    "internal/pkg/identity/brand.go",
    "internal/pkg/i18n/locales/zh-CN.yaml",
    "internal/pkg/i18n/locales/en-US.yaml",
    "configs/config.yaml",
    "configs/config-dev.yaml",
]

# 禁用能力的检测目标：一旦出现即说明引入了超范围能力。
FORBIDDEN_MARKERS = [
    ("tauri", "桌面 GUI 运行时"),
    ("mantine", "前端组件库"),
    ("@tabler/icons-react", "前端图标库"),
    ("tray-icon", "系统托盘"),
    ("tauri-plugin-notification", "系统通知"),
    ("tauri-plugin-autostart", "开机自启"),
    ("deep-link", "深链接"),
    ("global-shortcut", "全局快捷键"),
    ("sidebar_mode", "侧栏模式"),
    ("cobra", "CLI 框架"),
    ("urfave/cli", "CLI 框架"),
    ("bubbletea", "TUI 框架"),
    ("tview", "TUI 框架"),
    ("mcp-go", "MCP 框架"),
    ("modelcontextprotocol", "MCP 框架"),
    ("internal/mcp", "MCP 适配器目录"),
]

# 禁用能力只针对交付给下游的产品面。Agent 工具、Harness 维护脚本与 Harness 方法论卷
# 自带同一批禁用字面量（如 `$go-implement-change` 的接口检测器必须在下游保留），
# 把它们算进来会让检查器在裁剪前后都恒失败，因此按路径前缀排除。
NON_PRODUCT_PATHS = frozenset(
    {
        ".agents",  # Agent 技能与其脚本
        ".git",  # 版本库内部对象
        ".harness",  # 工程事实文件
        "release",  # 忽略的候选证据目录
        "scripts",  # Harness 维护工具
        "docs/harness_engineering",  # Harness 方法论卷，裁剪时删除
        "docs/HARNESS_ENGINEERING.md",
    }
)

# 工具锚点文件由 build tag 排除在产品构建之外，其内容不构成产品能力。
# `//go:build tools` 的空导入只用于把代码生成器钉在 go.mod 里，不参与正常编译。
TOOLS_BUILD_TAG = re.compile(r"^//go:build\s+tools\s*$", re.MULTILINE)

# gqlgen 生成的符号前缀由 Go 导入路径 mangle 而来：Go 标识符不允许 `.`、`/`、`-`，
# 生成器把它们换成三个 Ogham 字符。因此生成物里必然出现 `<module>ᚋinternalᚋ...`。
# 逐字节移植生成物时容易漏掉这种形式（上游 `golang-web-template` 会变成
# `golangᚑwebᚑtemplate`，普通文本替换匹配不到），所以这里按 mangle 形式正校验：
# 生成物必须属于当前 module，否则说明它是在别的模块名下生成的。
OGHAM_REPLACEMENTS = (("-", "\u1691"), ("/", "\u168b"), (".", "\u1690"))

# 中间件固定顺序：键为函数名，值为期望的相对次序。
MIDDLEWARE_ORDER = ["RequestID(", "Locale(", "Logger(", "ErrorHandler(", "CORS(", "RateLimit("]

# 分页契约固定常量。
QUERY_CONSTANTS = {
    "DefaultCurrent": "1",
    "DefaultSize": "10",
    "MaxSize": "200",
    "MaxCurrent": "1_000_000",
}

# 统一响应体必须提供的构造入口。
RESPONSE_ENTRIES = ["func OK(", "func List(", "func Page(", "func NoContent(", "func Fail(", "func Abort("]

# 处理器上的 swag 路由注解，形如 `@Router /api/v1/auth/login [post]`。
# 它是路由文档的唯一事实源；`docs/` 只是它的生成物。
ROUTER_ANNOTATION = re.compile(r"@Router\s+(?P<path>\S+)\s+\[(?P<method>[A-Za-z]+)\]")

# `cmd/server/main.go` 的 swag 标题注解，形如 `// @title 订单服务 API`。
TITLE_ANNOTATION = re.compile(r"^//\s*@title\s+(?P<title>.+?)\s*$", re.MULTILINE)

# Swagger 文档包相对项目根的固定位置。
SWAGGER_JSON = Path("docs") / "swagger.json"

# 基线脚手架携带的占位文档标题。`docs/` 在身份改名之后才落地，改名映射覆盖不到它，
# 因此这个占位值会在没有重新生成文档的下游里存活下来，必须显式拦截。
SCAFFOLD_PLACEHOLDER_TITLES = ("示例服务 API",)

# 配置包必须体现的分层能力。
CONFIG_MARKERS = [
    ("EnvPrefix", "环境变量前缀"),
    ("BindEnv", "显式环境变量绑定"),
    ("MergeInConfig", "环境档深合并"),
    ("func Load(", "配置加载入口"),
    ("func (c *Config) Validate(", "配置校验"),
]


class ContractError(Exception):
    """表示一项结构契约未通过。"""


def parse_arguments() -> argparse.Namespace:
    """解析检查器需要的根目录参数。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True, type=Path, help="项目根目录")
    parser.add_argument("--go-dir", type=Path, default=None, help="Go 模块目录，缺省等于项目根目录")
    return parser.parse_args()


def read_text(path: Path) -> str:
    """读取受维护文本；无法解码时视为契约错误。"""
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as error:
        raise ContractError(f"无法读取或解码文件 {path}: {error}") from error


def require_files(root: Path) -> None:
    """确认共享核心必须存在的全部文件。"""
    missing = [name for name in REQUIRED_FILES if not (root / name).is_file()]
    if missing:
        raise ContractError("共享核心文件缺失：" + "、".join(missing))


def load_profile(root: Path) -> dict[str, object]:
    """读取并校验接口与平台事实文件。"""
    path = root / PROFILE_RELATIVE
    if not path.is_file():
        raise ContractError(f"缺少接口事实文件：{PROFILE_RELATIVE.as_posix()}")
    try:
        profile = json.loads(read_text(path))
    except json.JSONDecodeError as error:
        raise ContractError(f"接口事实文件不是合法 JSON: {error}") from error
    if not isinstance(profile, dict):
        raise ContractError("接口事实文件顶层必须是对象")
    if profile.get("schemaVersion") != PROFILE_SCHEMA_VERSION:
        raise ContractError(f"schemaVersion 必须为 {PROFILE_SCHEMA_VERSION}")

    platform = profile.get("delivery-platform")
    if not isinstance(platform, str) or platform.strip() != DELIVERY_PLATFORM:
        raise ContractError(f"delivery-platform 必须固定为 {DELIVERY_PLATFORM}")

    user_api = profile.get("user-api")
    if not isinstance(user_api, str) or user_api.strip() not in ALLOWED_USER_API:
        raise ContractError(f"user-api 必须是 {' 或 '.join(ALLOWED_USER_API)}")

    graphql = profile.get("graphql")
    if not isinstance(graphql, str) or graphql.strip() not in ALLOWED_GRAPHQL:
        raise ContractError(f"graphql 必须是 {' 或 '.join(ALLOWED_GRAPHQL)}")

    interfaces = normalize_list(profile.get("interfaces"), "interfaces", ALLOWED_INTERFACES)
    resolved_user_api = user_api.strip()
    resolved_graphql = graphql.strip()
    # GraphQL 查询层的 me 查询需要账号与组织实体，所以它不能脱离用户 API 单独启用。
    if resolved_graphql == "enabled" and resolved_user_api != "enabled":
        raise ContractError("graphql=enabled 要求 user-api=enabled：me 查询依赖账号与组织实体")
    return {
        "delivery-platform": DELIVERY_PLATFORM,
        "user-api": resolved_user_api,
        "graphql": resolved_graphql,
        "interfaces": interfaces,
    }


def normalize_list(value: object, field: str, allowed: list[str]) -> list[str]:
    """校验事实列表非空、去重且在允许集合内。"""
    if not isinstance(value, list) or not value:
        raise ContractError(f"{field} 必须是非空数组")
    if any(item == "pending" for item in value):
        raise ContractError(f"{field} 不得残留 pending")
    items: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            raise ContractError(f"{field} 的每一项都必须是非空字符串")
        normalized = item.strip()
        if normalized not in allowed:
            raise ContractError(f"{field} 含不允许的值：{normalized}")
        if normalized in items:
            raise ContractError(f"{field} 含重复项：{normalized}")
        items.append(normalized)
    return items


def require_go_module(root: Path) -> str:
    """校验 go.mod 的 module 行、go 指令行与依赖声明形态。"""
    text = read_text(root / "go.mod")
    module_match = re.search(r"^module\s+(\S+)\s*$", text, re.MULTILINE)
    if module_match is None:
        raise ContractError("go.mod 缺少 module 行")
    module = module_match.group(1)
    if not module or "@" in module or "latest" in module:
        raise ContractError(f"go.mod 的 module 行不合法：{module}")

    go_match = re.search(r"^go\s+(\d+)\.(\d+)", text, re.MULTILINE)
    if go_match is None:
        raise ContractError("go.mod 缺少 go 指令行")
    major, minor = int(go_match.group(1)), int(go_match.group(2))
    if (major, minor) < (1, 26):
        raise ContractError(f"go.mod 的 go 指令行过低：{go_match.group(0)}")

    if re.search(r"\blatest\b", text):
        raise ContractError("go.mod 不得使用 latest 版本")
    if re.search(r"^\s+[^\s/]+/[^\s]+\s+=>", text, re.MULTILINE):
        raise ContractError("go.mod 不得包含 replace 到非受管路径")
    return module


def require_middleware_order(root: Path) -> None:
    """校验中间件链按固定顺序装配，且 Logger 位于 ErrorHandler 之前。"""
    text = read_text(root / "internal/middleware/middleware.go")
    positions = []
    for marker in MIDDLEWARE_ORDER:
        index = text.find(marker)
        if index < 0:
            raise ContractError(f"中间件链缺少固定环节：{marker.rstrip('(')}")
        positions.append(index)
    if positions != sorted(positions):
        raise ContractError("中间件顺序不是 RequestID → Locale → Logger → ErrorHandler → CORS → RateLimit")
    if "ErrorHandler(" in text and "Debug" not in text:
        raise ContractError("ErrorHandler 选项缺少 Debug 开关")


def require_response_shapes(root: Path) -> None:
    """校验统一响应体的五个构造入口与失败体形状。"""
    text = read_text(root / "internal/pkg/response/response.go")
    missing = [entry for entry in RESPONSE_ENTRIES if entry not in text]
    if missing:
        raise ContractError("统一响应体缺少构造入口：" + "、".join(item.rstrip("(") for item in missing))
    for marker in ['json:"model"', 'json:"data"', 'json:"datas"', 'json:"total"', 'json:"page"', 'json:"result"', 'json:"errors"', 'json:"code"', 'json:"message"']:
        if marker not in text:
            raise ContractError(f"统一响应体缺少字段标签：{marker}")


def require_error_handler(root: Path) -> None:
    """校验错误中间件确实恢复 panic 并写出统一失败体。"""
    text = read_text(root / "internal/middleware/error_handler.go")
    if "recover()" not in text:
        raise ContractError("错误中间件没有 recover panic")
    if "response.Abort(" not in text:
        raise ContractError("错误中间件没有通过统一响应包写出失败体")


def require_locale_parity(root: Path) -> None:
    """校验两种语言的词条 key 集合一致，并覆盖全部错误码。"""
    base = root / "internal/pkg/i18n/locales"
    zh = parse_locale_keys(base / "zh-CN.yaml")
    en = parse_locale_keys(base / "en-US.yaml")
    if zh != en:
        only_zh = sorted(zh - en)
        only_en = sorted(en - zh)
        detail = []
        if only_zh:
            detail.append("仅 zh-CN: " + "、".join(only_zh))
        if only_en:
            detail.append("仅 en-US: " + "、".join(only_en))
        raise ContractError("词条 key 不一致；" + "；".join(detail))

    codes = collect_error_codes(root)
    missing = sorted(code for code in codes if code not in zh)
    if missing:
        raise ContractError("词条未覆盖的错误码：" + "、".join(missing))


def parse_locale_keys(path: Path) -> set[str]:
    """解析词条文件中形如 `key: value` 的键名集合。"""
    keys: set[str] = set()
    for line in read_text(path).splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        match = re.match(r"^([A-Za-z0-9_.]+)\s*:", stripped)
        if match is None:
            raise ContractError(f"词条行不合法：{path.name}: {stripped}")
        keys.add(match.group(1))
    if not keys:
        raise ContractError(f"词条文件为空：{path.name}")
    return keys


def collect_error_codes(root: Path) -> set[str]:
    """从错误包中收集全部声明的错误码字面量。"""
    codes: set[str] = set()
    for path in sorted((root / "internal/apperr").rglob("*.go")):
        for match in re.finditer(r'"([a-z][a-z0-9]*(?:\.[a-z0-9]+)+)"', read_text(path)):
            codes.add(match.group(1))
    if not codes:
        raise ContractError("错误包中未发现任何错误码")
    return codes


def require_config_layers(root: Path) -> None:
    """校验配置分层能力。"""
    text = read_text(root / "internal/config/config.go")
    missing = [name for marker, name in CONFIG_MARKERS if marker not in text]
    if missing:
        raise ContractError("配置包缺少分层能力：" + "、".join(missing))
    for profile in ("configs/config.yaml", "configs/config-dev.yaml"):
        if not (root / profile).is_file():
            raise ContractError(f"缺少配置文件：{profile}")


def require_snowflake_primary_key(root: Path) -> None:
    """校验主键显式关闭自增，且时间字段显式声明自动时间戳标签。"""
    text = read_text(root / "internal/model/base.go")
    if "autoIncrement:false" not in text.replace(" ", ""):
        raise ContractError("主键必须显式声明 autoIncrement:false")
    if "autoCreateTime" not in text or "autoUpdateTime" not in text:
        raise ContractError("时间字段必须显式声明 autoCreateTime 与 autoUpdateTime")


def require_query_constants(root: Path) -> None:
    """校验分页契约常量与排序列名白名单。"""
    text = read_text(root / "internal/pkg/query/query.go")
    for name, value in QUERY_CONSTANTS.items():
        if not re.search(rf"{name}\s*=\s*{re.escape(value)}\b", text):
            raise ContractError(f"分页常量 {name} 必须为 {value}")
    if "regexp.MustCompile" not in text:
        raise ContractError("排序列名必须通过正则白名单校验")


def require_http_contract(root: Path) -> None:
    """校验 HTTP API 接口的路由与中间件接入。"""
    system = read_text(root / "internal/api/v1/system.go")
    if "/healthz" not in system:
        raise ContractError("HTTP API 缺少 /healthz 存活探针")
    # 健康检查路由允许写成完整路径，也允许写成挂在 /api/v1/system 组下的相对路径。
    if "/api/v1/system/health-check" not in system:
        grouped = "/health-check" in system and 'Group("/api/v1/system")' in system
        if not grouped:
            raise ContractError("HTTP API 缺少 /api/v1/system/health-check")
    router = read_text(root / "internal/api/router.go")
    if "middleware.Setup(" not in router:
        raise ContractError("路由装配没有接入共享中间件链")
    if "v1.Register(" not in router:
        raise ContractError("路由装配没有注册 v1 模块")


def normalize_route_path(raw: str) -> str:
    """归一化 swag 注解里的路由路径，便于与生成文档逐项比对。"""
    path = raw.strip()
    if len(path) > 1 and path.endswith("/"):
        path = path.rstrip("/")
    return path


def collect_router_paths(root: Path) -> dict[str, str]:
    """扫描 `internal/` 下的 swag `@Router` 注解，返回路径到声明文件的映射。

    路由文档的事实源是处理器注解，`docs/` 只是它的生成物。条件资产（用户 API、
    GraphQL）带来新注解后如果不同步重新生成，文档会停留在基线状态——启用用户
    API 的下游就会在 `/swagger/index.html` 只看得到健康检查。
    """

    paths: dict[str, str] = {}
    internal = root / "internal"
    if not internal.is_dir():
        return paths
    for path in sorted(internal.rglob("*.go")):
        if path.name.endswith("_test.go"):
            continue
        text = read_text(path)
        if is_tool_anchor(path, text):
            continue
        for match in ROUTER_ANNOTATION.finditer(text):
            normalized = normalize_route_path(match.group("path"))
            paths.setdefault(normalized, path.relative_to(root).as_posix())
    return paths


def load_swagger_document(root: Path) -> dict[str, object]:
    """读取 `docs/swagger.json`，缺失或非法时视为契约错误。"""

    document_path = root / SWAGGER_JSON
    if not document_path.is_file():
        raise ContractError("缺少 swag init 生成的文档文件：docs/swagger.json")
    try:
        document = json.loads(read_text(document_path))
    except json.JSONDecodeError as error:
        raise ContractError(f"docs/swagger.json 不是合法 JSON: {error}") from error
    if not isinstance(document, dict):
        raise ContractError("docs/swagger.json 顶层必须是对象")
    return document


def require_swagger_covers_routes(root: Path, docs_text: str, main_text: str) -> None:
    """校验生成文档覆盖全部 `@Router` 注解，且标题来自当前 main 包。

    只检查 `docs/docs.go` 在场无法发现「条件资产落地后没有重新生成」这一失效：
    文件始终存在，内容却停留在基线。因此这里以注解为基准做双向比对，并核对
    `@title` 与文档标题一致，使陈旧文档在基线提交前就失败关闭。
    """

    annotated = collect_router_paths(root)
    if not annotated:
        return

    document = load_swagger_document(root)
    paths = document.get("paths")
    documented = set(paths) if isinstance(paths, dict) else set()

    missing = sorted(path for path in annotated if path not in documented)
    if missing:
        detail = "、".join(f"{path}（{annotated[path]}）" for path in missing)
        raise ContractError(
            "docs 包未覆盖已注解的路由，条件资产落地后必须重新运行 swag init：" + detail
        )

    orphans = sorted(path for path in documented if path not in annotated)
    if orphans:
        raise ContractError("docs 包收录了没有 @Router 注解的路径：" + "、".join(orphans))

    for path in sorted(annotated):
        if f'"{path}"' not in docs_text:
            raise ContractError(
                f"docs/docs.go 与 docs/swagger.json 不同步，缺少路径声明：{path}；"
                "请重新运行 swag init 生成完整文档包"
            )

    info = document.get("info")
    title = info.get("title") if isinstance(info, dict) else None
    if title in SCAFFOLD_PLACEHOLDER_TITLES:
        raise ContractError(
            f"docs 包标题仍是基线占位值 {title!r}；docs/ 在身份改名之后才落地，"
            "必须把 cmd/server/main.go 的 @title 改为「<中文项目展示名称> API」并重新运行 swag init"
        )
    match = TITLE_ANNOTATION.search(main_text)
    declared = match.group("title") if match else None
    if declared and title != declared:
        raise ContractError(
            f"docs 包标题 {title!r} 与 cmd/server/main.go 的 @title {declared!r} 不一致；"
            "标题注解变更后必须重新运行 swag init"
        )


def require_swagger(root: Path) -> None:
    """校验 Swagger 文档包与 UI 路由在场，否则初始化后无法展示接口文档。

    三处缺一不可：路由挂载 `/swagger/*any`、`swag init` 生成的 docs 包，
    以及 main 包对 docs 的空白导入。只有空白导入会把 spec 注册进 swag 注册表；
    缺少它时 UI 页面仍返回 200，但 `/swagger/doc.json` 是空的。
    此外还要求生成物与处理器注解同步，避免条件资产落地后文档停留在基线。
    """

    router = read_text(root / "internal/api/router.go")
    if "/swagger/*any" not in router:
        raise ContractError("路由装配缺少 Swagger UI 挂载 /swagger/*any")
    docs = root / "docs/docs.go"
    if not docs.is_file():
        raise ContractError("缺少 swag init 生成的 docs 包：docs/docs.go")
    docs_text = read_text(docs)
    if "package docs" not in docs_text:
        raise ContractError("docs/docs.go 不是合法的 docs 包")
    main = read_text(root / "cmd/server/main.go")
    if not re.search(r'_\s+"[^"]*/docs"', main):
        raise ContractError("cmd/server/main.go 缺少 docs 包空白导入，Swagger spec 不会注册")
    require_swagger_covers_routes(root, docs_text, main)


def require_user_api(root: Path, profile: dict[str, object]) -> None:
    """按 user-api 取值校验用户模块在场或零残留。

    条件资产是「选是才复制」，因此关闭路径必须是文件与引用都不存在，
    而不是复制后删除——后者会留下 AllModels/Modules 之类的悬空引用。
    """

    enabled = profile["user-api"] == "enabled"
    present = [name for name in USER_API_FILES if (root / name).is_file()]
    if enabled and len(present) != len(USER_API_FILES):
        missing = [name for name in USER_API_FILES if name not in present]
        raise ContractError("user-api=enabled 但缺少用户模块文件：" + "、".join(missing))
    if not enabled and present:
        raise ContractError("user-api=disabled 但存在用户模块文件：" + "、".join(present))


def mangle_go_path(path: str) -> str:
    """按 gqlgen 的符号命名规则把 Go 导入路径转成生成代码里的前缀。"""
    for source, replacement in OGHAM_REPLACEMENTS:
        path = path.replace(source, replacement)
    return path


def require_generated_graphql_identity(root: Path, module: str) -> None:
    """校验 gqlgen 生成物属于当前 module，而不是在别的模块名下生成的。

    生成物随资产预生成并提交，身份改名只能替换普通文本；若生成物是在上游模板
    名下生成的，其 Ogham mangle 前缀不会被改名覆盖，就会在下游留下外来身份。
    """
    expected = mangle_go_path(f"{module}/internal")
    text = read_text(root / "internal/graphql/generated.go")
    if expected not in text:
        raise ContractError(
            f"internal/graphql/generated.go 不是按当前 module 生成的：缺少 {expected!r}；"
            "请在该项目内运行 `go run github.com/99designs/gqlgen generate` 重新生成"
        )


def require_graphql(root: Path, profile: dict[str, object], module: str) -> None:
    """按 graphql 取值校验查询层资产在场或零残留。

    与用户 API 同一约定：条件资产是「选是才复制」，因此关闭路径必须是文件与
    引用都不存在，而不是复制后删除——后者会留下 newGraphQLModule 之类的悬空引用。
    """

    enabled = profile["graphql"] == "enabled"
    present = [name for name in GRAPHQL_FILES if (root / name).is_file()]
    if enabled and len(present) != len(GRAPHQL_FILES):
        missing = [name for name in GRAPHQL_FILES if name not in present]
        raise ContractError("graphql=enabled 但缺少查询层文件：" + "、".join(missing))
    if not enabled and present:
        raise ContractError("graphql=disabled 但存在查询层文件：" + "、".join(present))

    modules = read_text(root / "internal/api/v1/module.go")
    referenced = "newGraphQLModule(" in modules
    if enabled and not referenced:
        raise ContractError("graphql=enabled 但 internal/api/v1/module.go 未注册 GraphQL 模块")
    if not enabled and referenced:
        raise ContractError("graphql=disabled 但 internal/api/v1/module.go 仍引用 GraphQL 模块")

    if enabled:
        require_generated_graphql_identity(root, module)


def is_product_path(root: Path, path: Path) -> bool:
    """判断路径是否属于交付给下游的产品面，而非 Agent 工具或 Harness 维护内容。"""
    relative = path.relative_to(root).as_posix()
    if relative == ".":
        return True
    return not any(
        relative == item or relative.startswith(item + "/") for item in NON_PRODUCT_PATHS
    )


def is_tool_anchor(path: Path, text: str) -> bool:
    """判断文件是否为 `//go:build tools` 工具锚点。

    锚点文件被 build tag 排除在产品构建之外，无法产生任何运行时能力，
    因此不参与禁用能力扫描。
    """
    return path.suffix == ".go" and TOOLS_BUILD_TAG.search(text) is not None


def strip_indirect_requires(text: str) -> str:
    """剔除 go.mod 中带 `// indirect` 的间接依赖行。

    间接依赖是某个直接依赖自身的实现细节，不是产品主动引入的能力：
    例如 gqlgen 的代码生成命令行依赖 `github.com/urfave/cli/v3`，它随
    GraphQL 条件资产以 `// indirect` 进入 go.mod，但下游服务并不因此
    暴露任何 CLI 入口。真正的 CLI 能力必然表现为非间接的 require 行，
    以及产品代码里对该包的 import。
    """
    return "\n".join(line for line in text.splitlines() if "// indirect" not in line)


def require_no_desktop_capabilities(root: Path) -> None:
    """校验产品代码中不存在任何 GUI、CLI、TUI 或 MCP 能力。"""
    hits: list[str] = []
    # 先按路径名拦截典型桌面/CLI 目录，避免只依赖文件内容。
    for path in root.rglob("*"):
        if not is_product_path(root, path):
            continue
        relative = path.relative_to(root).as_posix()
        lowered = relative.lower()
        for marker, label in FORBIDDEN_MARKERS:
            if marker in lowered:
                hits.append(f"{relative} 含{label}（{marker}）")
                break
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if not is_product_path(root, path):
            continue
        relative = path.relative_to(root).as_posix()
        if path.suffix.lower() in {".png", ".jpg", ".jpeg", ".ico", ".gif", ".db", ".exe", ".sum"}:
            continue
        try:
            text = read_text(path)
        except ContractError:
            continue
        if is_tool_anchor(path, text):
            continue
        if path.name == "go.mod":
            text = strip_indirect_requires(text)
        for marker, label in FORBIDDEN_MARKERS:
            if marker in text:
                hits.append(f"{relative} 含{label}（{marker}）")
                break
    # 去重并保持稳定顺序
    unique = sorted(set(hits))
    if unique:
        raise ContractError("发现超范围的桌面/CLI/TUI/MCP 能力：" + "；".join(unique[:5]))


def require_identity(root: Path, profile: dict[str, object]) -> None:
    """校验身份事实与接口事实一致，且两份许可证名称语言正确。"""
    readme = read_text(root / "README.md")
    if "productDefinitionRequired" not in readme:
        raise ContractError("README.md 必须记录 productDefinitionRequired 状态")

    for name in ("LICENSE.zh-CN.md", "LICENSE.en.md"):
        if not (root / name).is_file():
            raise ContractError(f"缺少许可证文件：{name}")
    zh_license = read_text(root / "LICENSE.zh-CN.md")
    en_license = read_text(root / "LICENSE.en.md")
    if "适用项目名称" not in zh_license:
        raise ContractError("中文许可证缺少「适用项目名称」标识")
    if "Applicable Project Name" not in en_license:
        raise ContractError("英文许可证缺少 Applicable Project Name 标识")

    if "http-api" in profile["interfaces"]:
        if not (root / "internal/api/v1/system.go").is_file():
            raise ContractError("选择 http-api 时必须存在 HTTP 路由模块")


def check(root: Path, go_dir: Path | None) -> dict[str, object]:
    """执行全部结构契约检查并返回汇总结果。"""
    resolved_root = root.resolve()
    if not resolved_root.is_dir() and not (resolved_root / "go.mod").is_file() and go_dir is None:
        raise ContractError(f"项目根目录不存在：{resolved_root}")
    module_dir = (go_dir or root).resolve()
    if not (module_dir / "go.mod").is_file():
        raise ContractError(f"Go 模块目录缺少 go.mod：{module_dir}")

    require_files(module_dir)
    profile = load_profile(resolved_root)
    module = require_go_module(module_dir)
    if not SNAKE_CASE.match(module.split("/")[-1]):
        raise ContractError(f"module 末级名称必须是 ASCII snake_case：{module}")

    require_middleware_order(module_dir)
    require_response_shapes(module_dir)
    require_error_handler(module_dir)
    require_locale_parity(module_dir)
    require_config_layers(module_dir)
    require_snowflake_primary_key(module_dir)
    require_query_constants(module_dir)
    require_identity(resolved_root, profile)
    require_no_desktop_capabilities(module_dir)
    require_user_api(module_dir, profile)
    require_graphql(module_dir, profile, module)

    if "http-api" in profile["interfaces"]:
        require_http_contract(module_dir)
        require_swagger(module_dir)

    return {
        "schemaVersion": 1,
        "root": str(resolved_root),
        "goDir": str(module_dir),
        "module": module,
        "deliveryPlatform": profile["delivery-platform"],
        "userApi": profile["user-api"],
        "graphql": profile["graphql"],
        "interfaces": profile["interfaces"],
        "checks": [
            "shared-core",
            "middleware-order",
            "response-shapes",
            "error-handler",
            "locale-parity",
            "config-layers",
            "snowflake-primary-key",
            "query-contract",
            "identity",
            "no-desktop-capabilities",
            "user-api",
            "graphql",
            "swagger",
            "interface-dispatch",
        ],
    }


def main() -> int:
    """输出结构契约检查结果；任何契约缺失都以非零状态失败。"""
    args = parse_arguments()
    try:
        result = check(args.root, args.go_dir)
    except ContractError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
