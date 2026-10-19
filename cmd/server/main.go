package main

import (
	"context"
	"errors"
	"fmt"
	"log/slog"
	"net/http"
	"os"
	"os/signal"
	"syscall"
	"time"

	"github.com/resetinging/njust-schedule/internal/app"
	"github.com/resetinging/njust-schedule/internal/config"
)

func main() {
	logger := slog.New(slog.NewJSONHandler(os.Stdout, &slog.HandlerOptions{
		Level: config.LogLevel(os.Getenv("LOG_LEVEL")),
	}))
	os.Exit(run(logger))
}

func run(logger *slog.Logger) int {
	cfg, err := config.Load()
	if err != nil {
		logger.Error("配置无效", "error", err)
		return 1
	}

	application, err := app.New(cfg, logger)
	if err != nil {
		logger.Error("应用初始化失败", "error", err)
		return 1
	}

	listener, err := application.Listen()
	if err != nil {
		logger.Error("监听端口失败", "address", cfg.Address, "error", err)
		return 1
	}
	logger.Info("健康端口已监听", "address", cfg.Address, "runtime", "webgo")

	ctx, stop := signal.NotifyContext(context.Background(), syscall.SIGINT, syscall.SIGTERM)
	defer stop()

	errCh := make(chan error, 1)
	go func() {
		logger.Info("服务启动", "address", cfg.Address, "runtime", "webgo")
		errCh <- application.Serve(listener)
	}()

	migrationErrCh := make(chan error, 1)
	go func() {
		if err := application.Initialize(ctx, logger); err != nil {
			migrationErrCh <- fmt.Errorf("数据库初始化失败: %w", err)
			return
		}
		logger.Info("服务就绪", "migrations_auto", cfg.MigrationsAuto)
	}()

	exitCode := 0
	select {
	case <-ctx.Done():
	case err = <-errCh:
		if err != nil && !errors.Is(err, http.ErrServerClosed) {
			logger.Error("服务异常退出", "error", err)
			exitCode = 1
		}
	case err = <-migrationErrCh:
		logger.Error("服务初始化失败", "error", err)
		exitCode = 1
	}

	shutdownCtx, cancel := context.WithTimeout(context.Background(), 15*time.Second)
	defer cancel()
	if err := application.Shutdown(shutdownCtx); err != nil {
		logger.Error("优雅停机失败", "error", err)
		exitCode = 1
	}
	if err := application.Close(); err != nil {
		logger.Error("关闭数据库失败", "error", err)
		exitCode = 1
	}
	return exitCode
}
