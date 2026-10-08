package middleware

import (
	"bytes"
	"encoding/json"
	"io"
	"net/url"
	"strings"
	"time"

	"github.com/gin-gonic/gin"
	"github.com/sirupsen/logrus"

	"project_id/internal/pkg/contextx"
)

const (
	// defaultBodyLimit 是未配置时记录的请求体最大字节数。
	defaultBodyLimit = 4096
	// maskedValue 是脱敏后替换的文本。
	maskedValue = "****"
	// maxBufferedBody 是缓冲请求体的上限，超过后不再记录正文。
	maxBufferedBody = 1 << 20
	// latencyStartKey 是请求起始时间在 gin 上下文中的键。
	latencyStartKey = "middleware.latency_start"
)

// defaultSensitiveKeys 是未配置时默认脱敏的字段名。
var defaultSensitiveKeys = []string{
	"password", "passwd", "token", "secret", "authorization",
	"access_token", "refresh_token", "cookie", "api_key",
}

// LoggerOptions 是访问日志中间件的配置。
type LoggerOptions struct {
	// Logger 是进程日志器。
	Logger *logrus.Logger
	// LogBody 表示是否记录请求体。
	LogBody bool
	// LogHeader 表示是否记录请求头。
	LogHeader bool
	// BodyLimit 是记录的请求体最大字节数。
	BodyLimit int
	// SensitiveKeys 是需要脱敏的字段名。
	SensitiveKeys []string
	// SkipPaths 是不记录日志的路径前缀。
	SkipPaths []string
}

// Logger 记录访问日志，并按配置对请求头与请求体脱敏。
func Logger(options LoggerOptions) gin.HandlerFunc {
	limit := options.BodyLimit
	if limit <= 0 {
		limit = defaultBodyLimit
	}
	sensitive := buildSensitiveSet(options.SensitiveKeys)
	skipPaths := options.SkipPaths
	logger := options.Logger

	return func(c *gin.Context) {
		if matchedPrefix(c.Request.URL.Path, skipPaths) {
			c.Next()
			return
		}
		rawBody := readRequestBody(c, options.LogBody)
		capture := &bodyCaptureWriter{ResponseWriter: c.Writer, body: &bytes.Buffer{}}
		c.Writer = capture
		c.Set(latencyStartKey, time.Now())

		c.Next()

		entry := logger.WithFields(logrus.Fields{
			"request_id": contextx.RequestID(c.Request.Context()),
			"method":     c.Request.Method,
			"path":       c.Request.URL.Path,
			"status":     c.Writer.Status(),
			"client_ip":  c.ClientIP(),
			"latency_ms": latencyMillis(c),
			"locale":     contextx.Locale(c.Request.Context()),
		})
		if options.LogHeader {
			entry = entry.WithField("headers", flattenHeaders(c.Request.Header, sensitive))
		}
		if rawBody != "" {
			entry = entry.WithField("body", truncateBody(maskBody(rawBody, c.ContentType(), sensitive), limit))
		}
		if capture.body.Len() > 0 {
			entry = entry.WithField("response", truncateBody(capture.body.String(), limit))
		}

		switch {
		case c.Writer.Status() >= 500:
			entry.Error("访问日志")
		case c.Writer.Status() >= 400:
			entry.Warn("访问日志")
		default:
			entry.Info("访问日志")
		}
	}
}

// bodyCaptureWriter 在写出响应时同步缓冲一份响应正文用于日志。
type bodyCaptureWriter struct {
	// ResponseWriter 是被包装的原始响应写入器。
	gin.ResponseWriter
	// body 缓冲已写出的响应正文。
	body *bytes.Buffer
}

// Write 写出响应并缓冲正文。
func (w *bodyCaptureWriter) Write(data []byte) (int, error) {
	w.body.Write(data)
	return w.ResponseWriter.Write(data)
}

// WriteString 写出字符串响应并缓冲正文。
//
// 必须实现该方法，否则 c.String 不会经过 Write 而无法进入日志。
func (w *bodyCaptureWriter) WriteString(value string) (int, error) {
	w.body.WriteString(value)
	return w.ResponseWriter.WriteString(value)
}

// readRequestBody 按需缓冲请求体，并把可重复读的正文放回请求。
func readRequestBody(c *gin.Context, enabled bool) string {
	if !enabled || c.Request.Body == nil {
		return ""
	}
	buffered, err := io.ReadAll(io.LimitReader(c.Request.Body, maxBufferedBody))
	if err != nil {
		return ""
	}
	c.Request.Body = &multiReadCloser{Reader: bytes.NewReader(buffered), closer: c.Request.Body}
	if len(buffered) == 0 {
		return ""
	}
	return string(buffered)
}

// multiReadCloser 让被缓冲过的请求体仍可按原语义关闭。
type multiReadCloser struct {
	// Reader 是缓冲后的正文读取器。
	io.Reader
	// closer 是原始请求体，用于释放底层资源。
	closer io.Closer
}

// Close 关闭底层原始请求体。
func (m *multiReadCloser) Close() error {
	return m.closer.Close()
}

// latencyMillis 返回请求从进入中间件到写出响应的毫秒数。
func latencyMillis(c *gin.Context) int64 {
	start, ok := c.Get(latencyStartKey)
	if !ok {
		return 0
	}
	began, ok := start.(time.Time)
	if !ok {
		return 0
	}
	return time.Since(began).Milliseconds()
}

// matchedPrefix 判断路径是否命中跳过的前缀列表。
func matchedPrefix(path string, prefixes []string) bool {
	for _, prefix := range prefixes {
		if prefix == "" {
			continue
		}
		if strings.HasPrefix(path, prefix) {
			return true
		}
	}
	return false
}

// buildSensitiveSet 把配置的敏感字段名归一化为查找集合。
func buildSensitiveSet(keys []string) map[string]struct{} {
	source := keys
	if len(source) == 0 {
		source = defaultSensitiveKeys
	}
	result := make(map[string]struct{}, len(source))
	for _, key := range source {
		result[normalizeKey(key)] = struct{}{}
	}
	return result
}

// normalizeKey 去掉分隔符并统一为小写，便于按字段名匹配。
func normalizeKey(key string) string {
	replacer := strings.NewReplacer("_", "", "-", "", ".", "")
	return replacer.Replace(strings.ToLower(strings.TrimSpace(key)))
}

// flattenHeaders 把请求头展开为可记录的键值对，并脱敏敏感头。
func flattenHeaders(headers map[string][]string, sensitive map[string]struct{}) map[string]string {
	result := make(map[string]string, len(headers))
	for name, values := range headers {
		joined := strings.Join(values, ", ")
		if _, ok := sensitive[normalizeKey(name)]; ok {
			joined = maskedValue
		}
		result[name] = joined
	}
	return result
}

// maskBody 按内容类型对请求体脱敏。
func maskBody(body string, contentType string, sensitive map[string]struct{}) string {
	trimmed := strings.TrimSpace(body)
	if trimmed == "" {
		return ""
	}
	lower := strings.ToLower(contentType)
	switch {
	case strings.Contains(lower, "json"), strings.HasPrefix(trimmed, "{"), strings.HasPrefix(trimmed, "["):
		return maskJSON(trimmed, sensitive)
	case strings.Contains(lower, "form-urlencoded"):
		return maskForm(trimmed, sensitive)
	default:
		return maskedValue
	}
}

// maskJSON 递归脱敏 JSON 文本中的敏感字段。
func maskJSON(body string, sensitive map[string]struct{}) string {
	var decoded any
	if err := json.Unmarshal([]byte(body), &decoded); err != nil {
		return maskedValue
	}
	encoded, err := json.Marshal(maskValue(decoded, sensitive))
	if err != nil {
		return maskedValue
	}
	return string(encoded)
}

// maskForm 脱敏表单编码文本中的敏感字段。
func maskForm(body string, sensitive map[string]struct{}) string {
	values, err := url.ParseQuery(body)
	if err != nil {
		return maskedValue
	}
	for key := range values {
		if _, ok := sensitive[normalizeKey(key)]; ok {
			values.Set(key, maskedValue)
		}
	}
	return values.Encode()
}

// maskValue 递归遍历解析后的结构并把敏感字段替换为脱敏文本。
func maskValue(value any, sensitive map[string]struct{}) any {
	switch typed := value.(type) {
	case map[string]any:
		result := make(map[string]any, len(typed))
		for key, item := range typed {
			if _, ok := sensitive[normalizeKey(key)]; ok {
				result[key] = maskedValue
				continue
			}
			result[key] = maskValue(item, sensitive)
		}
		return result
	case []any:
		result := make([]any, 0, len(typed))
		for _, item := range typed {
			result = append(result, maskValue(item, sensitive))
		}
		return result
	default:
		return value
	}
}

// truncateBody 把正文截断到配置的长度上限。
func truncateBody(body string, limit int) string {
	if limit <= 0 || len(body) <= limit {
		return body
	}
	return body[:limit] + "...(truncated)"
}
