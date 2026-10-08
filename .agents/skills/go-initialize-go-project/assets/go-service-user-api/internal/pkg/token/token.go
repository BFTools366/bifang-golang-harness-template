// Package token 封装 JWT 的签发与校验。
package token

import (
	"errors"
	"fmt"
	"time"

	"github.com/golang-jwt/jwt/v5"
)

// 令牌类型
const (
	TypeAccess  = "access"
	TypeRefresh = "refresh"
)

// 校验失败原因
var (
	ErrMalformed = errors.New("token malformed")
	ErrInvalid   = errors.New("token invalid")
	ErrExpired   = errors.New("token expired")
	ErrWrongType = errors.New("token type mismatch")
)

// Claims 自定义声明。
//
// 声明里只放「身份 + 令牌版本」，不放任何权限信息：
// 权限属于「账号在某个组织里的成员关系」，放进令牌会随成员关系变化而失效，
// 只能等令牌自然过期才能纠正。
//
// aid 用 `,string` 输出：雪花 ID 是 19 位，超过 JS 安全整数范围，
// 前端解 payload 时按 number 读会丢精度。
type Claims struct {
	AccountID    int64  `json:"aid,string"`
	Username     string `json:"username"`
	TokenVersion int64  `json:"ver"`
	Type         string `json:"typ"`
	jwt.RegisteredClaims
}

// Pair 令牌对
type Pair struct {
	AccessToken  string `json:"access_token"`
	RefreshToken string `json:"refresh_token"`
	TokenType    string `json:"token_type"`
	ExpiresIn    int64  `json:"expires_in"` // access_token 有效期（秒）
}

// Manager 令牌管理器
type Manager struct {
	secret     []byte
	issuer     string
	accessTTL  time.Duration
	refreshTTL time.Duration
}

// NewManager 创建令牌管理器
func NewManager(secret, issuer string, accessTTL, refreshTTL time.Duration) *Manager {
	return &Manager{
		secret:     []byte(secret),
		issuer:     issuer,
		accessTTL:  accessTTL,
		refreshTTL: refreshTTL,
	}
}

// AccessTTL 访问令牌有效期
func (m *Manager) AccessTTL() time.Duration { return m.accessTTL }

// Generate 签发令牌对
func (m *Manager) Generate(accountID int64, username string, tokenVersion int64) (*Pair, error) {
	access, err := m.sign(accountID, username, tokenVersion, TypeAccess, m.accessTTL)
	if err != nil {
		return nil, err
	}
	refresh, err := m.sign(accountID, username, tokenVersion, TypeRefresh, m.refreshTTL)
	if err != nil {
		return nil, err
	}
	return &Pair{
		AccessToken:  access,
		RefreshToken: refresh,
		TokenType:    "Bearer",
		ExpiresIn:    int64(m.accessTTL.Seconds()),
	}, nil
}

func (m *Manager) sign(accountID int64, username string, tokenVersion int64, typ string, ttl time.Duration) (string, error) {
	now := time.Now()
	claims := Claims{
		AccountID:    accountID,
		Username:     username,
		TokenVersion: tokenVersion,
		Type:         typ,
		RegisteredClaims: jwt.RegisteredClaims{
			Issuer:    m.issuer,
			Subject:   fmt.Sprintf("%d", accountID),
			IssuedAt:  jwt.NewNumericDate(now),
			NotBefore: jwt.NewNumericDate(now),
			ExpiresAt: jwt.NewNumericDate(now.Add(ttl)),
		},
	}
	return jwt.NewWithClaims(jwt.SigningMethodHS256, claims).SignedString(m.secret)
}

// Parse 解析并校验令牌，返回声明。typ 为空表示不校验令牌类型。
func (m *Manager) Parse(rawToken, typ string) (*Claims, error) {
	parsed, err := jwt.ParseWithClaims(rawToken, &Claims{}, func(t *jwt.Token) (any, error) {
		if _, ok := t.Method.(*jwt.SigningMethodHMAC); !ok {
			return nil, fmt.Errorf("%w: 非预期的签名算法 %v", ErrInvalid, t.Header["alg"])
		}
		return m.secret, nil
	}, jwt.WithIssuer(m.issuer))

	if err != nil {
		switch {
		case errors.Is(err, jwt.ErrTokenExpired):
			return nil, ErrExpired
		case errors.Is(err, jwt.ErrTokenMalformed):
			return nil, ErrMalformed
		default:
			return nil, ErrInvalid
		}
	}

	claims, ok := parsed.Claims.(*Claims)
	if !ok || !parsed.Valid {
		return nil, ErrInvalid
	}
	if typ != "" && claims.Type != typ {
		return nil, ErrWrongType
	}
	return claims, nil
}
