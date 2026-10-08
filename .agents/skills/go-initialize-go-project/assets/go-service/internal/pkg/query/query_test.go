package query

import "testing"

// TestNormalizeAppliesBounds 验证越界分页参数被收敛到合法范围。
func TestNormalizeAppliesBounds(t *testing.T) {
	page := &Page{Current: 0, Size: 0}
	page.Normalize()
	if page.Current != DefaultCurrent {
		t.Fatalf("期望默认页码 %d，实际 %d", DefaultCurrent, page.Current)
	}
	if page.Size != DefaultSize {
		t.Fatalf("期望默认每页条数 %d，实际 %d", DefaultSize, page.Size)
	}

	oversized := &Page{Current: MaxCurrent + 1, Size: MaxSize + 1}
	oversized.Normalize()
	if oversized.Current != MaxCurrent {
		t.Fatalf("期望页码上界 %d，实际 %d", MaxCurrent, oversized.Current)
	}
	if oversized.Size != MaxSize {
		t.Fatalf("期望每页条数上界 %d，实际 %d", MaxSize, oversized.Size)
	}
}

// TestOffsetComputesPageStart 验证偏移量按页码与每页条数计算。
func TestOffsetComputesPageStart(t *testing.T) {
	page := &Page{Current: 3, Size: 20}
	if got := page.Offset(); got != 40 {
		t.Fatalf("期望偏移量 40，实际 %d", got)
	}
}

// TestValidateOrderByRejectsUnsafeColumn 验证排序列名必须通过安全校验。
func TestValidateOrderByRejectsUnsafeColumn(t *testing.T) {
	allowed := []string{"id", "created_time"}

	safe := &Page{OrderBy: "created_time"}
	if err := safe.ValidateOrderBy(allowed); err != nil {
		t.Fatalf("合法排序列名不应报错：%v", err)
	}

	injected := &Page{OrderBy: "id; DROP TABLE users"}
	if err := injected.ValidateOrderBy(allowed); err == nil {
		t.Fatal("含注入片段的排序列名必须被拒绝")
	}

	unknown := &Page{OrderBy: "not_a_column"}
	if err := unknown.ValidateOrderBy(allowed); err == nil {
		t.Fatal("不在允许集合内的排序列名必须被拒绝")
	}
}

// TestOrderClauseFallsBackToDefault 验证未指定排序列时使用默认列。
func TestOrderClauseFallsBackToDefault(t *testing.T) {
	page := &Page{}
	if got := page.OrderClause("id"); got != "id ASC" {
		t.Fatalf("期望默认排序列 id ASC，实际 %s", got)
	}
	descending := &Page{OrderBy: "created_time", Desc: true}
	if got := descending.OrderClause("id"); got != "created_time DESC" {
		t.Fatalf("期望降序子句 created_time DESC，实际 %s", got)
	}
}

// TestOrderClauseRejectsUnsafeDefault 验证不安全的默认列不会进入排序子句。
func TestOrderClauseRejectsUnsafeDefault(t *testing.T) {
	page := &Page{}
	if got := page.OrderClause("id; DROP TABLE users"); got != "" {
		t.Fatalf("不安全的默认排序列必须返回空子句，实际 %s", got)
	}
}
