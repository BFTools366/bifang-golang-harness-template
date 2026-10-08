#!/usr/bin/env python3
"""验证 core-first 分层门禁的分层映射、反向依赖判定与退出码契约。"""

from __future__ import annotations

import io
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout

import check_core_first as checker


def _write(root: Path, relative: str, content: str) -> Path:
    """按相对路径写文件，自动补齐父目录。"""

    target = root / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return target


def _scaffold(root: Path) -> None:
    """写出一个满足分层基线的最小 module：model 与 service 同时存在。"""

    _write(root, "go.mod", "module order_service\n\ngo 1.26.0\n")
    _write(root, "internal/model/entity.go", "package model\n")
    _write(root, "internal/service/entity.go", "package service\n")


class LayerMappingTests(unittest.TestCase):
    """`_layer_of` 必须把目录准确映射到五层，且中性目录不参与判定。"""

    def test_model_layer(self) -> None:
        self.assertEqual("model", checker._layer_of("internal/model/entity.go"))

    def test_repository_layer(self) -> None:
        self.assertEqual(
            "repository", checker._layer_of("internal/repository/entity.go")
        )

    def test_service_layer(self) -> None:
        self.assertEqual("service", checker._layer_of("internal/service/entity.go"))

    def test_api_layer(self) -> None:
        self.assertEqual("api", checker._layer_of("internal/api/v1/entity.go"))

    def test_middleware_belongs_to_api_layer(self) -> None:
        self.assertEqual("api", checker._layer_of("internal/middleware/auth.go"))

    def test_graphql_belongs_to_api_layer(self) -> None:
        """internal/graphql 是 GraphQL 传输层，与 api 同级归入 adapter。"""

        self.assertEqual("api", checker._layer_of("internal/graphql/generated.go"))

    def test_graphql_projection_package_is_not_model_layer(self) -> None:
        """GraphQL 投影包是传输契约而非持久化实体，不得命中 model 分层。"""

        self.assertEqual(
            "api", checker._layer_of("internal/graphql/model/models_gen.go")
        )

    def test_cmd_layer(self) -> None:
        self.assertEqual("cmd", checker._layer_of("cmd/server/main.go"))

    def test_configs_is_neutral(self) -> None:
        self.assertIsNone(checker._layer_of("configs/config.go"))

    def test_pkg_is_neutral(self) -> None:
        self.assertIsNone(checker._layer_of("internal/pkg/query/query.go"))


class ImportMappingTests(unittest.TestCase):
    """`_import_layer` 只识别 module 内部导入，外部依赖返回空值。"""

    def test_internal_import_maps_to_layer(self) -> None:
        self.assertEqual(
            "service",
            checker._import_layer("order_service", "order_service/internal/service"),
        )

    def test_module_self_import_is_neutral(self) -> None:
        self.assertIsNone(checker._import_layer("order_service", "order_service"))

    def test_external_import_is_neutral(self) -> None:
        self.assertIsNone(
            checker._import_layer("order_service", "github.com/gin-gonic/gin")
        )

    def test_module_prefix_collision_is_neutral(self) -> None:
        self.assertIsNone(
            checker._import_layer("order_service", "order_service_extra/internal/service")
        )


class InterfaceImportTests(unittest.TestCase):
    """core 侧禁止依赖的接口框架清单，必须覆盖 HTTP、配置与 ORM。"""

    def test_gin_is_interface_import(self) -> None:
        self.assertTrue(checker._is_interface_import("github.com/gin-gonic/gin"))

    def test_viper_is_interface_import(self) -> None:
        self.assertTrue(checker._is_interface_import("github.com/spf13/viper"))

    def test_gorm_is_interface_import(self) -> None:
        self.assertTrue(checker._is_interface_import("gorm.io/gorm"))

    def test_swaggo_is_interface_import(self) -> None:
        self.assertTrue(checker._is_interface_import("github.com/swaggo/gin-swagger"))

    def test_gqlgen_is_interface_import(self) -> None:
        self.assertTrue(
            checker._is_interface_import("github.com/99designs/gqlgen/graphql")
        )

    def test_gqlparser_is_interface_import(self) -> None:
        self.assertTrue(
            checker._is_interface_import("github.com/vektah/gqlparser/v2")
        )

    def test_stdlib_is_not_interface_import(self) -> None:
        self.assertFalse(checker._is_interface_import("net/http"))

    def test_mcp_go_is_no_longer_an_interface_import(self) -> None:
        """接口形态收敛为 HTTP API 后，MCP 框架不得再出现在门禁清单。"""

        self.assertFalse(checker._is_interface_import("github.com/mark3labs/mcp-go/mcp"))


class ParseImportsTests(unittest.TestCase):
    """import 解析需同时覆盖块形式与单行形式。"""

    def test_block_imports_are_parsed(self) -> None:
        source = 'import (\n\t"fmt"\n\t"order_service/internal/model"\n)\n'
        self.assertEqual(
            ["fmt", "order_service/internal/model"], checker._parse_imports(source)
        )

    def test_single_line_import_is_parsed(self) -> None:
        self.assertEqual(["fmt"], checker._parse_imports('import "fmt"\n'))

    def test_aliased_single_line_import_is_parsed(self) -> None:
        self.assertEqual(
            ["github.com/gin-gonic/gin"],
            checker._parse_imports('import gin "github.com/gin-gonic/gin"\n'),
        )


class ValidateModuleTests(unittest.TestCase):
    """分层方向与 core 隔离的确定性判定。"""

    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp(prefix="core-first-"))
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)

    def test_clean_module_passes(self) -> None:
        _scaffold(self.root)
        _write(
            self.root,
            "internal/service/order.go",
            'package service\n\nimport "order_service/internal/model"\n'
            "\nvar _ = model.Entity{}\n",
        )
        self.assertEqual([], checker.validate_module(self.root))

    def test_missing_go_mod_fails_closed(self) -> None:
        self.assertIn("项目根缺少普通 go.mod", checker.validate_module(self.root))

    def test_reverse_dependency_is_reported(self) -> None:
        _scaffold(self.root)
        _write(
            self.root,
            "internal/repository/order.go",
            'package repository\n\nimport "order_service/internal/service"\n'
            "\nvar _ = service.Entity{}\n",
        )
        errors = checker.validate_module(self.root)
        self.assertTrue(
            any("反向依赖 service 层" in item for item in errors), errors
        )

    def test_service_importing_gin_is_reported(self) -> None:
        _scaffold(self.root)
        _write(
            self.root,
            "internal/service/order.go",
            'package service\n\nimport "github.com/gin-gonic/gin"\n\nvar _ = gin.New\n',
        )
        errors = checker.validate_module(self.root)
        self.assertTrue(
            any("不得引入接口框架 github.com/gin-gonic/gin" in item for item in errors),
            errors,
        )

    def test_service_importing_gqlgen_is_reported(self) -> None:
        """service 层引入 GraphQL 执行引擎必须被拒，与 gin 同等对待。"""

        _scaffold(self.root)
        _write(
            self.root,
            "internal/service/order.go",
            'package service\n\nimport "github.com/99designs/gqlgen/graphql"\n'
            "\nvar _ = graphql.MarshalTime\n",
        )
        errors = checker.validate_module(self.root)
        self.assertTrue(
            any(
                "不得引入接口框架 github.com/99designs/gqlgen/graphql" in item
                for item in errors
            ),
            errors,
        )

    def test_api_layer_may_import_gqlgen(self) -> None:
        """适配器侧使用 gqlgen 并依赖 service 是正向的，不应报错。"""

        _scaffold(self.root)
        _write(
            self.root,
            "internal/graphql/resolver.go",
            'package graphql\n\nimport (\n\t"order_service/internal/service"\n'
            '\t"github.com/99designs/gqlgen/graphql"\n)\n\n'
            "var _ = service.Entity{}\nvar _ = graphql.MarshalTime\n",
        )
        self.assertEqual([], checker.validate_module(self.root))

    def test_service_depending_on_graphql_layer_is_reported(self) -> None:
        """core 侧依赖 GraphQL 传输层必须判为反向依赖。"""

        _scaffold(self.root)
        _write(self.root, "internal/graphql/resolver.go", "package graphql\n\nvar Entity = 1\n")
        _write(
            self.root,
            "internal/service/order.go",
            'package service\n\nimport "order_service/internal/graphql"\n'
            "\nvar _ = graphql.Entity\n",
        )
        errors = checker.validate_module(self.root)
        self.assertTrue(any("反向依赖 api 层" in item for item in errors), errors)

    def test_model_importing_gorm_is_exempt(self) -> None:
        """model 层的 GORM 依赖是表结构数据契约，属显式豁免。"""

        _scaffold(self.root)
        _write(
            self.root,
            "internal/model/entity_gorm.go",
            'package model\n\nimport (\n\t"gorm.io/gorm"\n'
            '\t"gorm.io/plugin/soft_delete"\n)\n\nvar _ = gorm.Open\n'
            "var _ soft_delete.DeletedAt\n",
        )
        self.assertEqual([], checker.validate_module(self.root))

    def test_repository_importing_gorm_is_exempt(self) -> None:
        """repository 层是 GORM 的实现载体，同样在豁免范围内。"""

        _scaffold(self.root)
        _write(
            self.root,
            "internal/repository/order.go",
            'package repository\n\nimport "gorm.io/gorm"\n\nvar _ = gorm.Open\n',
        )
        self.assertEqual([], checker.validate_module(self.root))

    def test_service_importing_gorm_is_reported(self) -> None:
        """service 层不享受 ORM 豁免：业务规则必须与 ORM 解耦。"""

        _scaffold(self.root)
        _write(
            self.root,
            "internal/service/order.go",
            'package service\n\nimport "gorm.io/gorm"\n\nvar _ = gorm.Open\n',
        )
        errors = checker.validate_module(self.root)
        self.assertTrue(
            any("不得引入接口框架 gorm.io/gorm" in item for item in errors), errors
        )

    def test_model_importing_gin_is_still_reported(self) -> None:
        """ORM 豁免不适用于传输层框架。"""

        _scaffold(self.root)
        _write(
            self.root,
            "internal/model/entity_gin.go",
            'package model\n\nimport "github.com/gin-gonic/gin"\n\nvar _ = gin.New\n',
        )
        errors = checker.validate_module(self.root)
        self.assertTrue(
            any("不得引入接口框架 github.com/gin-gonic/gin" in item for item in errors),
            errors,
        )

    def test_api_layer_may_import_gin(self) -> None:
        _scaffold(self.root)
        _write(
            self.root,
            "internal/api/v1/order.go",
            'package v1\n\nimport "github.com/gin-gonic/gin"\n\nvar _ = gin.New\n',
        )
        self.assertEqual([], checker.validate_module(self.root))

    def test_api_layer_may_import_service(self) -> None:
        _scaffold(self.root)
        _write(
            self.root,
            "internal/api/v1/order.go",
            'package v1\n\nimport "order_service/internal/service"\n'
            "\nvar _ = service.Entity{}\n",
        )
        self.assertEqual([], checker.validate_module(self.root))

    def test_service_without_model_layer_is_reported(self) -> None:
        _write(self.root, "go.mod", "module order_service\n")
        _write(self.root, "internal/service/order.go", "package service\n")
        errors = checker.validate_module(self.root)
        self.assertTrue(
            any("分层基线不完整" in item for item in errors), errors
        )

    def test_errors_are_sorted_and_deduplicated(self) -> None:
        _scaffold(self.root)
        body = (
            'package repository\n\nimport (\n'
            '\t"order_service/internal/service"\n'
            '\t"order_service/internal/api"\n'
            ')\n\nvar _ = service.Entity{}\nvar _ = api.X\n'
        )
        _write(self.root, "internal/repository/order.go", body)
        errors = checker.validate_module(self.root)
        self.assertEqual(sorted(set(errors)), errors)


class MainExitCodeTests(unittest.TestCase):
    """退出码契约：0 通过、1 分层违规、2 工具错误。"""

    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp(prefix="core-first-cli-"))
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)

    def _run(self, arguments: list[str]) -> int:
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            return checker.main(arguments)

    def test_clean_module_returns_zero(self) -> None:
        _scaffold(self.root)
        self.assertEqual(0, self._run(["--root", str(self.root), "--skip-go-list"]))

    def test_reverse_dependency_returns_one(self) -> None:
        _scaffold(self.root)
        _write(
            self.root,
            "internal/repository/order.go",
            'package repository\n\nimport "order_service/internal/service"\n'
            "\nvar _ = service.Entity{}\n",
        )
        self.assertEqual(1, self._run(["--root", str(self.root), "--skip-go-list"]))

    def test_missing_root_returns_two(self) -> None:
        missing = self.root / "does-not-exist"
        self.assertEqual(2, self._run(["--root", str(missing), "--skip-go-list"]))

    def test_json_mode_emits_parseable_report(self) -> None:
        _scaffold(self.root)
        _write(
            self.root,
            "internal/repository/order.go",
            'package repository\n\nimport "order_service/internal/service"\n'
            "\nvar _ = service.Entity{}\n",
        )
        buffer = io.StringIO()
        with redirect_stdout(buffer), redirect_stderr(io.StringIO()):
            code = checker.main(["--root", str(self.root), "--skip-go-list", "--json"])
        self.assertEqual(1, code)
        report = json.loads(buffer.getvalue())
        self.assertFalse(report["ok"])
        self.assertIsNone(report["toolError"])
        self.assertTrue(report["errors"])


if __name__ == "__main__":
    unittest.main()
