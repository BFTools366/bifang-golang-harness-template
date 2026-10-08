#!/usr/bin/env python3
"""校验初始化结构契约检查器的行为。"""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).with_name("verify_initialization_contract.py")
sys.path.insert(0, str(SCRIPT.parent))

import verify_initialization_contract as contract  # noqa: E402


def build_minimal_project(root: Path) -> None:
    """构造一个满足全部契约的最小项目骨架。"""
    (root / ".harness").mkdir(parents=True, exist_ok=True)
    (root / ".harness" / "go-service-profile.json").write_text(
        json.dumps(
            {
                "schemaVersion": 1,
                "delivery-platform": "linux",
                "user-api": "enabled",
                "graphql": "disabled",
                "interfaces": ["http-api"],
            }
        ),
        encoding="utf-8",
    )
    (root / "go.mod").write_text(
        "module sample_service\n\ngo 1.26.0\n\nrequire (\n\tgithub.com/gin-gonic/gin v1.12.0\n)\n",
        encoding="utf-8",
    )
    (root / "go.sum").write_text("github.com/gin-gonic/gin v1.12.0/go.mod h1:abc=\n", encoding="utf-8")
    (root / "README.md").write_text(
        "# Sample Service\n\n`productDefinitionRequired=true`\n",
        encoding="utf-8",
    )
    (root / "LICENSE.zh-CN.md").write_text("适用项目名称：示例服务\n", encoding="utf-8")
    (root / "LICENSE.en.md").write_text("Applicable Project Name: Sample Service\n", encoding="utf-8")

    for relative in contract.REQUIRED_FILES:
        path = root / relative
        if path.exists():
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("package placeholder\n", encoding="utf-8")

    for relative in contract.USER_API_FILES:
        path = root / relative
        if path.exists():
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("package placeholder\n", encoding="utf-8")

    (root / "internal/middleware/middleware.go").write_text(
        "package middleware\n\nfunc Setup() {\n"
        "\tRequestID()\n\tLocale()\n\tLogger()\n\tErrorHandler()\n\tCORS()\n\tRateLimit()\n"
        "}\n\nvar Debug = true\n",
        encoding="utf-8",
    )
    (root / "internal/pkg/response/response.go").write_text(
        "package response\n\n"
        'type Body struct {\n\tModel string `json:"model"`\n\tData any `json:"data"`\n}\n'
        'type ListBody struct {\n\tModel string `json:"model"`\n\tDatas any `json:"datas"`\n\tTotal int `json:"total"`\n}\n'
        'type PageBody struct {\n\tModel string `json:"model"`\n\tPage any `json:"page"`\n\tResult any `json:"result"`\n}\n'
        'type ErrorItem struct {\n\tModel string `json:"model"`\n\tCode string `json:"code"`\n\tMessage string `json:"message"`\n}\n'
        'type ErrorBody struct {\n\tModel string `json:"model"`\n\tErrors any `json:"errors"`\n}\n\n'
        "func OK() {}\nfunc List() {}\nfunc Page() {}\nfunc NoContent() {}\nfunc Fail() {}\nfunc Abort() {}\n",
        encoding="utf-8",
    )
    (root / "internal/middleware/error_handler.go").write_text(
        "package middleware\n\nimport \"sample_service/internal/pkg/response\"\n\n"
        "func ErrorHandler() {\n\tdefer func() {\n\t\t_ = recover()\n\t\tresponse.Abort(nil, nil)\n\t}()\n}\n",
        encoding="utf-8",
    )
    (root / "internal/apperr/apperr.go").write_text(
        'package apperr\n\nvar ErrBadRequest = "common.bad.request"\n',
        encoding="utf-8",
    )
    (root / "internal/pkg/i18n/locales/zh-CN.yaml").write_text(
        "common.bad.request: 请求参数不合法\n", encoding="utf-8"
    )
    (root / "internal/pkg/i18n/locales/en-US.yaml").write_text(
        "common.bad.request: Invalid request parameters\n", encoding="utf-8"
    )
    (root / "internal/config/config.go").write_text(
        "package config\n\nconst EnvPrefix = \"APP\"\n\n"
        "func Load() {\n\t_ = BindEnv\n\t_ = MergeInConfig\n}\n\n"
        "func (c *Config) Validate() error { return nil }\n\nvar BindEnv, MergeInConfig int\n",
        encoding="utf-8",
    )
    (root / "configs/config.yaml").write_text("app:\n  name: sample_service\n", encoding="utf-8")
    (root / "configs/config-dev.yaml").write_text("log:\n  level: debug\n", encoding="utf-8")
    (root / "internal/model/base.go").write_text(
        "package model\n\n"
        'type Base struct {\n\tID int64 `gorm:"primaryKey;autoIncrement:false"`\n'
        '\tCreatedTime int64 `gorm:"autoCreateTime"`\n'
        '\tUpdatedTime int64 `gorm:"autoUpdateTime"`\n}\n',
        encoding="utf-8",
    )
    (root / "internal/pkg/query/query.go").write_text(
        "package query\n\nimport \"regexp\"\n\n"
        "const (\n\tDefaultCurrent = 1\n\tDefaultSize = 10\n\tMaxSize = 200\n\tMaxCurrent = 1_000_000\n)\n\n"
        "var safeColumn = regexp.MustCompile(`^[A-Za-z0-9_]+$`)\n",
        encoding="utf-8",
    )
    (root / "internal/api/v1/system.go").write_text(
        "package v1\n\nfunc Register() {\n\t_ = \"/healthz\"\n\t_ = \"/api/v1/system/health-check\"\n}\n",
        encoding="utf-8",
    )
    (root / "internal/api/router.go").write_text(
        "package api\n\nfunc NewRouter() {\n\tmiddleware.Setup(nil, nil)\n\tv1.Register(nil, nil)\n"
        '\t_ = "/swagger/*any"\n}\n',
        encoding="utf-8",
    )
    (root / "docs").mkdir(parents=True, exist_ok=True)
    (root / "docs" / "docs.go").write_text("package docs\n", encoding="utf-8")
    (root / "cmd" / "server" / "main.go").write_text(
        'package main\n\nimport _ "sample_service/docs"\n\nfunc main() {}\n',
        encoding="utf-8",
    )


def write_graphql_assets(root: Path) -> None:
    """按 GraphQL 条件资产的标志性文件生成占位内容，并在模块清单中注册。"""
    for relative in contract.GRAPHQL_FILES:
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("package placeholder\n", encoding="utf-8")
    # 生成物必须带当前 module 的 Ogham mangle 前缀，否则身份校验会（正确地）阻断。
    (root / "internal/graphql/generated.go").write_text(
        "package graphql\n\n// " + contract.mangle_go_path("sample_service/internal") + "\n",
        encoding="utf-8",
    )
    (root / "internal/api/v1/module.go").write_text(
        "package v1\n\nfunc Modules() {\n\tnewGraphQLModule(nil)\n}\n",
        encoding="utf-8",
    )


def write_swagger_assets(
    root: Path,
    *,
    routes: dict[str, str],
    documented: dict[str, str] | None = None,
    title: str = "订单服务 API",
) -> None:
    """写入带 `@Router` 注解的处理器与对应文档包。

    `routes` 是「路由路径 → 声明它的处理器文件」，`documented` 允许刻意写成
    与注解不一致的陈旧文档，用来验证检查器确实会阻断。
    """

    for index, (relative, path) in enumerate(sorted(routes.items())):
        target = root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        # 追加而非覆盖：基线骨架里已写好的路由字面量仍要满足 HTTP 契约检查。
        existing = target.read_text(encoding="utf-8") if target.is_file() else "package v1\n"
        target.write_text(
            existing + f'\nvar _ = "{relative}"\n\n// @Router {relative} [get]\n'
            f"func Handler{index}() {{}}\n",
            encoding="utf-8",
        )
    (root / "cmd" / "server" / "main.go").write_text(
        f'package main\n\nimport _ "sample_service/docs"\n\n// @title {title}\nfunc main() {{}}\n',
        encoding="utf-8",
    )
    entries = documented if documented is not None else routes
    (root / "docs").mkdir(parents=True, exist_ok=True)
    (root / "docs" / "docs.go").write_text(
        "package docs\n\nconst docTemplate = `{\n    \"paths\": {\n"
        + "".join(f'        "{path}": {{}},\n' for path in entries)
        + '    }\n}`\n',
        encoding="utf-8",
    )
    (root / "docs" / "swagger.json").write_text(
        json.dumps(
            {
                "swagger": "2.0",
                "info": {"title": title, "version": "0.1.0"},
                "paths": {path: {} for path in entries},
            }
        ),
        encoding="utf-8",
    )


class VerifyInitializationContractTests(unittest.TestCase):
    """覆盖契约检查器的通过路径与关键阻断路径。"""

    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp(prefix="go-init-contract-"))
        build_minimal_project(self.root)

    def tearDown(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)

    def write_profile(
        self,
        *,
        delivery_platform: str = "linux",
        user_api: str = "enabled",
        graphql: str = "disabled",
        interfaces: list[str] | None = None,
    ) -> None:
        """按指定取值重写接口事实文件，便于各用例只改自己关心的字段。"""
        (self.root / ".harness" / "go-service-profile.json").write_text(
            json.dumps(
                {
                    "schemaVersion": 1,
                    "delivery-platform": delivery_platform,
                    "user-api": user_api,
                    "graphql": graphql,
                    "interfaces": interfaces or ["http-api"],
                }
            ),
            encoding="utf-8",
        )

    def test_minimal_project_passes(self) -> None:
        """满足全部契约的最小骨架应通过检查。"""
        result = contract.check(self.root, self.root)
        self.assertEqual(result["module"], "sample_service")
        self.assertEqual(result["interfaces"], ["http-api"])
        self.assertIn("middleware-order", result["checks"])
        self.assertIn("swagger", result["checks"])

    def test_missing_profile_is_rejected(self) -> None:
        """缺少接口事实文件必须阻断。"""
        (self.root / ".harness" / "go-service-profile.json").unlink()
        with self.assertRaisesRegex(contract.ContractError, "接口事实文件"):
            contract.check(self.root, self.root)

    def test_non_linux_delivery_platform_is_rejected(self) -> None:
        """交付平台不是 linux 必须阻断。"""
        self.write_profile(delivery_platform="windows")
        with self.assertRaisesRegex(contract.ContractError, "delivery-platform"):
            contract.check(self.root, self.root)

    def test_invalid_user_api_value_is_rejected(self) -> None:
        """user-api 非法取值必须阻断。"""
        self.write_profile(user_api="maybe")
        with self.assertRaisesRegex(contract.ContractError, "user-api"):
            contract.check(self.root, self.root)

    def test_disabled_user_api_with_leftover_files_is_rejected(self) -> None:
        """user-api=disabled 但残留用户模块文件必须阻断。"""
        self.write_profile(user_api="disabled")
        with self.assertRaisesRegex(contract.ContractError, "存在用户模块文件"):
            contract.check(self.root, self.root)

    def test_enabled_user_api_with_missing_files_is_rejected(self) -> None:
        """user-api=enabled 但缺少用户模块文件必须阻断。"""
        (self.root / "internal/model/account.go").unlink()
        with self.assertRaisesRegex(contract.ContractError, "缺少用户模块文件"):
            contract.check(self.root, self.root)

    def test_disabled_user_api_without_files_passes(self) -> None:
        """user-api=disabled 且零残留时必须通过。"""
        for relative in contract.USER_API_FILES:
            (self.root / relative).unlink()
        self.write_profile(user_api="disabled")
        result = contract.check(self.root, self.root)
        self.assertEqual(result["userApi"], "disabled")

    def test_invalid_graphql_value_is_rejected(self) -> None:
        """graphql 非法取值必须阻断。"""
        self.write_profile(graphql="maybe")
        with self.assertRaisesRegex(contract.ContractError, "graphql"):
            contract.check(self.root, self.root)

    def test_graphql_without_user_api_is_rejected(self) -> None:
        """graphql=enabled 但 user-api=disabled 必须阻断，me 查询没有账号实体可用。"""
        for relative in contract.USER_API_FILES:
            (self.root / relative).unlink()
        self.write_profile(user_api="disabled", graphql="enabled")
        with self.assertRaisesRegex(contract.ContractError, "user-api=enabled"):
            contract.check(self.root, self.root)

    def test_disabled_graphql_with_leftover_files_is_rejected(self) -> None:
        """graphql=disabled 但残留查询层文件必须阻断。"""
        write_graphql_assets(self.root)
        with self.assertRaisesRegex(contract.ContractError, "存在查询层文件"):
            contract.check(self.root, self.root)

    def test_enabled_graphql_with_missing_files_is_rejected(self) -> None:
        """graphql=enabled 但缺少查询层文件必须阻断。"""
        self.write_profile(graphql="enabled")
        with self.assertRaisesRegex(contract.ContractError, "缺少查询层文件"):
            contract.check(self.root, self.root)

    def test_enabled_graphql_without_module_registration_is_rejected(self) -> None:
        """graphql=enabled 但模块清单未注册必须阻断。"""
        for relative in contract.GRAPHQL_FILES:
            path = self.root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("package placeholder\n", encoding="utf-8")
        self.write_profile(graphql="enabled")
        with self.assertRaisesRegex(contract.ContractError, "未注册 GraphQL 模块"):
            contract.check(self.root, self.root)

    def test_disabled_graphql_with_module_reference_is_rejected(self) -> None:
        """graphql=disabled 但模块清单仍引用必须阻断。"""
        (self.root / "internal/api/v1/module.go").write_text(
            "package v1\n\nfunc Modules() {\n\tnewGraphQLModule(nil)\n}\n",
            encoding="utf-8",
        )
        with self.assertRaisesRegex(contract.ContractError, "仍引用 GraphQL 模块"):
            contract.check(self.root, self.root)

    def test_enabled_graphql_with_complete_assets_passes(self) -> None:
        """graphql=enabled 且资产与注册齐备时必须通过。"""
        write_graphql_assets(self.root)
        self.write_profile(graphql="enabled")
        result = contract.check(self.root, self.root)
        self.assertEqual(result["graphql"], "enabled")
        self.assertIn("graphql", result["checks"])

    def test_graphql_generated_for_another_module_is_rejected(self) -> None:
        """生成物属于别的 module 时必须阻断。

        上游模板的导入路径会被 gqlgen mangle 成 Ogham 形式（`-` → `ᚑ`、`/` → `ᚋ`），
        身份改名的普通文本替换匹配不到，会在下游留下外来身份。
        """
        write_graphql_assets(self.root)
        self.write_profile(graphql="enabled")
        (self.root / "internal/graphql/generated.go").write_text(
            "package graphql\n\n// "
            + contract.mangle_go_path("golang-web-template/internal")
            + "\n",
            encoding="utf-8",
        )
        with self.assertRaisesRegex(contract.ContractError, "不是按当前 module 生成"):
            contract.check(self.root, self.root)

    def test_unknown_interface_is_rejected(self) -> None:
        """不允许的接口值必须阻断。"""
        self.write_profile(interfaces=["cli"])
        with self.assertRaisesRegex(contract.ContractError, "不允许的值"):
            contract.check(self.root, self.root)

    def test_missing_swagger_route_is_rejected(self) -> None:
        """缺少 Swagger UI 挂载必须阻断。"""
        (self.root / "internal/api/router.go").write_text(
            "package api\n\nfunc NewRouter() {\n\tmiddleware.Setup(nil, nil)\n\tv1.Register(nil, nil)\n}\n",
            encoding="utf-8",
        )
        with self.assertRaisesRegex(contract.ContractError, "Swagger UI 挂载"):
            contract.check(self.root, self.root)

    def test_missing_generated_docs_package_is_rejected(self) -> None:
        """缺少 swag init 生成的 docs 包必须阻断。"""
        (self.root / "docs" / "docs.go").unlink()
        with self.assertRaisesRegex(contract.ContractError, "docs 包"):
            contract.check(self.root, self.root)

    def test_missing_docs_blank_import_is_rejected(self) -> None:
        """main 包缺少 docs 空白导入必须阻断。"""
        (self.root / "cmd" / "server" / "main.go").write_text(
            "package main\n\nfunc main() {}\n", encoding="utf-8"
        )
        with self.assertRaisesRegex(contract.ContractError, "空白导入"):
            contract.check(self.root, self.root)

    def test_stale_swagger_docs_after_conditional_asset_is_rejected(self) -> None:
        """条件资产带来新注解但文档未重新生成时必须阻断。

        这是「启用用户 API 后 Swagger 看不到认证接口」的回归用例：docs 包
        始终在场，失效点只在内容停留在基线。
        """
        write_swagger_assets(
            self.root,
            routes={
                "/healthz": "internal/api/v1/system.go",
                "/api/v1/auth/login": "internal/api/v1/account.go",
            },
            documented={"/healthz": "internal/api/v1/system.go"},
        )
        with self.assertRaisesRegex(contract.ContractError, "未覆盖已注解的路由"):
            contract.check(self.root, self.root)

    def test_regenerated_swagger_docs_cover_annotated_routes(self) -> None:
        """文档覆盖全部注解时通过，且标题与 @title 一致。"""
        write_swagger_assets(
            self.root,
            routes={
                "/healthz": "internal/api/v1/system.go",
                "/api/v1/auth/login": "internal/api/v1/account.go",
            },
            title="订单服务 API",
        )
        contract.check(self.root, self.root)

    def test_swagger_title_drift_is_rejected(self) -> None:
        """文档标题与 @title 注解不一致必须阻断。"""
        write_swagger_assets(
            self.root,
            routes={"/healthz": "internal/api/v1/system.go"},
            title="订单服务 API",
        )
        document = json.loads((self.root / "docs" / "swagger.json").read_text(encoding="utf-8"))
        document["info"]["title"] = "库存服务 API"
        (self.root / "docs" / "swagger.json").write_text(
            json.dumps(document), encoding="utf-8"
        )
        with self.assertRaisesRegex(contract.ContractError, "@title"):
            contract.check(self.root, self.root)

    def test_scaffold_placeholder_title_is_rejected(self) -> None:
        """文档标题停留在基线占位值时必须阻断。

        `docs/` 在身份改名之后才落地，改名映射覆盖不到占位标题，所以没有重新
        生成文档的下游会带着「示例服务 API」进入基线提交。
        """
        write_swagger_assets(
            self.root,
            routes={"/healthz": "internal/api/v1/system.go"},
            title="示例服务 API",
        )
        with self.assertRaisesRegex(contract.ContractError, "基线占位值"):
            contract.check(self.root, self.root)

    def test_orphan_swagger_path_is_rejected(self) -> None:
        """文档收录了没有注解的路径必须阻断。"""
        write_swagger_assets(
            self.root,
            routes={"/healthz": "internal/api/v1/system.go"},
            documented={
                "/healthz": "internal/api/v1/system.go",
                "/api/v1/auth/login": "internal/api/v1/account.go",
            },
        )
        with self.assertRaisesRegex(contract.ContractError, "没有 @Router 注解的路径"):
            contract.check(self.root, self.root)

    def test_wrong_middleware_order_is_rejected(self) -> None:
        """中间件顺序被调换必须阻断。"""
        (self.root / "internal/middleware/middleware.go").write_text(
            "package middleware\n\nfunc Setup() {\n"
            "\tRequestID()\n\tLogger()\n\tLocale()\n\tErrorHandler()\n\tCORS()\n\tRateLimit()\n"
            "}\n\nvar Debug = true\n",
            encoding="utf-8",
        )
        with self.assertRaisesRegex(contract.ContractError, "中间件顺序"):
            contract.check(self.root, self.root)

    def test_locale_parity_is_enforced(self) -> None:
        """两种语言词条 key 不一致必须阻断。"""
        (self.root / "internal/pkg/i18n/locales/en-US.yaml").write_text(
            "common.bad.request: Invalid\ncommon.other.key: Other\n", encoding="utf-8"
        )
        with self.assertRaisesRegex(contract.ContractError, "词条 key 不一致"):
            contract.check(self.root, self.root)

    def test_untranslated_error_code_is_rejected(self) -> None:
        """错误码缺少词条必须阻断。"""
        (self.root / "internal/apperr/apperr.go").write_text(
            'package apperr\n\nvar ErrBadRequest = "common.bad.request"\nvar ErrMissing = "common.not.translated"\n',
            encoding="utf-8",
        )
        with self.assertRaisesRegex(contract.ContractError, "未覆盖的错误码"):
            contract.check(self.root, self.root)

    def test_missing_shared_core_file_is_rejected(self) -> None:
        """共享核心文件缺失必须阻断。"""
        (self.root / "internal/pkg/snowflake/snowflake.go").unlink()
        with self.assertRaisesRegex(contract.ContractError, "共享核心文件缺失"):
            contract.check(self.root, self.root)

    def test_primary_key_autoincrement_must_be_disabled(self) -> None:
        """主键未关闭自增必须阻断。"""
        (self.root / "internal/model/base.go").write_text(
            "package model\n\n"
            'type Base struct {\n\tID int64 `gorm:"primaryKey"`\n'
            '\tCreatedTime int64 `gorm:"autoCreateTime"`\n'
            '\tUpdatedTime int64 `gorm:"autoUpdateTime"`\n}\n',
            encoding="utf-8",
        )
        with self.assertRaisesRegex(contract.ContractError, "autoIncrement:false"):
            contract.check(self.root, self.root)

    def test_desktop_capability_is_rejected(self) -> None:
        """出现桌面能力必须阻断。"""
        (self.root / "src-tauri").mkdir()
        (self.root / "src-tauri" / "tauri.conf.json").write_text('{"productName":"x"}', encoding="utf-8")
        with self.assertRaisesRegex(contract.ContractError, "超范围"):
            contract.check(self.root, self.root)

    def test_cli_framework_is_rejected(self) -> None:
        """出现 CLI 框架必须阻断。"""
        (self.root / "cmd" / "tool").mkdir(parents=True)
        (self.root / "cmd" / "tool" / "main.go").write_text(
            'package main\n\nimport "github.com/spf13/cobra"\n', encoding="utf-8"
        )
        with self.assertRaisesRegex(contract.ContractError, "超范围"):
            contract.check(self.root, self.root)

    def test_mcp_adapter_is_rejected(self) -> None:
        """出现 MCP 适配器必须阻断。"""
        (self.root / "internal" / "mcp").mkdir(parents=True)
        (self.root / "internal" / "mcp" / "server.go").write_text("package mcp\n", encoding="utf-8")
        with self.assertRaisesRegex(contract.ContractError, "超范围"):
            contract.check(self.root, self.root)

    def test_agent_tooling_markers_are_not_product_capabilities(self) -> None:
        """Agent 工具与 Harness 维护脚本自带的禁用字面量不得阻断初始化。

        `$go-implement-change` 的接口检测器必须在下游保留，其正文必然包含
        cobra/tauri 之类的字面量；把工具目录算作产品能力会让初始化 E2E 恒失败。
        """
        tooling = self.root / ".agents" / "skills" / "go-implement-change" / "scripts"
        tooling.mkdir(parents=True)
        (tooling / "check_core_first.py").write_text(
            'FORBIDDEN = ("/spf13/cobra", "/charmbracelet/bubbletea")\n', encoding="utf-8"
        )
        maintenance = self.root / "scripts" / "harness_validation"
        maintenance.mkdir(parents=True)
        (maintenance / "governance.py").write_text(
            'MARKERS = ("tauri", "mantine")\n', encoding="utf-8"
        )
        methodology = self.root / "docs" / "harness_engineering"
        methodology.mkdir(parents=True)
        (methodology / "agent_first_design.md").write_text(
            "MCP（modelcontextprotocol）不在支持范围内。\n", encoding="utf-8"
        )
        contract.check(self.root, self.root)

    def test_product_marker_beside_tooling_is_still_rejected(self) -> None:
        """排除工具目录不得放过产品代码里的桌面能力。"""
        tooling = self.root / ".agents" / "skills" / "go-implement-change" / "scripts"
        tooling.mkdir(parents=True)
        (tooling / "check_core_first.py").write_text('MARKERS = ("tauri",)\n', encoding="utf-8")
        (self.root / "configs" / "desktop.yaml").write_text("runtime: tauri\n", encoding="utf-8")
        with self.assertRaisesRegex(contract.ContractError, "超范围"):
            contract.check(self.root, self.root)

    def test_indirect_codegen_dependency_is_not_a_product_capability(self) -> None:
        """代码生成器的间接 CLI 依赖不得被判为产品 CLI 能力。

        gqlgen 的 `generate` 命令行依赖 `github.com/urfave/cli/v3`，它随
        GraphQL 条件资产以 `// indirect` 进入 go.mod；下游服务并不因此暴露
        任何 CLI 入口，把它算作能力会让 `graphql=enabled` 恒失败。
        """
        (self.root / "go.mod").write_text(
            "module sample_service\n\ngo 1.26.0\n\nrequire (\n"
            "\tgithub.com/gin-gonic/gin v1.12.0\n"
            "\tgithub.com/99designs/gqlgen v0.17.95\n"
            ")\n\nrequire (\n"
            "\tgithub.com/urfave/cli/v3 v3.11.0 // indirect\n"
            ")\n",
            encoding="utf-8",
        )
        contract.check(self.root, self.root)

    def test_tools_build_tag_anchor_is_not_a_product_capability(self) -> None:
        """`//go:build tools` 锚点文件被排除在产品构建之外，其内容不构成能力。"""
        write_graphql_assets(self.root)
        self.write_profile(graphql="enabled")
        (self.root / "tools.go").write_text(
            "//go:build tools\n\n"
            "// Package tools 只用于把开发期工具固定在 go.mod 里。\n"
            "//\n"
            "// 缺失锚点时 go run github.com/99designs/gqlgen generate 会报\n"
            "// missing go.sum entry for github.com/urfave/cli/v3。\n"
            "package tools\n\n"
            'import _ "github.com/99designs/gqlgen"\n',
            encoding="utf-8",
        )
        result = contract.check(self.root, self.root)
        self.assertEqual(result["graphql"], "enabled")

    def test_direct_cli_dependency_is_still_rejected(self) -> None:
        """直接声明 CLI 框架（非间接）仍必须阻断。"""
        (self.root / "go.mod").write_text(
            "module sample_service\n\ngo 1.26.0\n\nrequire (\n"
            "\tgithub.com/gin-gonic/gin v1.12.0\n"
            "\tgithub.com/urfave/cli/v3 v3.11.0\n"
            ")\n",
            encoding="utf-8",
        )
        with self.assertRaisesRegex(contract.ContractError, "超范围"):
            contract.check(self.root, self.root)

    def test_go_directive_lower_bound_is_enforced(self) -> None:
        """go 指令行低于下界必须阻断。"""
        (self.root / "go.mod").write_text(
            "module sample_service\n\ngo 1.21.0\n", encoding="utf-8"
        )
        with self.assertRaisesRegex(contract.ContractError, "go 指令行过低"):
            contract.check(self.root, self.root)

    def test_main_script_reports_failure_with_nonzero_status(self) -> None:
        """命令行入口在契约失败时必须以非零状态退出。"""
        (self.root / "internal/pkg/query/query.go").write_text("package query\n", encoding="utf-8")
        import io
        import contextlib

        argv = sys.argv
        stderr = io.StringIO()
        try:
            sys.argv = [
                str(SCRIPT),
                "--root",
                str(self.root),
                "--go-dir",
                str(self.root),
            ]
            with contextlib.redirect_stderr(stderr):
                code = contract.main()
        finally:
            sys.argv = argv
        self.assertEqual(code, 2)
        self.assertIn("ERROR:", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
