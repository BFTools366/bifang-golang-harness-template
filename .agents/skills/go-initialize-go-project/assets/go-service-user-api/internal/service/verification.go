package service

import (
	"context"
	"errors"
	"regexp"
	"strconv"
	"strings"
	"time"

	"project_id/internal/apperr"
	"project_id/internal/config"
	"project_id/internal/dto"
	"project_id/internal/model"
	"project_id/internal/pkg/notify"
	"project_id/internal/pkg/verifycode"
	"project_id/internal/repository"
)

var (
	// emailPattern 比 net/mail 更严：要求域名里带点、顶级域至少两位，
	// 挡掉 "a@b" 这种 mail.ParseAddress 会放行但实际收不到信的地址。
	emailPattern = regexp.MustCompile(`^[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}$`)
	// e164Pattern 国际手机号：+ 开头，1-9 起头，总长 7-15 位数字
	e164Pattern = regexp.MustCompile(`^\+[1-9]\d{6,14}$`)
	// phoneSeparators 手机号里常见的分隔符，归一化时全部去掉
	phoneSeparators = strings.NewReplacer(" ", "", "-", "", "(", "", ")", "", ".", "")
)

// VerificationService 验证码业务。
//
// 职责边界：
//   - 生成、存储、校验验证码，以及发送频率与尝试次数的约束
//   - 通过 notify.Sender 投递，不关心具体是短信还是邮件
//   - 对账号表**只读**：场景要求「目标必须已绑定账号」时用它做存在性判断
//     （重置密码就是这种场景）。本服务不创建、不修改账号 ——
//     注册流程由 AuthService 编排。
type VerificationService struct {
	codes    *repository.VerificationCodeRepository
	accounts *repository.AccountRepository
	cfg      config.Verification
	sender   notify.Sender
}

// NewVerificationService 创建验证码业务实例
func NewVerificationService(codes *repository.VerificationCodeRepository, accounts *repository.AccountRepository, cfg config.Verification, sender notify.Sender) *VerificationService {
	if sender == nil {
		sender = notify.Unconfigured{}
	}
	return &VerificationService{codes: codes, accounts: accounts, cfg: cfg, sender: sender}
}

// Enabled 验证码功能是否启用（对所有场景生效）
func (s *VerificationService) Enabled() bool { return s.cfg.Enabled }

// Mock 是否处于模拟模式（验证码随响应返回）
func (s *VerificationService) Mock() bool { return s.cfg.Mock }

// NormalizeTarget 归一化并校验接收目标。
//
// 发送与校验两条路径都必须走这里 —— 两边归一化规则不一致的话，
// 会出现「发得出去但校验永远不通过」这种极难排查的问题。
func (s *VerificationService) NormalizeTarget(targetType, target string) (notify.Target, error) {
	value := strings.TrimSpace(target)

	switch strings.ToLower(strings.TrimSpace(targetType)) {
	case model.VerificationTargetEmail:
		value = strings.ToLower(value)
		if !emailPattern.MatchString(value) {
			return notify.Target{}, apperr.ErrVerificationTargetInvalid
		}
		return notify.Target{Type: notify.TargetTypeEmail, Value: value}, nil

	case model.VerificationTargetPhone:
		value = phoneSeparators.Replace(value)
		if !e164Pattern.MatchString(value) {
			return notify.Target{}, apperr.ErrVerificationTargetInvalid
		}
		return notify.Target{Type: notify.TargetTypePhone, Value: value}, nil

	default:
		return notify.Target{}, apperr.ErrVerificationTargetInvalid
	}
}

// Send 生成并投递验证码。
//
// mock 模式下不调用 Sender，把明文验证码放进响应；非 mock 模式下
// **先发送成功再落库** —— 发送失败还留一条有效记录，用户会永远等不到码，
// 而服务端看起来一切正常。
func (s *VerificationService) Send(ctx context.Context, req *dto.SendVerificationCodeRequest, ip string) (*dto.SendVerificationCodeResponse, error) {
	if !s.cfg.Enabled {
		return nil, apperr.ErrVerificationDisabled
	}

	scene, err := ResolveScene(req.Scene)
	if err != nil {
		return nil, err
	}
	target, err := s.NormalizeTarget(req.TargetType, req.Target)
	if err != nil {
		return nil, err
	}
	if err := s.checkSceneTarget(ctx, scene, target); err != nil {
		return nil, err
	}

	now := model.Now()
	if err := s.checkSendQuota(ctx, target, scene.Key, now); err != nil {
		return nil, err
	}

	code, err := verifycode.Generate(s.cfg.CodeLength)
	if err != nil {
		return nil, apperr.ErrVerificationGenerateFailed
	}

	if !s.cfg.Mock {
		if err := s.sender.Send(ctx, target, code, s.cfg.TTL); err != nil {
			if errors.Is(err, notify.ErrChannelUnavailable) {
				return nil, apperr.ErrVerificationChannelUnavailable
			}
			return nil, apperr.ErrVerificationSendFailed
		}
	}

	record := &model.VerificationCode{
		Target:     target.Value,
		TargetType: target.Type,
		Scene:      scene.Key,
		CodeHash:   verifycode.Hash(code, target.Value),
		Status:     model.VerificationCodeStatusPending,
		ExpiredAt:  now.Add(s.cfg.TTL),
		SendIP:     ip,
	}

	// 作废旧码与写入新码必须同一事务：只成功一半会留下「旧码已作废、
	// 新码没写进去」的状态，用户手里一个能用的码都没有。
	//
	// 事务边界走仓储的 Transaction，回调参数是泛型仓储；service 层借此
	// 不直接 import ORM 类型（core-first 的 ORM 解耦硬规则）。
	err = s.codes.Transaction(ctx, func(tx *repository.Repository[model.VerificationCode]) error {
		txRepo := s.codes.WithDB(tx.DB())
		if err := txRepo.RevokePending(ctx, target.Type, target.Value, scene.Key); err != nil {
			return err
		}
		return txRepo.Create(ctx, record)
	})
	if err != nil {
		return nil, apperr.ErrVerificationSaveFailed
	}

	resp := &dto.SendVerificationCodeResponse{
		Target:      target.Display(),
		TargetType:  target.Type,
		Scene:       scene.Key,
		ExpiresIn:   int(s.cfg.TTL.Seconds()),
		ResendAfter: int(s.cfg.ResendInterval.Seconds()),
		Mock:        s.cfg.Mock,
	}
	if s.cfg.Mock {
		resp.Code = code
	}
	return resp, nil
}

// checkSceneTarget 执行场景对接收目标的额外要求。
//
// 目前只有「目标必须已绑定账号」一条（重置密码）。放在服务层而不是
// 调用方，是为了让这条约束无法被绕过 —— Send 是唯一的发送入口。
//
// 注意这里返回的是「尚未注册」而不是「验证码无效」：发送阶段还没有码，
// 说「码不对」会让调用方完全摸不着头脑。
func (s *VerificationService) checkSceneTarget(ctx context.Context, scene VerificationScene, target notify.Target) error {
	if !scene.RequireAccount {
		return nil
	}

	account, err := s.accounts.FindByTarget(ctx, target.Type, target.Value)
	if err != nil {
		return apperr.ErrInternal
	}
	if account == nil {
		// 这里会暴露「该邮箱/手机号是否已注册」。取舍见 README「验证码」章节：
		// 不暴露的话，用户拿到的是一个永远用不上的码，且没有任何反馈。
		return apperr.ErrVerificationTargetNotRegistered.WithExtra("target", target.Display())
	}
	return nil
}

// checkSendQuota 检查重发间隔与每日上限。
//
// now 由调用方传入（unix 秒），保证「取最新一条」与「算时间窗口」用的是
// 同一个时刻 —— 两次取当前时间跨过整秒边界时，窗口会差一秒。
func (s *VerificationService) checkSendQuota(ctx context.Context, target notify.Target, scene string, now model.Timestamp) error {
	// 取不限状态的最新一条：刚发过的码可能已经被消费或作废，
	// 但「刚刚发过」这个事实仍然要拦住下一次发送
	latest, err := s.codes.Latest(ctx, target.Type, target.Value, scene)
	if err != nil {
		return apperr.ErrInternal
	}
	if latest != nil && s.cfg.ResendInterval > 0 {
		// created_time 与 now 同为 model.Timestamp（unix 秒），Sub 直接给出时长。
		if elapsed := now.Sub(latest.CreatedTime); elapsed < s.cfg.ResendInterval {
			wait := int((s.cfg.ResendInterval - elapsed).Seconds())
			if wait < 1 {
				wait = 1
			}
			return apperr.ErrVerificationTooFrequent.WithExtra("retry_after", strconv.Itoa(wait))
		}
	}

	sent, err := s.codes.CountSince(ctx, target.Type, target.Value, scene, now.Add(-24*time.Hour))
	if err != nil {
		return apperr.ErrInternal
	}
	if sent >= int64(s.cfg.DailyLimit) {
		return apperr.ErrVerificationDailyLimit
	}
	return nil
}

// Verify 校验验证码，通过则返回记录主键供后续消费。
//
// 本方法**只校验不消费**：调用方后面还有查重、建账号、改密码等步骤，
// 任何一步失败都应该让用户能拿着同一个码重试，所以消费动作放到
// 调用方的事务里（见 Consume）。
//
// scene 必须是 ResolveScene 解析出的落库值，不做归一化 ——
// 归一化只在入口处做一次，中途再做一次就多了一个可能不一致的地方。
//
// 调用方需先确认 Enabled()。
func (s *VerificationService) Verify(ctx context.Context, scene, targetType, target, code string) (model.ID, error) {
	code = strings.TrimSpace(code)
	if code == "" {
		return 0, apperr.ErrVerificationCodeRequired
	}

	record, err := s.codes.LatestPending(ctx, targetType, target, scene)
	if err != nil {
		return 0, apperr.ErrInternal
	}
	if record == nil {
		// 「没发过」「已被使用」「已被重发顶掉」在这里都归一为同一个错误：
		// 对调用方来说处理动作完全一样 —— 重新获取验证码。
		// 细分反而给了攻击者一个探测「这个邮箱是否正在注册」的接口。
		return 0, apperr.ErrVerificationCodeInvalid
	}

	now := model.Now()
	if record.IsExpired(now) {
		// 标记失败不影响拒绝结果，用户拿到的仍然是「已过期」
		_ = s.codes.Revoke(ctx, record.ID)
		return 0, apperr.ErrVerificationCodeExpired
	}
	if record.Attempts >= s.cfg.MaxAttempts {
		_ = s.codes.Revoke(ctx, record.ID)
		return 0, apperr.ErrVerificationAttemptsExceeded
	}
	if !verifycode.Match(record.CodeHash, code, target) {
		// 累加失败次数失败时仍然返回「验证码不正确」——
		// 少计一次数比放行一个错码安全得多
		_ = s.codes.IncrAttempts(ctx, record.ID)
		return 0, apperr.ErrVerificationCodeInvalid
	}
	return record.ID, nil
}

// Consume 在调用方的事务里把验证码标记为已使用。
//
// tx 是调用方 `Transaction` 回调给出的仓储；本方法用它的会话派生验证码
// 仓储，因此 service 层不必直接依赖 ORM 类型。
//
// 必须传事务：调用方的事务回滚时验证码要跟着回到待用状态，
// 否则「用户名冲突导致注册失败」这类失败会把用户刚收到的码一起吃掉。
//
// id 为 0 表示本次流程没有走验证码（功能关闭），直接放行。
func (s *VerificationService) Consume(ctx context.Context, tx *repository.Repository[model.Account], id model.ID) error {
	if id == 0 {
		return nil
	}
	consumed, err := s.codes.WithDB(tx.DB()).Consume(ctx, id, model.Now())
	if err != nil {
		return apperr.ErrVerificationSaveFailed
	}
	if !consumed {
		// 并发的两个请求抢同一个码，只有一个能拿到 —— 另一个必须被拒
		return apperr.ErrVerificationCodeConsumed
	}
	return nil
}
