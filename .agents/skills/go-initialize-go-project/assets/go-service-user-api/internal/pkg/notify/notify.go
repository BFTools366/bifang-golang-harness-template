// Package notify 定义验证码等一次性凭据的「送达通道」抽象。
//
// 本模板不绑定任何具体的短信 / 邮件服务商：业务层只依赖 Sender 接口，
// 接入真实通道时新增一个实现并在 New 里注册即可，service 与 api 层不用改。
//
// 当前所有 provider 都落到 Unconfigured，即「通道未接入」：
// 非 mock 模式下调用发送会返回 ErrChannelUnavailable，接口层翻译成 503。
// 这是有意为之的显式失败 —— 比静默丢弃、让用户永远收不到码要好排查得多。
package notify

import (
	"context"
	"errors"
	"strings"
	"time"
)

// ErrChannelUnavailable 发送通道未接入或不可用
var ErrChannelUnavailable = errors.New("notify: 发送通道未配置")

// 目标类型，与 model.VerificationTarget* 取值保持一致
const (
	TargetTypeEmail = "email"
	TargetTypePhone = "phone"
)

// 已注册的通道名。空串表示未接入真实通道。
const (
	ProviderNone = ""
	ProviderSMTP = "smtp"
	ProviderHTTP = "http"
)

// Target 验证码接收目标
type Target struct {
	// Type 目标类型：email / phone
	Type string
	// Value 归一化后的目标值（邮箱小写、手机号无分隔符）
	Value string
}

// Display 返回脱敏后的目标，用于响应体与日志 —— 别把完整手机号回显给调用方
func (t Target) Display() string {
	switch t.Type {
	case TargetTypeEmail:
		return MaskEmail(t.Value)
	case TargetTypePhone:
		return MaskPhone(t.Value)
	default:
		return "***"
	}
}

// Sender 验证码发送通道
type Sender interface {
	// Send 把验证码投递到目标。返回 nil 表示服务商已受理，
	// 不代表用户一定收到（投递失败是异步的，不在本接口职责内）。
	Send(ctx context.Context, target Target, code string, ttl time.Duration) error
}

// Unconfigured 未接入真实通道时的占位实现
type Unconfigured struct{}

// Send 恒返回 ErrChannelUnavailable
func (Unconfigured) Send(context.Context, Target, string, time.Duration) error {
	return ErrChannelUnavailable
}

// New 按配置的通道名构造 Sender。
//
// 未实现的通道一律返回 Unconfigured，不返回 error：
// 配置值的合法性由 config.Validate 用 Supported 提前拦下，
// 走到这里说明是「合法但尚未接入」，此时让发送动作显式失败即可。
func New(provider string) Sender {
	switch strings.ToLower(strings.TrimSpace(provider)) {
	case ProviderSMTP, ProviderHTTP:
		// TODO 接入真实通道：实现 Sender 后替换掉这里的分支
		return Unconfigured{}
	default:
		return Unconfigured{}
	}
}

// Supported 判断通道名是否被识别，供 config.Validate 做启动期校验
func Supported(provider string) bool {
	switch strings.ToLower(strings.TrimSpace(provider)) {
	case ProviderNone, ProviderSMTP, ProviderHTTP:
		return true
	default:
		return false
	}
}

// MaskEmail 邮箱脱敏：保留首字符与完整域名，user@a.com -> u***@a.com
func MaskEmail(email string) string {
	at := strings.LastIndex(email, "@")
	if at <= 0 {
		return "***"
	}
	local, domain := email[:at], email[at:]
	if len(local) <= 1 {
		return "*" + domain
	}
	return local[:1] + "***" + domain
}

// MaskPhone 手机号脱敏：保留前 3 位与后 4 位，13800138000 -> 138****8000
//
// 位数不足 7 位时直接整体打码，避免「脱敏后反而暴露全部内容」。
func MaskPhone(phone string) string {
	if len(phone) < 7 {
		return "***"
	}
	return phone[:3] + "****" + phone[len(phone)-4:]
}
