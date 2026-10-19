package database

import (
	"context"
	"database/sql"
	"fmt"
	"net"
	"net/url"
	"time"

	_ "github.com/go-sql-driver/mysql"
	"github.com/resetinging/njust-schedule/internal/config"
)

func Open(ctx context.Context, cfg config.Config) (*sql.DB, error) {
	return open(ctx, cfg, 20*time.Second)
}

func OpenForMigration(ctx context.Context, cfg config.Config) (*sql.DB, error) {
	return open(ctx, cfg, 5*time.Minute)
}

func open(ctx context.Context, cfg config.Config, ioTimeout time.Duration) (*sql.DB, error) {
	if _, _, err := net.SplitHostPort(cfg.MySQLAddress); err != nil {
		return nil, fmt.Errorf("MYSQL_ADDRESS 必须为 host:port: %w", err)
	}
	params := url.Values{
		"charset":      {"utf8mb4"},
		"collation":    {"utf8mb4_unicode_ci"},
		"loc":          {"Asia/Shanghai"},
		"parseTime":    {"true"},
		"timeout":      {"5s"},
		"readTimeout":  {ioTimeout.String()},
		"writeTimeout": {ioTimeout.String()},
	}
	dsn := fmt.Sprintf("%s:%s@tcp(%s)/%s?%s",
		cfg.MySQLUsername, cfg.MySQLPassword, cfg.MySQLAddress,
		cfg.MySQLDatabase, params.Encode())
	db, err := sql.Open("mysql", dsn)
	if err != nil {
		return nil, fmt.Errorf("打开 MySQL 失败: %w", err)
	}
	db.SetMaxOpenConns(20)
	db.SetMaxIdleConns(10)
	db.SetConnMaxLifetime(time.Hour)
	db.SetConnMaxIdleTime(15 * time.Minute)

	pingCtx, cancel := context.WithTimeout(ctx, 5*time.Second)
	defer cancel()
	if err = db.PingContext(pingCtx); err != nil {
		_ = db.Close()
		return nil, fmt.Errorf("连接 MySQL 失败: %w", err)
	}
	return db, nil
}
