// Package scalar 定义 GraphQL 自定义标量在 Go 侧的表示。
package scalar

import (
	"io"

	"github.com/99designs/gqlgen/graphql"
)

// Timestamp unix 秒时间戳标量。
//
// 为什么是自定义标量而不是内置的 Int：
//
//	GraphQL 规范的 Int 是 **32 位**有符号整数，上限 2147483647
//	对应 2038-01-19T03:14:07Z，unix 秒会在 2038 年溢出。
//	所以这里用 Int64 语义的自定义标量，取值域与 Go 的 int64 一致。
//
// 为什么不用 RFC3339 字符串：
//
//	时间在本模板里**只有一种对外表示法** —— unix 秒。数据库列是 bigint 秒，
//	REST 响应是数字，GraphQL 也必须是数字，客户端不需要为两条链路各写一个
//	解析器。RFC3339 还有一个额外问题：小数秒位数由驱动精度决定，
//	同一份代码在 dev（sqlite，纳秒）与 prod（MySQL，毫秒）返回的字符串位数不同。
//
// 为什么不把标量直接绑定到标准库 time.Time：
//
//	gqlgen 通过「这个类型有没有实现 MarshalGQL / UnmarshalGQL」来判断
//	自定义标量怎么编解码。time.Time 两个方法都没有，绑上去之后 gqlgen
//	会把它当成普通结构体逐字段序列化，输出成 {"wall":...,"ext":...} 这种东西。
//
// 与 model.Timestamp 的关系：两者底层都是 int64，投影时直接转换
// （见 internal/graphql/convert.go 的 gqlTimestamp），不做任何精度处理。
//
// 映射关系写在仓库根目录的 gqlgen.yml 里，改类型名要同步改那边。
type Timestamp int64

// MarshalGQL 实现 graphql.Marshaler：输出 unix 秒整数。
//
// 零值输出 0（即 1970-01-01T00:00:00Z），不转成 null ——
// 「没有值」由 schema 的可空性（*Timestamp）表达，不由数值表达。
func (t Timestamp) MarshalGQL(w io.Writer) {
	graphql.MarshalInt64(int64(t)).MarshalGQL(w)
}

// UnmarshalGQL 实现 graphql.Unmarshaler：接受整数或数字字符串。
//
// 当前 schema 里没有任何以 Timestamp 为入参的字段（GraphQL 层只读），
// 但标量必须两个方法都实现，gqlgen 才会把它当标量而不是结构体。
func (t *Timestamp) UnmarshalGQL(v any) error {
	parsed, err := graphql.UnmarshalInt64(v)
	if err != nil {
		return err
	}
	*t = Timestamp(parsed)
	return nil
}
