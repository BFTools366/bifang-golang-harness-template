package response

import (
	"encoding/json"
	"errors"
	"net/http"
	"net/http/httptest"
	"testing"

	"github.com/gin-gonic/gin"

	"project_id/internal/apperr"
	"project_id/internal/pkg/contextx"
	"project_id/internal/pkg/i18n"
)

// newTestContext 构造带请求 ID 与语言的测试上下文。
func newTestContext(t *testing.T) (*gin.Context, *httptest.ResponseRecorder) {
	t.Helper()
	gin.SetMode(gin.TestMode)
	recorder := httptest.NewRecorder()
	c, _ := gin.CreateTestContext(recorder)
	c.Request = httptest.NewRequest(http.MethodGet, "/", nil)
	ctx := contextx.SetRequestID(c.Request.Context(), "test-request-id")
	ctx = contextx.SetLocale(ctx, i18n.DefaultLocale)
	c.Request = c.Request.WithContext(ctx)
	return c, recorder
}

// setupI18N 初始化多语言管理器，供错误消息翻译使用。
func setupI18N(t *testing.T) {
	t.Helper()
	if err := i18n.Setup([]string{"zh-CN", "en-US"}, "zh-CN"); err != nil {
		t.Fatalf("初始化多语言失败：%v", err)
	}
}

// TestOKProducesSingleObjectShape 验证单对象响应体形状。
func TestOKProducesSingleObjectShape(t *testing.T) {
	c, recorder := newTestContext(t)
	OK(c, "system", map[string]any{"name": "<project_id>"})

	var payload map[string]any
	if err := json.Unmarshal(recorder.Body.Bytes(), &payload); err != nil {
		t.Fatalf("响应体不是合法 JSON：%v", err)
	}
	if payload["model"] != "system" {
		t.Fatalf("期望 model 为 system，实际 %v", payload["model"])
	}
	if payload["request_id"] != "test-request-id" {
		t.Fatalf("期望 request_id 回填，实际 %v", payload["request_id"])
	}
	if _, ok := payload["data"]; !ok {
		t.Fatal("单对象响应体必须包含 data 字段")
	}
}

// TestListProducesDataSetShape 验证数据集响应体形状。
func TestListProducesDataSetShape(t *testing.T) {
	c, recorder := newTestContext(t)
	List(c, "data.set", []string{"a", "b"}, 2)

	var payload map[string]any
	if err := json.Unmarshal(recorder.Body.Bytes(), &payload); err != nil {
		t.Fatalf("响应体不是合法 JSON：%v", err)
	}
	if payload["model"] != "data.set" {
		t.Fatalf("期望 model 为 data.set，实际 %v", payload["model"])
	}
	if payload["total"].(float64) != 2 {
		t.Fatalf("期望 total 为 2，实际 %v", payload["total"])
	}
	if _, ok := payload["datas"]; !ok {
		t.Fatal("数据集响应体必须包含 datas 字段")
	}
}

// TestPageProducesGridShape 验证分页响应体形状。
func TestPageProducesGridShape(t *testing.T) {
	c, recorder := newTestContext(t)
	Page(c, "grid.result", 1, 10, 42, []string{"a"})

	var payload map[string]any
	if err := json.Unmarshal(recorder.Body.Bytes(), &payload); err != nil {
		t.Fatalf("响应体不是合法 JSON：%v", err)
	}
	if payload["model"] != "grid.result" {
		t.Fatalf("期望 model 为 grid.result，实际 %v", payload["model"])
	}
	page, ok := payload["page"].(map[string]any)
	if !ok {
		t.Fatal("分页响应体必须包含 page 对象")
	}
	if page["total"].(float64) != 42 {
		t.Fatalf("期望 page.total 为 42，实际 %v", page["total"])
	}
	result, ok := payload["result"].(map[string]any)
	if !ok {
		t.Fatal("分页响应体必须包含 result 对象")
	}
	if result["model"] != "data.set" {
		t.Fatalf("期望 result.model 为 data.set，实际 %v", result["model"])
	}
}

// TestNoContentProducesEmptyShape 验证空结果响应体形状。
func TestNoContentProducesEmptyShape(t *testing.T) {
	c, recorder := newTestContext(t)
	NoContent(c)

	var payload map[string]any
	if err := json.Unmarshal(recorder.Body.Bytes(), &payload); err != nil {
		t.Fatalf("响应体不是合法 JSON：%v", err)
	}
	if payload["model"] != "empty" {
		t.Fatalf("期望 model 为 empty，实际 %v", payload["model"])
	}
}

// TestAbortProducesErrorShape 验证失败响应体形状与状态码。
func TestAbortProducesErrorShape(t *testing.T) {
	setupI18N(t)
	c, recorder := newTestContext(t)
	Abort(c, apperr.ErrBadRequest)

	if recorder.Code != http.StatusBadRequest {
		t.Fatalf("期望状态码 400，实际 %d", recorder.Code)
	}
	var payload map[string]any
	if err := json.Unmarshal(recorder.Body.Bytes(), &payload); err != nil {
		t.Fatalf("响应体不是合法 JSON：%v", err)
	}
	if payload["model"] != "errors" {
		t.Fatalf("期望 model 为 errors，实际 %v", payload["model"])
	}
	errorsField, ok := payload["errors"].(map[string]any)
	if !ok {
		t.Fatal("失败响应体必须包含 errors 对象")
	}
	if errorsField["model"] != "data.set" {
		t.Fatalf("期望 errors.model 为 data.set，实际 %v", errorsField["model"])
	}
	items, ok := errorsField["datas"].([]any)
	if !ok || len(items) != 1 {
		t.Fatalf("期望 errors.datas 含 1 条错误，实际 %v", errorsField["datas"])
	}
	first, ok := items[0].(map[string]any)
	if !ok {
		t.Fatalf("错误条目形状不合法：%v", items[0])
	}
	if first["model"] != "error" {
		t.Fatalf("期望条目 model 为 error，实际 %v", first["model"])
	}
	if first["code"] != apperr.ErrBadRequest.Code {
		t.Fatalf("期望错误码 %s，实际 %v", apperr.ErrBadRequest.Code, first["code"])
	}
	if first["message"] == "" || first["message"] == apperr.ErrBadRequest.Code {
		t.Fatalf("错误消息必须经过 i18n 翻译，实际 %v", first["message"])
	}
}

// TestResolveFallsBackToInternalError 验证未知错误归为内部错误。
func TestResolveFallsBackToInternalError(t *testing.T) {
	resolved := Resolve(errors.New("database exploded"))
	if resolved.Status != http.StatusInternalServerError {
		t.Fatalf("期望状态码 500，实际 %d", resolved.Status)
	}
	if resolved.Code != apperr.ErrInternal.Code {
		t.Fatalf("期望错误码 %s，实际 %s", apperr.ErrInternal.Code, resolved.Code)
	}
}
