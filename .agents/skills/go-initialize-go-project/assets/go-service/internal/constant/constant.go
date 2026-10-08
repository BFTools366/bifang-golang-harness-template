// Package constant 保存跨层复用的常量。
package constant

const (
	// RequestIDHeader 是请求追踪标识的请求头与响应头名称。
	RequestIDHeader = "X-Request-Id"
	// ContentLanguageHeader 是响应语言标识头名称。
	ContentLanguageHeader = "Content-Language"
	// HeaderAuthorization 是标准鉴权请求头名称，只认 `Authorization: Bearer <token>`。
	HeaderAuthorization = "Authorization"
	// ModelSingle 是单对象响应体形状标识。
	ModelSingle = "data"
	// ModelDataSet 是数据集响应体形状标识。
	ModelDataSet = "data.set"
	// ModelGrid 是分页响应体形状标识。
	ModelGrid = "grid.result"
	// ModelEmpty 是空结果响应体形状标识。
	ModelEmpty = "empty"
	// ModelErrors 是失败响应体形状标识。
	ModelErrors = "errors"
	// ModelError 是单条错误形状标识。
	ModelError = "error"
)
