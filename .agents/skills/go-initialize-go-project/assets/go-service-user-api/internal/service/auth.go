package service

import (
	"context"
	"errors"
	"strings"

	"project_id/internal/apperr"
	"project_id/internal/dto"
	"project_id/internal/model"
	"project_id/internal/pkg/hash"
	"project_id/internal/pkg/token"
	"project_id/internal/repository"
)

// AuthService 认证业务
type AuthService struct {
	accounts     *repository.AccountRepository
	orgs         *repository.OrgRepository
	verification *VerificationService
	tokens       *token.Manager
}

// NewAuthService 创建认证业务实例
func NewAuthService(accounts *repository.AccountRepository, orgs *repository.OrgRepository, verification *VerificationService, tokens *token.Manager) *AuthService {
	return &AuthService{accounts: accounts, orgs: orgs, verification: verification, tokens: tokens}
}

// Register 注册新账号。
//
// 账号与它的默认组织在同一个事务里落库：两者是注册这一步的原子结果，
// 只成功一半会留下「有账号没组织」的脏数据。
//
// 验证码的消费也在这个事务里（见 Consume）：用户名/邮箱查重、密码哈希
// 这些步骤都排在事务之前，任何一步失败都不会把用户刚收到的验证码吃掉，
// 用户能拿着同一个码重试。
func (s *AuthService) Register(ctx context.Context, req *dto.RegisterRequest) (*model.Account, error) {
	username := strings.TrimSpace(req.Username)
	email := strings.ToLower(strings.TrimSpace(req.Email))

	// 手机号可选。归一化规则与验证码发送侧共用同一份实现，
	// 否则会出现「发得出去但校验永远不通过」这种极难排查的问题。
	var phone *string
	if raw := strings.TrimSpace(req.Phone); raw != "" {
		normalized, err := s.verification.NormalizeTarget(model.VerificationTargetPhone, raw)
		if err != nil {
			return nil, err
		}
		phone = &normalized.Value
	}

	codeID, err := s.verifyRegisterCode(ctx, req, email)
	if err != nil {
		return nil, err
	}

	occupied, err := s.accounts.ExistsUsername(ctx, username)
	if err != nil {
		return nil, apperr.ErrInternal
	}
	if occupied {
		return nil, apperr.ErrAccountUsernameTaken
	}
	occupied, err = s.accounts.ExistsEmail(ctx, email)
	if err != nil {
		return nil, apperr.ErrInternal
	}
	if occupied {
		return nil, apperr.ErrAccountExists
	}
	if phone != nil {
		occupied, err = s.accounts.ExistsPhone(ctx, *phone)
		if err != nil {
			return nil, apperr.ErrInternal
		}
		if occupied {
			return nil, apperr.ErrPhoneTaken
		}
	}

	hashed, err := hash.Password(req.Password)
	if err != nil {
		return nil, apperr.ErrInternal
	}

	nickname := strings.TrimSpace(req.Nickname)
	if nickname == "" {
		nickname = username
	}

	account := &model.Account{
		Username: username,
		Email:    email,
		Phone:    phone,
		Password: hashed,
		Nickname: nickname,
		Status:   model.AccountStatusEnabled,
	}

	// 事务边界走仓储的 Transaction，service 不 import gorm ——
	// 否则 service 会与 ORM 耦合，违反 core-first 的 ORM 解耦硬规则。
	err = s.accounts.Transaction(ctx, func(tx *repository.Repository[model.Account]) error {
		if err := s.verification.Consume(ctx, tx, codeID); err != nil {
			return err
		}
		if err := tx.Create(ctx, account); err != nil {
			return apperr.ErrInternal
		}
		org := &model.Org{
			Name:      DefaultOrgName(account.Nickname, account.Username),
			OwnerID:   account.ID,
			IsDefault: true,
		}
		if err := s.orgs.WithDB(tx.DB()).Create(ctx, org); err != nil {
			return apperr.ErrInternal
		}
		return nil
	})
	if err != nil {
		// 脚手架的错误码是指针类型（Error 为指针接收者），断言目标必须用指针。
		var apiErr *apperr.APIError
		if errors.As(err, &apiErr) {
			return nil, apiErr
		}
		return nil, apperr.ErrInternal
	}
	return account, nil
}

// verifyRegisterCode 按配置校验注册验证码，返回待消费的记录主键（未启用时为 0）。
//
// 校验目标由 code_type 决定，默认邮箱：邮箱是注册必填项，也是账号的天然锚点；
// 选了 phone 就必须带上手机号，否则没有可匹配的目标。
func (s *AuthService) verifyRegisterCode(ctx context.Context, req *dto.RegisterRequest, email string) (model.ID, error) {
	if !s.verification.Enabled() {
		return 0, nil
	}

	targetType, rawTarget := model.VerificationTargetEmail, email
	if strings.EqualFold(strings.TrimSpace(req.CodeType), model.VerificationTargetPhone) {
		targetType = model.VerificationTargetPhone
		rawTarget = strings.TrimSpace(req.Phone)
		if rawTarget == "" {
			return 0, apperr.ErrVerificationTargetMissing.WithExtra("target_type", model.VerificationTargetPhone)
		}
	}

	target, err := s.verification.NormalizeTarget(targetType, rawTarget)
	if err != nil {
		return 0, err
	}
	return s.verification.Verify(ctx, model.VerificationSceneRegister, target.Type, target.Value, req.Code)
}

// ResetPassword 用验证码重置密码（忘记密码）。
//
// 与「修改密码」的区别：改密靠登录态 + 原密码证明身份；重置是匿名入口，
// 唯一凭证就是验证码。因此成功后必须吊销该账号的全部已签发令牌 ——
// 「账号疑似被盗 → 重置密码」之后如果旧令牌还有效，重置就白做了。
//
// 验证码的消费与改密在同一事务：改密失败时验证码要回到待用状态，
// 用户能拿着同一个码重试（与 Register 的处理一致）。
func (s *AuthService) ResetPassword(ctx context.Context, req *dto.ResetPasswordRequest) error {
	if !s.verification.Enabled() {
		return apperr.ErrVerificationDisabled
	}

	// 归一化规则与发码侧共用同一份实现，否则会出现
	// 「码发得出去但永远匹配不上」这种极难排查的问题。
	target, err := s.verification.NormalizeTarget(req.TargetType, req.Target)
	if err != nil {
		return err
	}

	account, err := s.accounts.FindByTarget(ctx, target.Type, target.Value)
	if err != nil {
		return apperr.ErrInternal
	}
	if account == nil {
		return apperr.ErrVerificationTargetNotRegistered.WithExtra("target", target.Display())
	}
	// 被禁用的账号不给重置：重置完也登不进来，只会让用户以为密码没生效
	if !account.IsEnabled() {
		return apperr.ErrAccountDisabled
	}

	codeID, err := s.verification.Verify(ctx, model.VerificationSceneResetPassword, target.Type, target.Value, req.Code)
	if err != nil {
		return err
	}

	hashed, err := hash.Password(req.NewPassword)
	if err != nil {
		return apperr.ErrInternal
	}

	err = s.accounts.Transaction(ctx, func(tx *repository.Repository[model.Account]) error {
		if err := s.verification.Consume(ctx, tx, codeID); err != nil {
			return err
		}
		// 改密与 token_version 自增落在同一条 UPDATE 里（见 UpdatePassword）：
		// 分开写会留下「密码已换、旧令牌仍然有效」的窗口，
		// 而这正是重置密码最不该有的窗口。
		if err := s.accounts.WithDB(tx.DB()).UpdatePassword(ctx, account.ID, hashed); err != nil {
			return apperr.ErrInternal
		}
		return nil
	})
	if err != nil {
		var apiErr *apperr.APIError
		if errors.As(err, &apiErr) {
			return apiErr
		}
		return apperr.ErrInternal
	}
	return nil
}

// Login 登录并签发令牌
func (s *AuthService) Login(ctx context.Context, req *dto.LoginRequest, meta dto.ClientMeta) (*dto.AuthResponse, error) {
	keyword := strings.TrimSpace(req.Account)

	account, err := s.accounts.FindByUsernameOrEmail(ctx, keyword)
	if err != nil {
		return nil, apperr.ErrInternal
	}
	// 账号不存在与密码错误返回同一错误，避免账号枚举
	if account == nil || !hash.VerifyPassword(account.Password, req.Password) {
		return nil, apperr.ErrCredentialsInvalid
	}
	if !account.IsEnabled() {
		return nil, apperr.ErrAccountDisabled
	}

	pair, err := s.tokens.Generate(int64(account.ID), account.Username, account.TokenVersion)
	if err != nil {
		return nil, apperr.ErrTokenSignFailed
	}
	if err := s.accounts.TouchLogin(ctx, account.ID, meta.IP); err != nil {
		// 记录登录信息失败不影响登录结果
		_ = err
	}

	return &dto.AuthResponse{Token: pair, Account: dto.NewAccount(account)}, nil
}

// Refresh 用刷新令牌换取新的令牌对
func (s *AuthService) Refresh(ctx context.Context, refreshToken string) (*dto.AuthResponse, error) {
	claims, err := s.tokens.Parse(refreshToken, token.TypeRefresh)
	if err != nil {
		return nil, apperr.ErrTokenInvalid
	}

	account, err := s.accounts.GetByID(ctx, model.ID(claims.AccountID))
	if err != nil {
		return nil, apperr.ErrInternal
	}
	if account == nil {
		return nil, apperr.ErrAccountNotFound
	}
	if !account.IsEnabled() {
		return nil, apperr.ErrAccountDisabled
	}
	if account.TokenVersion != claims.TokenVersion {
		return nil, apperr.ErrTokenRevoked
	}

	pair, err := s.tokens.Generate(int64(account.ID), account.Username, account.TokenVersion)
	if err != nil {
		return nil, apperr.ErrTokenSignFailed
	}
	return &dto.AuthResponse{Token: pair, Account: dto.NewAccount(account)}, nil
}

// Logout 登出：递增令牌版本，吊销该账号全部已签发令牌
func (s *AuthService) Logout(ctx context.Context, accountID model.ID) error {
	if err := s.accounts.BumpTokenVersion(ctx, accountID); err != nil {
		return apperr.ErrInternal
	}
	return nil
}

// Authenticate 校验访问令牌并加载账号，实现 middleware.Authenticator。
// 同时返回令牌声明，便于中间件把声明写入请求上下文。
func (s *AuthService) Authenticate(ctx context.Context, rawToken string) (*model.Account, *token.Claims, error) {
	claims, err := s.tokens.Parse(rawToken, token.TypeAccess)
	if err != nil {
		switch {
		case errors.Is(err, token.ErrExpired):
			return nil, nil, apperr.ErrTokenExpired
		case errors.Is(err, token.ErrMalformed):
			return nil, nil, apperr.ErrTokenMalformed
		case errors.Is(err, token.ErrWrongType):
			return nil, nil, apperr.ErrTokenWrongType
		default:
			return nil, nil, apperr.ErrTokenInvalid
		}
	}

	account, err := s.accounts.GetByID(ctx, model.ID(claims.AccountID))
	if err != nil {
		return nil, nil, apperr.ErrInternal
	}
	if account == nil {
		return nil, nil, apperr.ErrAccountNotFound
	}
	if account.TokenVersion != claims.TokenVersion {
		return nil, nil, apperr.ErrTokenRevoked
	}
	if !account.IsEnabled() {
		return nil, nil, apperr.ErrAccountDisabled
	}
	return account, claims, nil
}
