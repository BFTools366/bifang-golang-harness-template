// Package i18n 提供按请求语言渲染错误词条的多语言支持。
package i18n

import (
	"embed"
	"fmt"
	"path"
	"sort"
	"strings"
	"sync"

	"go.yaml.in/yaml/v3"
	"golang.org/x/text/language"
)

//go:embed locales/*.yaml
var localeFS embed.FS

const (
	// localeDir 是词条文件所在的嵌入目录。
	localeDir = "locales"
	// DefaultLocale 是默认语言。
	DefaultLocale = "zh-CN"
	// defaultTemplate 是词条缺失时的兜底模板。
	defaultTemplate = "未定义的错误码：%s"
)

// mu 保护 manager 与 std 的并发读写。
var (
	mu      sync.RWMutex
	manager *Manager
	std     *Manager
)

// Manager 持有一套已加载的词条与语言匹配器。
type Manager struct {
	// supported 是受支持语言的规范化标签。
	supported []string
	// fallback 是回退语言。
	fallback string
	// matcher 负责把请求语言匹配到受支持语言。
	matcher language.Matcher
	// catalogs 按语言保存 key 到模板的映射。
	catalogs map[string]map[string]string
}

// NewManager 从嵌入目录加载词条并构造管理器。
func NewManager(supported []string, fallback string) (*Manager, error) {
	normalized := normalizeAll(supported)
	if len(normalized) == 0 {
		normalized = []string{DefaultLocale}
	}
	fallbackLocale := Normalize(fallback)
	if fallbackLocale == "" {
		fallbackLocale = normalized[0]
	}
	catalogs, err := loadCatalogs(normalized)
	if err != nil {
		return nil, err
	}
	tags := make([]language.Tag, 0, len(normalized))
	for _, locale := range normalized {
		tag, err := language.Parse(locale)
		if err != nil {
			return nil, fmt.Errorf("i18n: 无法解析语言标签 %s: %w", locale, err)
		}
		tags = append(tags, tag)
	}
	return &Manager{
		supported: normalized,
		fallback:  fallbackLocale,
		matcher:   language.NewMatcher(tags),
		catalogs:  catalogs,
	}, nil
}

// Setup 初始化包级默认管理器。
func Setup(supported []string, fallback string) error {
	created, err := NewManager(supported, fallback)
	if err != nil {
		return err
	}
	mu.Lock()
	defer mu.Unlock()
	manager = created
	std = created
	return nil
}

// Match 把 Accept-Language 头匹配到本服务支持的规范语言。
func Match(acceptLanguage string) string {
	current := current()
	if current == nil {
		return DefaultLocale
	}
	if strings.TrimSpace(acceptLanguage) == "" {
		return current.fallback
	}
	sanitized := sanitizeAcceptLanguage(acceptLanguage)
	if sanitized == "" {
		return current.fallback
	}
	tag, _, err := language.ParseAcceptLanguage(sanitized)
	if err != nil || len(tag) == 0 {
		return current.fallback
	}
	matched, _, _ := current.matcher.Match(tag...)
	return Normalize(matched.String())
}

// T 用给定语言渲染词条；词条缺失时回退到回退语言，再缺失时返回词条 key 本身。
func T(locale string, key string) string {
	current := current()
	if current == nil {
		return key
	}
	template, ok := current.lookup(locale, key)
	if !ok {
		return key
	}
	if strings.Contains(template, "%") {
		if placeholderMatched(template, 1) {
			return fmt.Sprintf(template, key)
		}
		return fmt.Sprintf(defaultTemplate, key)
	}
	return template
}

// Render 用给定参数渲染词条；占位符数量不匹配时回落到默认模板。
func Render(locale string, key string, args ...any) string {
	current := current()
	if current == nil {
		return key
	}
	template, ok := current.lookup(locale, key)
	if !ok {
		return key
	}
	if !placeholderMatched(template, len(args)) {
		return fmt.Sprintf(defaultTemplate, key)
	}
	return fmt.Sprintf(template, args...)
}

// Supported 返回受支持语言列表的副本。
func Supported() []string {
	current := current()
	if current == nil {
		return nil
	}
	result := make([]string, len(current.supported))
	copy(result, current.supported)
	return result
}

// Fallback 返回回退语言。
func Fallback() string {
	current := current()
	if current == nil {
		return DefaultLocale
	}
	return current.fallback
}

// IsSupported 判断语言是否在受支持列表中。
func IsSupported(locale string) bool {
	current := current()
	if current == nil {
		return false
	}
	normalized := Normalize(locale)
	for _, item := range current.supported {
		if item == normalized {
			return true
		}
	}
	return false
}

// Normalize 把语言标签规范化为「语言-区域」形式，例如 zh_CN 归一化为 zh-CN。
func Normalize(locale string) string {
	trimmed := strings.TrimSpace(locale)
	if trimmed == "" {
		return ""
	}
	replaced := strings.ReplaceAll(trimmed, "_", "-")
	parts := strings.Split(replaced, "-")
	if len(parts) == 1 {
		return strings.ToLower(parts[0])
	}
	languagePart := strings.ToLower(parts[0])
	regionPart := strings.ToUpper(parts[1])
	if len(parts) > 2 {
		return languagePart + "-" + regionPart
	}
	return languagePart + "-" + regionPart
}

// sanitizeAcceptLanguage 清理请求头中的非法字符，但保留完整的语言优先级列表。
func sanitizeAcceptLanguage(value string) string {
	var builder strings.Builder
	for _, char := range value {
		switch {
		case char >= 'a' && char <= 'z':
			builder.WriteRune(char)
		case char >= 'A' && char <= 'Z':
			builder.WriteRune(char)
		case char >= '0' && char <= '9':
			builder.WriteRune(char)
		case char == '-', char == '_', char == ',', char == ';', char == '.', char == '=', char == '*', char == ' ':
			builder.WriteRune(char)
		}
	}
	return strings.TrimSpace(builder.String())
}

// normalizeAll 规范化并去重语言列表，保持输入顺序。
func normalizeAll(locales []string) []string {
	seen := make(map[string]struct{}, len(locales))
	result := make([]string, 0, len(locales))
	for _, locale := range locales {
		normalized := Normalize(locale)
		if normalized == "" {
			continue
		}
		if _, ok := seen[normalized]; ok {
			continue
		}
		seen[normalized] = struct{}{}
		result = append(result, normalized)
	}
	return result
}

// current 返回当前生效的管理器。
func current() *Manager {
	mu.RLock()
	defer mu.RUnlock()
	return manager
}

// lookup 按语言、回退语言、默认语言的顺序查找词条模板。
func (m *Manager) lookup(locale string, key string) (string, bool) {
	candidates := []string{Normalize(locale), m.fallback, DefaultLocale}
	for _, candidate := range candidates {
		if candidate == "" {
			continue
		}
		catalog, ok := m.catalogs[candidate]
		if !ok {
			continue
		}
		if template, ok := catalog[key]; ok {
			return template, true
		}
	}
	return "", false
}

// placeholderMatched 校验模板占位符数量与实参数量是否一致。
func placeholderMatched(template string, count int) bool {
	return strings.Count(template, "%") == count
}

// loadCatalogs 读取嵌入目录中的全部词条文件。
func loadCatalogs(supported []string) (map[string]map[string]string, error) {
	catalogs := make(map[string]map[string]string, len(supported))
	for _, locale := range supported {
		catalog, err := loadCatalog(locale)
		if err != nil {
			return nil, err
		}
		catalogs[locale] = catalog
	}
	return catalogs, nil
}

// loadCatalog 读取并解析单个语言的词条文件。
func loadCatalog(locale string) (map[string]string, error) {
	file := path.Join(localeDir, locale+".yaml")
	raw, err := localeFS.ReadFile(file)
	if err != nil {
		return nil, fmt.Errorf("i18n: 无法读取词条文件 %s: %w", file, err)
	}
	parsed := make(map[string]string)
	if err := yaml.Unmarshal(raw, &parsed); err != nil {
		return nil, fmt.Errorf("i18n: 无法解析词条文件 %s: %w", file, err)
	}
	if len(parsed) == 0 {
		return nil, fmt.Errorf("i18n: 词条文件为空 %s", file)
	}
	return parsed, nil
}

// Keys 返回已加载的全部词条 key，用于测试与校验。
func Keys(locale string) []string {
	current := current()
	if current == nil {
		return nil
	}
	catalog := current.catalogs[Normalize(locale)]
	keys := make([]string, 0, len(catalog))
	for key := range catalog {
		keys = append(keys, key)
	}
	sort.Strings(keys)
	return keys
}
