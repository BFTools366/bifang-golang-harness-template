// Package scalar 定义 GraphQL 自定义标量在 Go 侧的表示。
package scalar

import (
	"io"
	"time"

	"github.com/99designs/gqlgen/graphql"
)

// Time 是 RFC3339 时间标量。
//
// 为什么不直接把 GraphQL 的 Time 绑定到标准库 time.Time：
// gqlgen 通过「这个类型有没有实现 MarshalGQL / UnmarshalGQL」来判断
// 自定义标量怎么编解码。time.Time 两个方法都没有，绑上去之后 gqlgen
// 会把它当成普通结构体逐字段序列化，输出成 {"wall":...,"ext":...} 这种东西。
//
// 所以这里包一层独立类型，把编解码委托给 gqlgen 自带的 MarshalTime /
// UnmarshalTime（RFC3339Nano，零值序列化为 null）。
//
// 映射关系写在仓库根目录的 gqlgen.yml 里，改类型名要同步改那边。
type Time time.Time

// MarshalGQL 实现 graphql.Marshaler。
func (t Time) MarshalGQL(w io.Writer) {
	graphql.MarshalTime(time.Time(t)).MarshalGQL(w)
}

// UnmarshalGQL 实现 graphql.Unmarshaler。
func (t *Time) UnmarshalGQL(v any) error {
	parsed, err := graphql.UnmarshalTime(v)
	if err != nil {
		return err
	}
	*t = Time(parsed)
	return nil
}

// FromTime 标准库时间转 GraphQL 标量。
func FromTime(t time.Time) Time { return Time(t) }

// FromTimePtr 标准库时间指针转 GraphQL 标量指针，nil 透传。
func FromTimePtr(t *time.Time) *Time {
	if t == nil {
		return nil
	}
	converted := Time(*t)
	return &converted
}

// FromUnix 把 unix 秒转成 GraphQL 标量。
//
// 本基线的 model.Base.CreatedTime / UpdatedTime 是 int64 unix 秒，不是 time.Time，
// 所以投影时必须经过这里。0 按「未设置」处理并返回零值 —— 零值会被
// MarshalTime 序列化成 null，而不是 1970-01-01T00:00:00Z 这个看似有效的时间。
func FromUnix(seconds int64) Time {
	if seconds == 0 {
		return Time{}
	}
	return Time(time.Unix(seconds, 0).UTC())
}

// FromUnixPtr 把 unix 秒指针转成 GraphQL 标量指针，nil 与 0 都透传为 nil。
func FromUnixPtr(seconds *int64) *Time {
	if seconds == nil || *seconds == 0 {
		return nil
	}
	converted := FromUnix(*seconds)
	return &converted
}

// Std 转回标准库类型。
func (t Time) Std() time.Time { return time.Time(t) }
