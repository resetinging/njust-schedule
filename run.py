# 创建应用实例
import logging
import sys

# 全局日志配置: info 级别输出到 stdout(云托管采集 stdout 日志)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
    stream=sys.stdout,
)

from wxcloudrun import app

# 启动Flask Web服务
if __name__ == '__main__':
    host = sys.argv[1] if len(sys.argv) > 1 else "0.0.0.0"
    port = sys.argv[2] if len(sys.argv) > 2 else 5000
    app.run(host=host, port=port)
