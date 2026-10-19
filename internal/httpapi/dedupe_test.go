package httpapi

import (
	"context"
	"errors"
	"sync/atomic"
	"testing"
	"time"
)

func TestDoOnceValueCallerCancellationDoesNotCancelSharedCall(t *testing.T) {
	serverCtx, stopServer := context.WithCancel(context.Background())
	defer stopServer()
	server := &Server{ctx: serverCtx, dedupe: map[string]*inflight{}}
	started := make(chan struct{})
	release := make(chan struct{})
	var calls atomic.Int32
	fn := func(ctx context.Context) (int, error) {
		calls.Add(1)
		close(started)
		select {
		case <-release:
			return 42, nil
		case <-ctx.Done():
			return 0, ctx.Err()
		}
	}

	firstCtx, cancelFirst := context.WithCancel(context.Background())
	firstDone := make(chan error, 1)
	go func() {
		_, err := doOnceValue(firstCtx, server, "shared", fn)
		firstDone <- err
	}()
	<-started

	secondDone := make(chan struct {
		value int
		err   error
	}, 1)
	go func() {
		value, err := doOnceValue(context.Background(), server, "shared", fn)
		secondDone <- struct {
			value int
			err   error
		}{value: value, err: err}
	}()
	deadline := time.Now().Add(time.Second)
	for {
		server.dedupeMu.Lock()
		waiters := server.dedupe["shared"].waiters
		server.dedupeMu.Unlock()
		if waiters == 2 {
			break
		}
		if time.Now().After(deadline) {
			t.Fatal("second caller did not join shared call")
		}
		time.Sleep(time.Millisecond)
	}
	cancelFirst()
	if err := <-firstDone; !errors.Is(err, context.Canceled) {
		t.Fatalf("first caller error = %v", err)
	}
	close(release)

	select {
	case result := <-secondDone:
		if result.err != nil || result.value != 42 {
			t.Fatalf("second caller result = %d, %v", result.value, result.err)
		}
	case <-time.After(time.Second):
		t.Fatal("shared call did not finish")
	}
	if got := calls.Load(); got != 1 {
		t.Fatalf("shared function called %d times", got)
	}
}
