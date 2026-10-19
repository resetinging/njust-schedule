package app

import (
	"context"
	"database/sql"
	"errors"
	"log/slog"

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
	if err = migrate.Verify(context.Background(), db); err != nil {
		return nil, errors.Join(err, db.Close())
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

func (a *App) Shutdown(ctx context.Context) error {
	return a.server.Shutdown(ctx)
}

func (a *App) Close() error { return a.db.Close() }
