# 创建应用实例
import logging
import os
import sys

# 全局日志配置: info 级别输出到 stdout(云托管采集 stdout 日志);
# 调试时可设环境变量 LOG_LEVEL=DEBUG 查看教务爬虫的详细日志
logging.basicConfig(
    level=getattr(logging, os.environ.get("LOG_LEVEL", "INFO").upper(), logging.INFO),
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    stream=sys.stdout,
)

# 抑制 werkzeug 自带访问日志(带 ANSI 颜色码且与 [req] 重复, 云托管控制台噪音);
# 请求日志统一由 views.py 的 [req] 输出(含 rid/状态/耗时/用户)
logging.getLogger("werkzeug").setLevel(logging.WARNING)

from wxcloudrun import app

# 空教室定时预热: 由后端在每天各大节上课时刻刷新缓存(前端只读接口结果)。
# 放在服务入口启动: gunicorn run:app / python run.py 都会执行; 测试只导入
# wxcloudrun 包, 不会拉起该线程。设 FREE_CLASSROOM_PREWARM=0 可关闭。
from wxcloudrun.api.freeclass import _start_freeclass_prewarm  # noqa: E402
_start_freeclass_prewarm()

# 启动摘要日志: 确认部署版本与关键配置(云托管控制台日志可见)
logger = logging.getLogger("startup")
logger.info("========================================")
logger.info("NJUST 课表后端启动")
logger.info("LOG_LEVEL=%s", os.environ.get("LOG_LEVEL", "INFO"))
logger.info("JW_MAX_CONCURRENT=%s SESSION_TTL=%ss MAX_SESSIONS=%s",
            os.environ.get("JW_MAX_CONCURRENT", "4"),
            os.environ.get("SESSION_TTL", "43200"),
            os.environ.get("MAX_SESSIONS", "200"))
logger.info("SLOW_MS=%s(慢请求告警阈值)", os.environ.get("SLOW_MS", "2000"))
logger.info("DB=%s", "sqlite(local)" if os.environ.get("SQLALCHEMY_DATABASE_URI", "").startswith("sqlite") else "mysql(cloud)")
logger.info("========================================")

# 启动Flask Web服务
if __name__ == '__main__':
    host = sys.argv[1] if len(sys.argv) > 1 else "0.0.0.0"
    port = sys.argv[2] if len(sys.argv) > 2 else 5000
    app.run(host=host, port=port)
