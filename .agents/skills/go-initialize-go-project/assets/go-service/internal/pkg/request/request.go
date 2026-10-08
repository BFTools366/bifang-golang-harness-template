// Package request 提供请求绑定与字段校验的翻译支持。
package request

import (
	"errors"
	"fmt"
	"reflect"
	"regexp"
	"strings"
	"sync"

	"github.com/gin-gonic/gin"
	"github.com/gin-gonic/gin/binding"
	"github.com/go-playground/validator/v10"

	"project_id/internal/apperr"
	"project_id/internal/pkg/contextx"
	"project_id/internal/pkg/i18n"
)

// usernamePattern 约束用户名字符集与长度。
var usernamePattern = regexp.MustCompile(`^[a-zA-Z0-9_]{3,32}$`)

var (
	// registerOnce 保证自定义校验规则只注册一次。
	registerOnce sync.Once
	// passwordLetterPattern 要求口令至少包含一个字母。
	passwordLetterPattern = regexp.MustCompile(`[A-Za-z]`)
	// passwordDigitPattern 要求口令至少包含一个数字。
	passwordDigitPattern = regexp.MustCompile(`[0-9]`)
)

// Bind 解析并校验请求体，失败时直接 panic 统一错误。
func Bind(c *gin.Context, target any) {
	if err := c.ShouldBindJSON(target); err != nil {
		panic(translate(c, err))
	}
}

// BindQuery 解析并校验查询参数，失败时直接 panic 统一错误。
func BindQuery(c *gin.Context, target any) {
	if err := c.ShouldBindQuery(target); err != nil {
		panic(translate(c, err))
	}
}

// BindURI 解析并校验路径参数，失败时直接 panic 统一错误。
func BindURI(c *gin.Context, target any) {
	if err := c.ShouldBindUri(target); err != nil {
		panic(translate(c, err))
	}
}

// RegisterValidation 注册自定义校验规则，并把字段错误映射到 json 标签名。
func RegisterValidation() {
	registerOnce.Do(func() {
		engine, ok := binding.Validator.Engine().(*validator.Validate)
		if !ok {
			return
		}
		engine.RegisterTagNameFunc(func(field reflect.StructField) string {
			name := strings.SplitN(field.Tag.Get("json"), ",", 2)[0]
			if name == "" || name == "-" {
				return field.Name
			}
			return name
		})
		_ = engine.RegisterValidation("username", func(level validator.FieldLevel) bool {
			return usernamePattern.MatchString(level.Field().String())
		})
		_ = engine.RegisterValidation("password", func(level validator.FieldLevel) bool {
			value := level.Field().String()
			if len(value) < 8 || len(value) > 64 {
				return false
			}
			return passwordLetterPattern.MatchString(value) && passwordDigitPattern.MatchString(value)
		})
	})
}

// translate 把绑定或校验错误翻译为统一 API 错误。
func translate(c *gin.Context, err error) error {
	var validationErrors validator.ValidationErrors
	if ok := errors.As(err, &validationErrors); ok {
		return apperr.ErrBadRequest.WithMessage("%s", joinFieldMessages(contextx.Locale(c.Request.Context()), validationErrors))
	}
	return apperr.ErrBadRequest
}

// joinFieldMessages 把字段级错误拼接为一条可读消息。
func joinFieldMessages(locale string, errors validator.ValidationErrors) string {
	parts := make([]string, 0, len(errors))
	for _, fieldError := range errors {
		parts = append(parts, fieldMessage(locale, fieldError))
	}
	return strings.Join(parts, "; ")
}

// fieldMessage 把单个字段错误按标签映射到对应词条。
func fieldMessage(locale string, fieldError validator.FieldError) string {
	field := fieldError.Field()
	switch fieldError.Tag() {
	case "required":
		return fmt.Sprintf("%s: %s", field, i18n.T(locale, "validate.required"))
	case "username":
		return fmt.Sprintf("%s: %s", field, i18n.T(locale, "validate.username"))
	case "password":
		return fmt.Sprintf("%s: %s", field, i18n.T(locale, "validate.password"))
	case "email":
		return fmt.Sprintf("%s: %s", field, i18n.T(locale, "validate.email"))
	case "min", "max", "len":
		return fmt.Sprintf("%s: %s", field, i18n.T(locale, "validate.length"))
	case "numeric", "number":
		return fmt.Sprintf("%s: %s", field, i18n.T(locale, "validate.number"))
	case "url":
		return fmt.Sprintf("%s: %s", field, i18n.T(locale, "validate.url"))
	case "oneof":
		return fmt.Sprintf("%s: %s", field, i18n.T(locale, "validate.oneof"))
	default:
		return fmt.Sprintf("%s: %s", field, i18n.T(locale, "validate.format"))
	}
}
