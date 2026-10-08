package service

import (
	"strings"

	"project_id/internal/apperr"
	"project_id/internal/model"
)

// VerificationScene 验证码场景策略。
//
// 场景 = 验证码的用途。它与接收目标（邮箱 / 手机号）正交：同一个邮箱
// 可以同时存在注册码与重置密码码，各自独立计数、独立过期。
//
// 为什么用注册表而不是 switch：场景之间的差异不在「码怎么发」，而在
// 「发给谁、发之前要确认什么」。把差异集中成一张表，新增场景就是加一行
// 数据 —— 而不是在 Send / Verify / dto 的 binding tag 里各改一处。
// 分散写法的代价是漏改一处就变成「能发不能验」这类极难排查的问题，
// 而 binding tag 漏改更糟：请求会在参数绑定阶段被拒成 400，
// 根本走不到那句可读的「不支持的验证码场景」。
type VerificationScene struct {
	// Key 落库值，必须与 model.VerificationScene* 常量一致
	Key string
	// RequireAccount 发送前要求该接收目标已绑定某个账号。
	//
	// 重置密码必须为 true：给一个未注册的邮箱发重置码，用户收得到、
	// 点进来却改不了任何东西，只能困惑地再试一次。
	// 注册则为 false —— 那正是账号还不存在的场景。
	RequireAccount bool
	// Description 用途说明，用于文档与日志
	Description string
}

// verificationScenes 全部场景。
//
// 新增场景：这里加一行 + model 里加一个常量，然后实现对应的业务流程。
var verificationScenes = []VerificationScene{
	{
		Key:            model.VerificationSceneRegister,
		RequireAccount: false,
		Description:    "注册新账号",
	},
	{
		Key:            model.VerificationSceneResetPassword,
		RequireAccount: true,
		Description:    "忘记密码时重置密码",
	},
}

// verificationSceneIndex 按 Key 索引，供 O(1) 查表
var verificationSceneIndex = func() map[string]VerificationScene {
	index := make(map[string]VerificationScene, len(verificationScenes))
	for _, scene := range verificationScenes {
		index[scene.Key] = scene
	}
	return index
}()

// VerificationScenes 返回全部场景的副本，供文档与测试使用。
//
// 返回副本而不是原切片：调用方改到切片元素会静默改变全局策略。
func VerificationScenes() []VerificationScene {
	out := make([]VerificationScene, len(verificationScenes))
	copy(out, verificationScenes)
	return out
}

// ResolveScene 解析场景 key。
//
// 留空回落为注册：接口最初只有注册一种场景，不带 scene 的调用方必须
// 保持原有行为。未知场景返回 ErrVerificationSceneUnsupported。
//
// 这个判断刻意放在服务层而不是 dto 的 binding tag 里，让「合法场景」
// 只有注册表这一个定义处，也保证错误码可读、可翻译。
func ResolveScene(scene string) (VerificationScene, error) {
	key := strings.ToLower(strings.TrimSpace(scene))
	if key == "" {
		key = model.VerificationSceneRegister
	}

	item, ok := verificationSceneIndex[key]
	if !ok {
		return VerificationScene{}, apperr.ErrVerificationSceneUnsupported.WithExtra("scene", key)
	}
	return item, nil
}
