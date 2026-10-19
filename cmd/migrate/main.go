package main

import (
	"context"
	"log/slog"
	"os"
	"time"

	"github.com/resetinging/njust-schedule/internal/config"
	"github.com/resetinging/njust-schedule/internal/database"
	"github.com/resetinging/njust-schedule/internal/logging"
	"github.com/resetinging/njust-schedule/internal/migrate"
)

func main() {
	logger := logging.New(os.Stdout, config.LogLevel(os.Getenv("LOG_LEVEL")))
	os.Exit(run(logger))
}

func run(logger *slog.Logger) int {
	cfg, err := config.Load()
	if err != nil {
		logger.Error("配置无效", "error", err)
		return 1
	}
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Minute)
	defer cancel()
	db, err := database.OpenForMigration(ctx, cfg)
	if err != nil {
		logger.Error("数据库连接失败", "error", err)
		return 1
	}
	applied, err := migrate.Run(ctx, db, logger)
	if err != nil {
		logger.Error("数据库迁移失败", "error", err)
		if closeErr := db.Close(); closeErr != nil {
			logger.Error("关闭数据库失败", "error", closeErr)
		}
		return 1
	}
	if len(applied) == 0 {
		logger.Info("迁移完成", "result", "无待执行迁移")
	}
	if err = db.Close(); err != nil {
		logger.Error("关闭数据库失败", "error", err)
		return 1
	}
	return 0
}
