package notify_test

import (
	"context"
	"errors"
	"strings"
	"testing"
	"time"

	"project_id/internal/pkg/notify"
)

// TestMaskEmail 邮箱脱敏保留首字符与域名，非法输入整体打码。
func TestMaskEmail(t *testing.T) {
	cases := []struct {
		in   string
		want string
	}{
		{in: "user@example.com", want: "u***@example.com"},
		{in: "a@example.com", want: "*@example.com"},
		{in: "demo@sub.example.com", want: "d***@sub.example.com"},
		{in: "not-an-email", want: "***"},
		{in: "@example.com", want: "***"},
	}
	for _, tc := range cases {
		if got := notify.MaskEmail(tc.in); got != tc.want {
			t.Errorf("MaskEmail(%q) = %q，期望 %q", tc.in, got, tc.want)
		}
	}
}

// TestMaskPhone 手机号脱敏保留前 3 位与后 4 位，位数不足时整体打码。
func TestMaskPhone(t *testing.T) {
	cases := []struct {
		in   string
		want string
	}{
		{in: "13800138000", want: "138****8000"},
		{in: "+8613800138000", want: "+86****8000"},
		// 位数不足 7 位时整体打码，避免脱敏后反而暴露全部内容
		{in: "123456", want: "***"},
		{in: "", want: "***"},
	}
	for _, tc := range cases {
		if got := notify.MaskPhone(tc.in); got != tc.want {
			t.Errorf("MaskPhone(%q) = %q，期望 %q", tc.in, got, tc.want)
		}
	}
}

// TestDisplayNeverLeaksFullTarget 脱敏结果必须比原文短，
// 且不能包含完整的原始值 —— 这是回显给调用方的字段。
func TestDisplayNeverLeaksFullTarget(t *testing.T) {
	cases := []notify.Target{
		{Type: notify.TargetTypeEmail, Value: "someone@example.com"},
		{Type: notify.TargetTypePhone, Value: "+8613800138000"},
		{Type: "unknown", Value: "whatever"},
	}
	for _, target := range cases {
		display := target.Display()
		if display == target.Value {
			t.Errorf("Display() 未脱敏: %q", display)
		}
		if strings.Contains(display, target.Value) && target.Value != "" {
			t.Errorf("Display() = %q 仍包含完整原文 %q", display, target.Value)
		}
	}
}

// TestUnconfiguredSenderFailsExplicitly 未接入通道时必须显式报错。
//
// 静默成功会让调用方以为验证码发出去了，用户却永远收不到 —— 这是最难排查的一类问题。
func TestUnconfiguredSenderFailsExplicitly(t *testing.T) {
	err := notify.Unconfigured{}.Send(context.Background(),
		notify.Target{Type: notify.TargetTypeEmail, Value: "a@b.com"}, "123456", time.Minute)
	if !errors.Is(err, notify.ErrChannelUnavailable) {
		t.Fatalf("应返回 ErrChannelUnavailable，实际: %v", err)
	}
}

// TestNewAlwaysReturnsUsableSender New 不允许返回 nil，否则调用方每次发送都要判空。
func TestNewAlwaysReturnsUsableSender(t *testing.T) {
	for _, provider := range []string{"", "smtp", "http", "SMTP", "  http  ", "unknown-provider"} {
		sender := notify.New(provider)
		if sender == nil {
			t.Fatalf("provider=%q 时 New 返回了 nil", provider)
		}
	}
}

// TestSupported 只有留空与已预留的通道名算合法，拼错要能被启动期校验拦下。
func TestSupported(t *testing.T) {
	for _, provider := range []string{"", "smtp", "http", "SMTP", " Http "} {
		if !notify.Supported(provider) {
			t.Errorf("provider=%q 应被识别为合法", provider)
		}
	}
	for _, provider := range []string{"sms", "mail", "smtp2", "smt"} {
		if notify.Supported(provider) {
			t.Errorf("provider=%q 不应被识别为合法", provider)
		}
	}
}
