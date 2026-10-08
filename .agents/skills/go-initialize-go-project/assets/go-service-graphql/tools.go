//go:build tools

// Package tools 只用于把开发期工具固定在 go.mod 里，不参与正常编译
// （由 build tag 排除）。
//
// 为什么需要它：go mod tidy 会删掉「没有任何包 import 的模块」及其 go.sum 条目，
// 而 gqlgen 是命令行工具，代码里不会 import 它。结果就是
// `go run github.com/99designs/gqlgen generate` 报
//
//	missing go.sum entry for module providing package github.com/urfave/cli/v3
//
// 用一个空 import 把它锚住，tidy 就不会再剪掉。
//
// 新增命令行工具（golang-migrate、mockgen……）时在这里补一行 import。
package tools

import (
	_ "github.com/99designs/gqlgen"
)
