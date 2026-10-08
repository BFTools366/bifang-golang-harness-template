package model

import "time"

// Timestamp 以 **unix 秒** 表示的绝对时刻（UTC 时间轴上的一个点）。
//
// 为什么全项目统一用秒，而不是 time.Time：
//
//	跨边界的时间必须只有一个表示法。用 time.Time 时，同一个字段在不同
//	驱动下精度不同 —— MySQL 驱动把列建成 datetime(3)（毫秒），而 sqlite
//	驱动不设置 NowFunc，走 GORM 默认的 time.Now().Local()（纳秒），
//	序列化又都是 time.Time.MarshalJSON() ≡ RFC3339Nano 原样输出。
//	结果是同一份代码在 dev 返回 7 位小数秒、在 prod 返回 3 位，
//	客户端拿到的字符串位数不固定，写断言、做字符串比较都会踩。
//
//	统一成 unix 秒之后，数据库列、REST 响应、GraphQL 响应三处都是同一个
//	整数，且与已有的 deleted_time（soft_delete 插件，unix 秒）和 JWT 的
//	exp / iat / nbf（规范要求 unix 秒）保持一致。
//
// 精度取舍：秒级精度意味着同一秒内的先后顺序无法区分。本项目里需要严格
// 排序的场景（验证码取最新一条）用 `ORDER BY created_time DESC, id DESC`
// 兜底 —— 雪花 ID 在同一秒内仍单调递增，这也是不依赖 id 单独排序的原因。
//
// 与 GORM 的配合：
//
//	int64 的命名类型会被 GORM 判定为 DataType = Int（schema/field.go:241），
//	因此 autoCreateTime / autoUpdateTime **不带参数**即落到 UnixSecond
//	（schema/field.go:300、:312），写入时把 time.Time 转成 .Unix()
//	（schema/field.go 的 field.Set，`case time.Time` 分支）。
//	所以 tag 只写 autoCreateTime / autoUpdateTime 就够了，不需要
//	serializer，也不需要 precision —— 列类型由 DataType = Int 直接推出 bigint。
//
// 零值语义：0 表示「未设置」，与 time.Time 的零值语义一致，但注意它
// 对应的是 1970-01-01T00:00:00Z 这个真实时刻，不是「不存在」。
// 需要表达「不存在」的字段用 *Timestamp（JSON 输出 null）。
type Timestamp int64

// Now 当前时刻，精度为秒。
func Now() Timestamp { return Timestamp(time.Now().Unix()) }

// TimestampOf 把标准库时间转为 Timestamp（按秒截断）。
func TimestampOf(t time.Time) Timestamp { return Timestamp(t.Unix()) }

// TimestampOfPtr 指针版本，nil 透传，便于从可空 time.Time 转换。
func TimestampOfPtr(t *time.Time) *Timestamp {
	if t == nil {
		return nil
	}
	ts := TimestampOf(*t)
	return &ts
}

// Time 转回标准库 time.Time（本地时区，秒级精度）。
//
// 需要格式化、做日历运算（加月份、取当天零点）时用它，
// 单纯的加减与比较请直接用 Add / Before / After，避免来回转换。
func (t Timestamp) Time() time.Time { return time.Unix(int64(t), 0) }

// IsZero 是否为未设置状态（0）。
//
// 注意这是本类型自己的语义，与 GORM 判断字段零值的方式无关 ——
// GORM 走 reflect.Value.IsZero()，对 int64 而言同样是「等于 0」。
func (t Timestamp) IsZero() bool { return t == 0 }

// Before 是否早于 o
func (t Timestamp) Before(o Timestamp) bool { return t < o }

// After 是否晚于 o
func (t Timestamp) After(o Timestamp) bool { return t > o }

// Equal 是否与 o 表示同一时刻
func (t Timestamp) Equal(o Timestamp) bool { return t == o }

// Sub 返回 t - o 的时长。t 早于 o 时结果为负，与 time.Time.Sub 一致。
func (t Timestamp) Sub(o Timestamp) time.Duration {
	return time.Duration(int64(t)-int64(o)) * time.Second
}

// Add 返回 t 之后 d 所在的时刻。d 小于一秒时按截断处理 ——
// 秒级精度下不存在更细的时间点，截断比四舍五入更不容易出现「加 500ms
// 后与不加完全相等」这类反直觉结果。
func (t Timestamp) Add(d time.Duration) Timestamp {
	return t + Timestamp(int64(d/time.Second))
}

// String 以 RFC3339 输出，仅用于日志与调试。
//
// 它**不影响** JSON 序列化：命名 int64 类型在 encoding/json 里仍然编码成
// 数字，这正是「下发给前端的就是秒」所依赖的行为。
func (t Timestamp) String() string { return t.Time().Format(time.RFC3339) }
