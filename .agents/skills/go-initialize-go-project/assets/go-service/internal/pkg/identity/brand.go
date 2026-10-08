// Package identity 登记产品身份事实，供版本门禁读取唯一初始版本。
package identity

// productVersion 是产品版本常量的唯一登记处：`$go-manage-version init`
// 从这里读取初始版本并写入 `.harness/version-state.json`，之后每次版本提升
// 也会同步改写这里。刻意不导出，避免业务代码把它当作运行时版本来源；
// 二进制中的真实版本由构建期 `-ldflags -X main.version=` 注入。
const productVersion = "0.1.0"
