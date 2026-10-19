package httpapi

import (
	"context"
	"testing"
	"time"
)

func TestWithSessionJWCAcquiresSessionLockBeforeGlobalSlot(t *testing.T) {
	server := &Server{jwcSlots: make(chan struct{}, 1)}
	server.jwcSlots <- struct{}{}
	locked := make(chan struct{})
	unlocked := make(chan struct{})
	sess := observedSessionLock{locked: locked, unlocked: unlocked}

	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	done := make(chan error, 1)
	go func() {
		done <- server.withSessionJWC(ctx, sess, func() error { return nil })
	}()

	select {
	case <-locked:
	case <-time.After(time.Second):
		t.Fatal("请求没有先获取用户会话锁")
	}
	select {
	case <-unlocked:
		t.Fatal("等待全局教务并发槽时不应释放用户会话锁")
	default:
	}

	<-server.jwcSlots
	select {
	case err := <-done:
		if err != nil {
			t.Fatalf("withSessionJWC returned error: %v", err)
		}
	case <-time.After(time.Second):
		t.Fatal("释放全局教务并发槽后请求未完成")
	}

	select {
	case <-unlocked:
	case <-time.After(time.Second):
		t.Fatal("请求完成后用户会话锁未释放")
	}
}

type observedSessionLock struct {
	locked   chan struct{}
	unlocked chan struct{}
}

func (lock observedSessionLock) Lock() func() {
	close(lock.locked)
	return func() { close(lock.unlocked) }
}
