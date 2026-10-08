package middleware

import (
	"context"
	"errors"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"project_id/internal/apperr"
	"project_id/internal/model"
	"project_id/internal/pkg/token"

	"github.com/gin-gonic/gin"
)

// stubAuthenticator 记录被调用情况并返回固定账号，便于断言中间件的取令牌行为。
type stubAuthenticator struct {
	called bool
	raw    string
	err    error
}

func (s *stubAuthenticator) Authenticate(_ context.Context, rawToken string) (*model.Account, *token.Claims, error) {
	s.called = true
	s.raw = rawToken
	if s.err != nil {
		return nil, nil, s.err
	}
	const id model.ID = 1859123456789012480
	return &model.Account{Base: model.Base{ID: id}}, &token.Claims{AccountID: int64(id)}, nil
}

// newAuthEngine 构造 Auth -> ErrorHandler 的最小链路
func newAuthEngine(auth *stubAuthenticator) *gin.Engine {
	gin.SetMode(gin.TestMode)
	r := gin.New()
	r.Use(ErrorHandler(ErrorHandlerOptions{}))
	r.GET("/private", Auth(auth), func(c *gin.Context) { c.Status(http.StatusOK) })
	return r
}

// doAuthRequest 发送带指定请求头的 GET 请求并返回响应记录器。
func doAuthRequest(r *gin.Engine, target string, headers map[string]string) *httptest.ResponseRecorder {
	req := httptest.NewRequest(http.MethodGet, target, nil)
	for k, v := range headers {
		req.Header.Set(k, v)
	}
	w := httptest.NewRecorder()
	r.ServeHTTP(w, req)
	return w
}

// TestAuthAcceptsStandardAuthorization 只认 Authorization: Bearer <token>。
func TestAuthAcceptsStandardAuthorization(t *testing.T) {
	cases := []struct {
		name   string
		header string
	}{
		{"标准写法", "Bearer abc.def.ghi"},
		{"scheme 大小写不敏感", "bearer abc.def.ghi"},
		{"全大写 scheme", "BEARER abc.def.ghi"},
		{"多余空格", "Bearer    abc.def.ghi"},
	}

	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			auth := &stubAuthenticator{}
			r := newAuthEngine(auth)

			w := doAuthRequest(r, "/private", map[string]string{"Authorization": tc.header})

			if w.Code != http.StatusOK {
				t.Fatalf("期望 200，实际 %d，body=%s", w.Code, w.Body.String())
			}
			if auth.raw != "abc.def.ghi" {
				t.Fatalf("取到的令牌不符: %q", auth.raw)
			}
		})
	}
}

// TestAuthRejectsNonStandardWays 自定义头名、裸令牌、查询参数一律不兼容。
//
// 这是有意的收紧：不再支持 Auth 头、不再支持不带前缀的裸令牌、
// 也不支持 ?token= —— 令牌出现在 URL 里会进浏览器历史与各级访问日志。
func TestAuthRejectsNonStandardWays(t *testing.T) {
	cases := []struct {
		name       string
		target     string
		headers    map[string]string
		wantCode   int
		wantErrKey string
	}{
		{
			name:       "自定义 Auth 头不再生效",
			target:     "/private",
			headers:    map[string]string{"Auth": "Bearer abc.def.ghi"},
			wantCode:   http.StatusUnauthorized,
			wantErrKey: apperr.ErrTokenMissing.Code,
		},
		{
			name:       "裸令牌不接受",
			target:     "/private",
			headers:    map[string]string{"Authorization": "abc.def.ghi"},
			wantCode:   http.StatusUnauthorized,
			wantErrKey: apperr.ErrTokenMalformed.Code,
		},
		{
			name:       "前缀正确但令牌为空",
			target:     "/private",
			headers:    map[string]string{"Authorization": "Bearer "},
			wantCode:   http.StatusUnauthorized,
			wantErrKey: apperr.ErrTokenMalformed.Code,
		},
		{
			name:       "查询参数传令牌不接受",
			target:     "/private?token=abc.def.ghi",
			headers:    nil,
			wantCode:   http.StatusUnauthorized,
			wantErrKey: apperr.ErrTokenMissing.Code,
		},
		{
			name:       "完全没有鉴权头",
			target:     "/private",
			headers:    nil,
			wantCode:   http.StatusUnauthorized,
			wantErrKey: apperr.ErrTokenMissing.Code,
		},
	}

	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			auth := &stubAuthenticator{}
			r := newAuthEngine(auth)

			w := doAuthRequest(r, tc.target, tc.headers)

			if w.Code != tc.wantCode {
				t.Fatalf("期望 %d，实际 %d，body=%s", tc.wantCode, w.Code, w.Body.String())
			}
			if auth.called {
				t.Fatal("令牌未通过格式校验，不应调用 Authenticate")
			}
			if !strings.Contains(w.Body.String(), tc.wantErrKey) {
				t.Fatalf("响应应包含错误码 %s，实际: %s", tc.wantErrKey, w.Body.String())
			}
		})
	}
}

// TestAuthPropagatesAuthenticateError 校验失败的错误要原样透出（例如令牌过期）。
func TestAuthPropagatesAuthenticateError(t *testing.T) {
	auth := &stubAuthenticator{err: apperr.ErrTokenExpired}
	r := newAuthEngine(auth)

	w := doAuthRequest(r, "/private", map[string]string{"Authorization": "Bearer abc.def.ghi"})

	if w.Code != http.StatusUnauthorized {
		t.Fatalf("期望 401，实际 %d", w.Code)
	}
	if !strings.Contains(w.Body.String(), apperr.ErrTokenExpired.Code) {
		t.Fatalf("应返回令牌过期错误，实际: %s", w.Body.String())
	}
}

// TestOptionalAuthNeverRejects 可选鉴权：任何情况都放行，仅在有合法令牌时注入账号。
func TestOptionalAuthNeverRejects(t *testing.T) {
	cases := []struct {
		name       string
		headers    map[string]string
		wantCalled bool
	}{
		{"合法令牌", map[string]string{"Authorization": "Bearer abc.def.ghi"}, true},
		{"无令牌", nil, false},
		{"格式非法", map[string]string{"Authorization": "abc.def.ghi"}, false},
	}

	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			auth := &stubAuthenticator{}
			gin.SetMode(gin.TestMode)
			r := gin.New()
			r.Use(ErrorHandler(ErrorHandlerOptions{}))
			r.GET("/maybe", OptionalAuth(auth), func(c *gin.Context) { c.Status(http.StatusOK) })

			w := doAuthRequest(r, "/maybe", tc.headers)

			if w.Code != http.StatusOK {
				t.Fatalf("可选鉴权不应拦截，实际 %d", w.Code)
			}
			if auth.called != tc.wantCalled {
				t.Fatalf("Authenticate 调用情况不符: 期望 %v，实际 %v", tc.wantCalled, auth.called)
			}
		})
	}
}

// TestExtractToken 直接覆盖取令牌的边界。
func TestExtractToken(t *testing.T) {
	cases := []struct {
		name    string
		header  string
		want    string
		wantErr error
	}{
		{"正常", "Bearer tok", "tok", nil},
		{"小写 scheme", "bearer tok", "tok", nil},
		{"空头", "", "", apperr.ErrTokenMissing},
		{"只有空格", "   ", "", apperr.ErrTokenMissing},
		{"无空格分隔", "Bearertok", "", apperr.ErrTokenMalformed},
		{"裸令牌", "tok", "", apperr.ErrTokenMalformed},
		{"空令牌", "Bearer ", "", apperr.ErrTokenMalformed},
	}

	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			got, err := extractToken(tc.header)
			if tc.wantErr != nil {
				if !errors.Is(err, tc.wantErr) {
					t.Fatalf("期望错误 %v，实际 %v", tc.wantErr, err)
				}
				return
			}
			if err != nil {
				t.Fatalf("不应报错: %v", err)
			}
			if got != tc.want {
				t.Fatalf("令牌不符: 期望 %q，实际 %q", tc.want, got)
			}
		})
	}
}
