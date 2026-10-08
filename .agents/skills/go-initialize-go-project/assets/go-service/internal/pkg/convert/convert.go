// Package convert 提供切片与映射的泛型转换工具。
package convert

// AnySlice 把输入切片按转换函数映射为另一种元素类型的切片。
func AnySlice[T any, R any](items []T, mapper func(T) R) []R {
	if items == nil {
		return nil
	}
	result := make([]R, 0, len(items))
	for _, item := range items {
		result = append(result, mapper(item))
	}
	return result
}

// Map 把输入映射按转换函数映射为另一种键值类型的映射。
func Map[K comparable, V any, NK comparable, NV any](
	items map[K]V,
	mapper func(K, V) (NK, NV),
) map[NK]NV {
	if items == nil {
		return nil
	}
	result := make(map[NK]NV, len(items))
	for key, value := range items {
		newKey, newValue := mapper(key, value)
		result[newKey] = newValue
	}
	return result
}
