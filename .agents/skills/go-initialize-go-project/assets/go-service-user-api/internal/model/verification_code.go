package model

// 验证码状态
const (
	VerificationCodeStatusPending int8 = 0 // 待使用
	VerificationCodeStatusUsed    int8 = 1 // 已使用
	VerificationCodeStatusRevoked int8 = 2 // 已作废（被重发顶掉，或过期/尝试次数超限）
)

// 验证码接收目标类型
const (
	VerificationTargetEmail = "email"
	VerificationTargetPhone = "phone"
)

// 验证码使用场景。
//
// 场景是独立一列而不是靠 target 推断：同一个邮箱可以同时存在「注册」与
// 「重置密码」两条记录，互不干扰，各自独立计数与过期。
//
// 这里只定义**落库值**；每个场景的行为策略（是否要求目标已绑定账号等）
// 在 service 包的场景注册表里声明（见 service/verification_scene.go）。
// 新增场景要同时改这两处：常量是数据契约，注册表是行为契约。
const (
	// VerificationSceneRegister 注册新账号
	VerificationSceneRegister = "register"
	// VerificationSceneResetPassword 忘记密码时重置密码
	VerificationSceneResetPassword = "reset_password"
)

// VerificationCode 验证码记录
//
// 为什么落在数据库而不是内存 / Redis：
//
//	本模板不依赖任何外部中间件，落库是唯一「零新增基础设施」的持久化方案。
//	代价是每次校验多一次查询，对注册这种低频操作完全可以接受。
//	若以后 QPS 上来了，把 repository 换成 Redis 实现即可，service 层不用改。
//
// 为什么不存明文验证码：
//
//	数据库导出、慢查询日志、备份文件都可能带出明文。存 sha256 让这些渠道
//	拿不到可直接使用的验证码。但要清楚它的边界 —— 6 位数字只有 10^6 种可能，
//	拿到哈希后离线爆破是瞬间的事，所以哈希**不是**主要防线。
//	真正的防线是：有效期短 + 一次性消费 + 失败次数上限 + 重发与每日上限。
//
// 为什么没有 (target, scene) 唯一索引：
//
//	同一个目标会随时间产生多条记录（重发、多次注册失败），唯一索引会直接冲突。
//	查询走 (target, target_type, scene) 复合普通索引取最新一条。
type VerificationCode struct {
	Base
	Target     string     `gorm:"size:128;not null;index:idx_verification_lookup,priority:1;comment:接收目标（邮箱或手机号）" json:"target"`
	TargetType string     `gorm:"size:16;not null;index:idx_verification_lookup,priority:2;comment:目标类型 email/phone" json:"target_type"`
	Scene      string     `gorm:"size:32;not null;index:idx_verification_lookup,priority:3;comment:使用场景" json:"scene"`
	CodeHash   string     `gorm:"size:64;not null;comment:验证码哈希（sha256 hex，不存明文）" json:"-"`
	Status     int8       `gorm:"not null;default:0;index;comment:状态 0待用 1已用 2作废" json:"status"`
	Attempts   int        `gorm:"not null;default:0;comment:校验失败次数" json:"attempts"`
	ExpiredAt  Timestamp  `gorm:"not null;index;comment:过期时间（unix 秒）" json:"expired_at"`
	UsedAt     *Timestamp `gorm:"comment:消费时间（unix 秒，未消费为 NULL）" json:"used_at"`
	SendIP     string     `gorm:"size:64;comment:发送请求来源 IP" json:"send_ip"`
}

// TableName 显式指定表名，不依赖 GORM 的复数化规则
func (VerificationCode) TableName() string { return "verification_codes" }

// IsPending 是否为待使用状态
func (v *VerificationCode) IsPending() bool { return v.Status == VerificationCodeStatusPending }

// IsExpired 在给定时刻是否已过期。
//
// 边界取「到期时刻即算过期」（!now.Before），与 time.Time 版本的
// now.Before(ExpiredAt) 语义完全一致：等于到期秒的那一秒就已经不能用了。
func (v *VerificationCode) IsExpired(now Timestamp) bool { return !now.Before(v.ExpiredAt) }
