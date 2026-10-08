package verifycode_test

import (
	"regexp"
	"testing"

	"project_id/internal/pkg/verifycode"
)

// TestGenerateRespectsLength 生成结果必须等于请求的位数，非法位数回落默认值。
func TestGenerateRespectsLength(t *testing.T) {
	cases := []struct {
		length int
		want   int
	}{
		{length: 0, want: verifycode.DefaultLength}, // 0 走默认值
		{length: -1, want: verifycode.DefaultLength},
		{length: 4, want: 4},
		{length: 6, want: 6},
		{length: 10, want: 10},
	}

	for _, tc := range cases {
		code, err := verifycode.Generate(tc.length)
		if err != nil {
			t.Fatalf("Generate(%d) 报错: %v", tc.length, err)
		}
		if len(code) != tc.want {
			t.Errorf("Generate(%d) = %q，长度应为 %d", tc.length, code, tc.want)
		}
		if !regexp.MustCompile(`^\d+$`).MatchString(code) {
			t.Errorf("Generate(%d) = %q，应只含数字", tc.length, code)
		}
	}
}

// TestGenerateRejectsTooLong 超过位数上限必须报错，不静默截断。
func TestGenerateRejectsTooLong(t *testing.T) {
	if _, err := verifycode.Generate(11); err == nil {
		t.Fatal("超过位数上限应报错")
	}
}

// TestGenerateKeepsLeadingZeros 短数字必须补齐前导零，否则实际位数会小于配置值。
//
// 随机生成 200 次里必然会命中「数值小于 10^(n-1)」的情况（约 10% 概率），
// 靠这个覆盖到前导零分支。
func TestGenerateKeepsLeadingZeros(t *testing.T) {
	for i := 0; i < 200; i++ {
		code, err := verifycode.Generate(6)
		if err != nil {
			t.Fatalf("Generate 报错: %v", err)
		}
		if len(code) != 6 {
			t.Fatalf("第 %d 次生成的 %q 长度不是 6，前导零没有补齐", i, code)
		}
	}
}

// TestGenerateIsNotTriviallyRepeating 连续生成不应出现重复。
//
// 这不是严格的随机性检验，只是拦住「误用 math/rand 且没播种」这类低级错误 ——
// 那种情况下前几个值会完全一样。
func TestGenerateIsNotTriviallyRepeating(t *testing.T) {
	seen := make(map[string]bool, 100)
	for i := 0; i < 100; i++ {
		code, err := verifycode.Generate(6)
		if err != nil {
			t.Fatalf("Generate 报错: %v", err)
		}
		if seen[code] {
			t.Fatalf("100 次生成里出现重复的 %q，随机源可疑", code)
		}
		seen[code] = true
	}
}

// TestHashAndMatch 哈希不得等于明文，正确码通过、错误码拒绝。
func TestHashAndMatch(t *testing.T) {
	const target = "demo@example.com"

	hash := verifycode.Hash("123456", target)

	if hash == "123456" {
		t.Fatal("哈希结果不应等于明文")
	}
	if !verifycode.Match(hash, "123456", target) {
		t.Fatal("正确验证码应匹配通过")
	}
	if verifycode.Match(hash, "123457", target) {
		t.Fatal("错误验证码不应匹配通过")
	}
}

// TestHashIsBoundToTarget 同一个验证码发给不同目标时必须产生不同哈希。
//
// 否则拖库的人可以拿 A 的哈希去撞 B，等于把目标维度这道隔离抹掉。
func TestHashIsBoundToTarget(t *testing.T) {
	if verifycode.Hash("123456", "a@example.com") == verifycode.Hash("123456", "b@example.com") {
		t.Fatal("相同验证码在不同目标下的哈希不应相同")
	}
}

// TestMatchToleratesWrongLengthHash 哈希长度异常时只能返回 false，不能 panic。
func TestMatchToleratesWrongLengthHash(t *testing.T) {
	if verifycode.Match("", "123456", "demo@example.com") {
		t.Fatal("空哈希不应匹配成功")
	}
	if verifycode.Match("deadbeef", "123456", "demo@example.com") {
		t.Fatal("长度不符的哈希不应匹配成功")
	}
}
