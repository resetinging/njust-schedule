//go:build !cgo

package captcha

import (
	"context"
	"fmt"
)

type Solver struct{}

func NewSolver(_, _ string) *Solver { return &Solver{} }

func (s *Solver) Solve(context.Context, []byte) (string, error) {
	return "", fmt.Errorf("%w: 当前构建未启用 CGO", ErrUnavailable)
}

func (s *Solver) Close() error { return nil }
