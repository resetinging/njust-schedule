package session

import (
	"bytes"
	"context"
	"testing"
	"time"

	"github.com/alicebob/miniredis/v2"
	"github.com/resetinging/njust-schedule/internal/security"
)

func newBenchmarkManager(b *testing.B) (*Manager, string) {
	b.Helper()
	redisServer := miniredis.RunT(b)
	crypto, err := security.New(bytes.Repeat([]byte{1}, 32))
	if err != nil {
		b.Fatal(err)
	}
	manager, err := NewManager(time.Hour, 1000, "redis://"+redisServer.Addr()+"/0", crypto)
	if err != nil {
		b.Fatal(err)
	}
	b.Cleanup(func() { _ = manager.Close() })
	token, err := manager.Add(context.Background(), &Session{
		StudentID:   "924101960000",
		StudentName: "基准用户",
	})
	if err != nil {
		b.Fatal(err)
	}
	return manager, token
}

func BenchmarkManagerGetLocal(b *testing.B) {
	manager, token := newBenchmarkManager(b)
	ctx := context.Background()
	b.ReportAllocs()
	b.ResetTimer()
	for i := 0; i < b.N; i++ {
		if _, ok := manager.Get(ctx, token); !ok {
			b.Fatal("local session lookup failed")
		}
	}
}

func BenchmarkManagerGetLocalParallel(b *testing.B) {
	manager, token := newBenchmarkManager(b)
	ctx := context.Background()
	b.ReportAllocs()
	b.ResetTimer()
	b.RunParallel(func(pb *testing.PB) {
		for pb.Next() {
			if _, ok := manager.Get(ctx, token); !ok {
				b.Fatal("local session lookup failed")
			}
		}
	})
}
