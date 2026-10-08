// Package response 提供统一响应体的构造与写出。
package response

import (
	"errors"
	"net/http"

	"github.com/gin-gonic/gin"

	"project_id/internal/apperr"
	"project_id/internal/pkg/contextx"
	"project_id/internal/pkg/i18n"
)

// Body 是单对象响应体。
type Body struct {
	// Model 是响应体形状标识。
	Model string `json:"model"`
	// Data 是单对象载荷。
	Data any `json:"data"`
	// RequestID 是当前请求的追踪标识。
	RequestID string `json:"request_id"`
}

// ListBody 是数据集响应体。
type ListBody struct {
	// Model 是响应体形状标识。
	Model string `json:"model"`
	// Datas 是数据集合。
	Datas any `json:"datas"`
	// Total 是数据总条数。
	Total int64 `json:"total"`
	// RequestID 是当前请求的追踪标识。
	RequestID string `json:"request_id"`
}

// PageBody 是分页响应体。
type PageBody struct {
	// Model 是响应体形状标识。
	Model string `json:"model"`
	// Page 是分页元信息。
	Page PageMeta `json:"page"`
	// Result 是当前页结果。
	Result ListBody `json:"result"`
}

// PageMeta 描述分页元信息。
type PageMeta struct {
	// Current 是当前页码。
	Current int `json:"current"`
	// Size 是每页条数。
	Size int `json:"size"`
	// Total 是总条数。
	Total int64 `json:"total"`
}

// ErrorItem 是失败响应中的单条错误。
type ErrorItem struct {
	// Model 是错误条目形状标识。
	Model string `json:"model"`
	// Code 是稳定的错误码。
	Code string `json:"code"`
	// Message 是已按当前语言翻译的错误消息。
	Message string `json:"message"`
}

// ErrorSet 是失败响应中的错误集合。
type ErrorSet struct {
	// Model 是错误集合形状标识。
	Model string `json:"model"`
	// Datas 是错误条目集合。
	Datas []ErrorItem `json:"datas"`
	// Total 是错误条目总数。
	Total int `json:"total"`
}

// ErrorBody 是失败响应体。
type ErrorBody struct {
	// Model 是响应体形状标识。
	Model string `json:"model"`
	// Errors 是错误集合。
	Errors ErrorSet `json:"errors"`
	// RequestID 是当前请求的追踪标识。
	RequestID string `json:"request_id"`
}

// OK 写出单对象成功响应。
func OK(c *gin.Context, model string, data any) {
	c.JSON(http.StatusOK, Body{Model: model, Data: data, RequestID: contextx.RequestID(c.Request.Context())})
}

// List 写出数据集成功响应。
func List(c *gin.Context, model string, datas any, total int64) {
	c.JSON(http.StatusOK, ListBody{
		Model:     model,
		Datas:     datas,
		Total:     total,
		RequestID: contextx.RequestID(c.Request.Context()),
	})
}

// Page 写出分页成功响应。
func Page(c *gin.Context, model string, current, size int, total int64, datas any) {
	c.JSON(http.StatusOK, PageBody{
		Model: model,
		Page:  PageMeta{Current: current, Size: size, Total: total},
		Result: ListBody{
			Model:     "data.set",
			Datas:     datas,
			Total:     total,
			RequestID: contextx.RequestID(c.Request.Context()),
		},
	})
}

// NoContent 写出空结果响应，表示请求成功但没有返回数据。
func NoContent(c *gin.Context) {
	c.JSON(http.StatusOK, gin.H{"model": "empty", "request_id": contextx.RequestID(c.Request.Context())})
}

// Fail 写出失败响应。
func Fail(c *gin.Context, err error) {
	status, body := buildErrorBody(c, err)
	c.JSON(status, body)
}

// Abort 写出失败响应并终止后续处理器。
func Abort(c *gin.Context, err error) {
	status, body := buildErrorBody(c, err)
	c.AbortWithStatusJSON(status, body)
}

// Render 把任意错误渲染为可直接写出的状态码与响应体。
func Render(c *gin.Context, err error) (int, any) {
	return buildErrorBody(c, err)
}

// Resolve 把任意 error 归一化为 APIError；无法识别时归为内部错误。
func Resolve(err error) *apperr.APIError {
	var target *apperr.APIError
	if errors.As(err, &target) {
		return target
	}
	if err == nil {
		return apperr.ErrInternal
	}
	return apperr.ErrInternal.WithMessage("%s", err.Error())
}

// buildErrorBody 把归一化错误翻译为当前语言的失败响应体。
func buildErrorBody(c *gin.Context, err error) (int, ErrorBody) {
	apiErr := Resolve(err)
	message := apiErr.Message
	if message == "" || !apiErr.TranslateDisabled() {
		locale := contextx.Locale(c.Request.Context())
		message = i18n.T(locale, apiErr.Code)
	}
	return apiErr.Status, ErrorBody{
		Model: "errors",
		Errors: ErrorSet{
			Model: "data.set",
			Datas: []ErrorItem{{Model: "error", Code: apiErr.Code, Message: message}},
			Total: 1,
		},
		RequestID: contextx.RequestID(c.Request.Context()),
	}
}
