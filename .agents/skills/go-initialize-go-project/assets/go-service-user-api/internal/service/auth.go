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
	accounts *repository.AccountRepository
	orgs     *repository.OrgRepository
	tokens   *token.Manager
}

// NewAuthService 创建认证业务实例
func NewAuthService(accounts *repository.AccountRepository, orgs *repository.OrgRepository, tokens *token.Manager) *AuthService {
	return &AuthService{accounts: accounts, orgs: orgs, tokens: tokens}
}

// Register 注册新账号。
//
// 账号与它的默认组织在同一个事务里落库：两者是注册这一步的原子结果，
// 只成功一半会留下「有账号没组织」的脏数据。
func (s *AuthService) Register(ctx context.Context, req *dto.RegisterRequest) (*model.Account, error) {
	username := strings.TrimSpace(req.Username)
	email := strings.ToLower(strings.TrimSpace(req.Email))

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
		Password: hashed,
		Nickname: nickname,
		Status:   model.AccountStatusEnabled,
	}

	// 事务边界走仓储的 Transaction，service 不 import gorm ——
	// 否则 service 会与 ORM 耦合，违反 core-first 的 ORM 解耦硬规则。
	err = s.accounts.Transaction(ctx, func(tx *repository.Repository[model.Account]) error {
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
