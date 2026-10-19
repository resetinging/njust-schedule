package app

import (
	"context"
	"database/sql"
	"errors"
	"fmt"
	"log/slog"
	"net"
	"time"

	"github.com/resetinging/njust-schedule/internal/config"
	"github.com/resetinging/njust-schedule/internal/database"
	"github.com/resetinging/njust-schedule/internal/httpapi"
	"github.com/resetinging/njust-schedule/internal/migrate"
)

type App struct {
	server *httpapi.Server
	db     *sql.DB
	cfg    config.Config
}

func New(cfg config.Config, logger *slog.Logger) (*App, error) {
	db, err := database.Open(context.Background(), cfg)
	if err != nil {
		return nil, err
	}
	server, err := httpapi.New(cfg, db, logger)
	if err != nil {
		return nil, errors.Join(err, db.Close())
	}
	return &App{server: server, db: db, cfg: cfg}, nil
}

func (a *App) ListenAndServe() error {
	return a.server.ListenAndServe()
}

func (a *App) Listen() (net.Listener, error) {
	return a.server.Listen()
}

func (a *App) Serve(listener net.Listener) error {
	return a.server.Serve(listener)
}

func (a *App) Initialize(ctx context.Context, logger *slog.Logger) error {
	if a.cfg.MigrationsAuto {
		return a.Migrate(ctx, logger)
	}
	verifyCtx, cancel := context.WithTimeout(ctx, 30*time.Second)
	defer cancel()
	a.server.SetMigrationStage("verify_schema")
	if err := migrate.Verify(verifyCtx, a.db); err != nil {
		return fmt.Errorf("数据库 Schema 校验失败: %w", err)
	}
	logger.Info("数据库 Schema 校验完成", "version", migrate.Version)
	a.server.SetMigrationStage("complete")
	a.server.MarkReady()
	a.server.StartJobs()
	return nil
}

func (a *App) Migrate(ctx context.Context, logger *slog.Logger) error {
	migrationCtx, cancel := context.WithTimeout(ctx, 5*time.Minute)
	defer cancel()
	migrationDB, err := database.OpenForMigration(migrationCtx, a.cfg)
	if err != nil {
		return err
	}
	defer func() {
		if closeErr := migrationDB.Close(); closeErr != nil {
			logger.Warn("关闭迁移数据库连接失败", "error", closeErr)
		}
	}()
	applied, err := migrate.RunWithProgress(
		migrationCtx,
		migrationDB,
		logger,
		a.server.SetMigrationStage,
	)
	if err != nil {
		return err
	}
	if len(applied) == 0 {
		logger.Info("数据库迁移校验完成", "version", migrate.Version)
	}
	a.server.SetMigrationStage("complete")
	a.server.MarkReady()
	a.server.StartJobs()
	return nil
}

func (a *App) Shutdown(ctx context.Context) error {
	return a.server.Shutdown(ctx)
}

func (a *App) Close() error { return a.db.Close() }
