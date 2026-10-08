"""Harness validator 共享的架构契约片段与路径规则。"""

from __future__ import annotations

import re

# 分层目录的稳定顺序；core 侧指 model/repository/service，接口侧指 api/cmd。
CORE_LAYERS = ("model", "repository", "service")
ADAPTER_LAYERS = ("api", "cmd")
# 中性目录不参与分层判定，但仍受依赖方向硬规则约束。
NEUTRAL_LAYERS = ("configs", "bootstrap", "internal/pkg")

LAYER_DESCRIPTIONS = {
    "model": "领域模型与值对象，只依赖标准库与纯工具包",
    "dto": "传输契约层，定义请求与响应结构，只依赖 model 与纯工具包",
    "repository": "持久化访问，只依赖 model 与 gorm",
    "service": "业务规则与事务边界，不感知任何传输层类型",
    "api": "HTTP 传输层适配器，负责请求解码与响应编码",
    "cmd": "进程入口与装配，负责把各层按依赖方向组装",
}

# Harness 模板必须落地的 Go 目录骨架；缺任一项即判定初始化不完整。
GO_SCAFFOLD_REQUIRED_DIRECTORIES = (
    "cmd",
    "configs",
    "internal",
    "internal/api",
    "internal/model",
    "internal/repository",
    "internal/service",
)

GO_SCAFFOLD_REQUIRED_FILES = (
    "go.mod",
    "go.sum",
    "configs/config.yaml",
    # Swagger 文档包由 `swag init -g cmd/server/main.go -o docs` 生成，
    # 由 cmd/server/main.go 以空导入注册，供 /swagger/index.html 消费。
    "docs/docs.go",
    "docs/swagger.json",
    # 产品身份事实：`$go-manage-version init` 从这里的 productVersion 常量
    # 读取初始版本，缺失会让初始化收尾的版本门禁无法执行。
    "internal/pkg/identity/brand.go",
)

MODULE_PATH_PATTERN = re.compile(r"^[a-z0-9]([a-z0-9._-]*[a-z0-9])?(\/[a-z0-9]([a-z0-9._-]*[a-z0-9])?)+$")
GO_VERSION_PATTERN = re.compile(r"^go\s+(?P<version>\d+\.\d+(?:\.\d+)?)$", re.MULTILINE)
GO_TOOLCHAIN_MINIMUM = (1, 25, 0)
# 裸 module 路径：无点号、无版本后缀、无斜杠。
BARE_MODULE_PATTERN = re.compile(r"^[a-z][a-z0-9]*(?:_[a-z0-9]+)*$")
MODULE_DIRECTIVE_PATTERN = re.compile(r"^module\s+(?P<path>\S+)\s*$", re.MULTILINE)
GO_MODULE_RESERVED_NAMES = frozenset(
    {
        "internal",
        "net",
        "http",
        "test",
        "main",
        "log",
        "json",
        "common",
        "utils",
        "config",
        "gorm",
        "gin",
    }
)


def parse_module_path(go_mod_text: str) -> str | None:
    """从 go.mod 解析 module 路径，缺失时返回空值。"""

    match = MODULE_DIRECTIVE_PATTERN.search(go_mod_text)
    return match.group("path") if match else None


def check_module_path(errors: list[str], relative: str, go_mod_text: str) -> None:
    """校验 module 路径是合规的裸路径，避免被 Go 判定为域名而联网解析。"""

    module_path = parse_module_path(go_mod_text)
    if module_path is None:
        errors.append(f"{relative} 缺少 module 指令")
        return
    if "." in module_path:
        errors.append(
            f"{relative} 的 module 路径含点号 {module_path!r}；"
            "含点路径会被 Go 判定为域名并触发 go-get 网络解析，必须改为裸路径"
        )
        return
    if "/" in module_path:
        errors.append(
            f"{relative} 的 module 路径 {module_path!r} 含斜杠；"
            "本工程约定 module 路径为裸 <project_id>，不带域名或组织前缀"
        )
        return
    if not BARE_MODULE_PATTERN.fullmatch(module_path):
        errors.append(
            f"{relative} 的 module 路径 {module_path!r} 不符合 ASCII snake_case 裸路径约定"
        )
        return
    if module_path in GO_MODULE_RESERVED_NAMES:
        errors.append(
            f"{relative} 的 module 路径 {module_path!r} 易与 Go 标准库或常见依赖混淆，必须改名"
        )



def parse_go_version(go_mod_text: str) -> tuple[int, int, int] | None:
    """从 go.mod 解析 `go` 指令版本，缺失或格式非法时返回空值。"""

    match = GO_VERSION_PATTERN.search(go_mod_text)
    if match is None:
        return None
    parts = match.group("version").split(".")
    numbers = [int(part) for part in parts]
    while len(numbers) < 3:
        numbers.append(0)
    return numbers[0], numbers[1], numbers[2]


def check_go_directive(errors: list[str], relative: str, go_mod_text: str) -> None:
    """校验 go.mod 的 go 指令满足 Harness 下界。"""

    version = parse_go_version(go_mod_text)
    if version is None:
        errors.append(f"{relative} 缺少合法的 go 指令")
        return
    if version < GO_TOOLCHAIN_MINIMUM:
        minimum = ".".join(str(part) for part in GO_TOOLCHAIN_MINIMUM)
        actual = ".".join(str(part) for part in version)
        errors.append(f"{relative} 的 go 指令版本 {actual} 低于 Harness 下界 {minimum}")
