# 南理工课表 — 微信云托管 Dockerfile
# 基于官方模板框架，更换基础镜像以兼容 ddddocr（onnxruntime）
FROM python:3.10-slim

# 容器默认时区为UTC，启用上海时区（学期计算/日志时间依赖北京时间）
# 一并安装系统依赖（ddddocr 的 onnxruntime 需要 libgomp）
RUN apt-get update && apt-get install -y \
        tzdata ca-certificates libgomp1 \
    && ln -sf /usr/share/zoneinfo/Asia/Shanghai /etc/localtime \
    && echo Asia/Shanghai > /etc/timezone \
    && rm -rf /var/lib/apt/lists/*

# 设定工作目录
WORKDIR /app

# ★ 先拷贝并安装依赖（Docker 层缓存: 代码改动不会触发依赖重装, 构建大幅加速）
COPY requirements.txt /app/requirements.txt
RUN pip config set global.index-url http://mirrors.cloud.tencent.com/pypi/simple \
    && pip config set global.trusted-host mirrors.cloud.tencent.com \
    && pip install --upgrade pip \
    && pip install --user -r requirements.txt

# 再拷贝项目代码（.dockerignore 中文件除外）
COPY . /app

# 暴露端口。必须与 container.config.json 中的 containerPort 一致
EXPOSE 80

# 生产启动: gunicorn 单 worker + 多线程（会话在进程内存, 必须单进程;
# 8 线程足够承载教务 IO 等待期间的并发）
CMD ["python3", "-m", "gunicorn", "run:app", \
     "--workers", "1", "--threads", "8", \
     "--timeout", "60", "--bind", "0.0.0.0:80"]
