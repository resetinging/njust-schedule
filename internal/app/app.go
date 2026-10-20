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
	return &App{server: server, db: db}, nil
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

func (a *App) Shutdown(ctx context.Context) error {
	return a.server.Shutdown(ctx)
}

func (a *App) Close() error { return a.db.Close() }
