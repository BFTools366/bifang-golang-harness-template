package token_test

import (
	"errors"
	"testing"
	"time"

	"project_id/internal/pkg/token"
)

func newManager(accessTTL, refreshTTL time.Duration) *token.Manager {
	return token.NewManager("test-secret-key-at-least-16-chars", "test-issuer", accessTTL, refreshTTL)
}

// TestGenerateAndParse 覆盖签发与解析，并确认刷新令牌不能当访问令牌使用。
func TestGenerateAndParse(t *testing.T) {
	m := newManager(time.Hour, 24*time.Hour)

	pair, err := m.Generate(7, "alice", 3)
	if err != nil {
		t.Fatalf("签发令牌失败: %v", err)
	}
	if pair.AccessToken == "" || pair.RefreshToken == "" {
		t.Fatal("令牌为空")
	}
	if pair.ExpiresIn != int64(time.Hour.Seconds()) {
		t.Fatalf("ExpiresIn 不符: %d", pair.ExpiresIn)
	}

	claims, err := m.Parse(pair.AccessToken, token.TypeAccess)
	if err != nil {
		t.Fatalf("解析访问令牌失败: %v", err)
	}
	if claims.AccountID != 7 || claims.Username != "alice" || claims.TokenVersion != 3 {
		t.Fatalf("声明内容不符: %+v", claims)
	}

	// 刷新令牌不应被当作访问令牌通过
	if _, err := m.Parse(pair.RefreshToken, token.TypeAccess); !errors.Is(err, token.ErrWrongType) {
		t.Fatalf("令牌类型校验未生效: %v", err)
	}
}

// TestParseExpired 验证过期令牌返回 ErrExpired。
func TestParseExpired(t *testing.T) {
	m := newManager(-time.Minute, -time.Minute)

	pair, err := m.Generate(1, "bob", 0)
	if err != nil {
		t.Fatalf("签发令牌失败: %v", err)
	}
	if _, err := m.Parse(pair.AccessToken, token.TypeAccess); !errors.Is(err, token.ErrExpired) {
		t.Fatalf("过期令牌应返回 ErrExpired: %v", err)
	}
}

// TestParseMalformed 验证结构非法的令牌返回 ErrMalformed。
func TestParseMalformed(t *testing.T) {
	m := newManager(time.Hour, time.Hour)

	if _, err := m.Parse("not-a-jwt", token.TypeAccess); !errors.Is(err, token.ErrMalformed) {
		t.Fatalf("非法格式应返回 ErrMalformed: %v", err)
	}
}

// TestParseRejectsOtherSecret 验证用其他密钥签发的令牌校验失败。
func TestParseRejectsOtherSecret(t *testing.T) {
	issuer := newManager(time.Hour, time.Hour)
	other := token.NewManager("another-secret-key-16-chars", "test-issuer", time.Hour, time.Hour)

	pair, err := issuer.Generate(1, "carol", 0)
	if err != nil {
		t.Fatalf("签发令牌失败: %v", err)
	}
	if _, err := other.Parse(pair.AccessToken, token.TypeAccess); !errors.Is(err, token.ErrInvalid) {
		t.Fatalf("跨密钥令牌应校验失败: %v", err)
	}
}

// TestParseRejectsOtherIssuer 验证签发方与当前服务不一致的令牌校验失败。
func TestParseRejectsOtherIssuer(t *testing.T) {
	signer := token.NewManager("test-secret-key-at-least-16-chars", "issuer-a", time.Hour, time.Hour)
	verifier := token.NewManager("test-secret-key-at-least-16-chars", "issuer-b", time.Hour, time.Hour)

	pair, err := signer.Generate(1, "dave", 0)
	if err != nil {
		t.Fatalf("签发令牌失败: %v", err)
	}
	if _, err := verifier.Parse(pair.AccessToken, token.TypeAccess); err == nil {
		t.Fatal("签发方不一致时应校验失败")
	}
}
