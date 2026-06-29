# 南理工课表 — 微信云托管 Dockerfile
# 基于官方模板框架，更换基础镜像以兼容 ddddocr（onnxruntime）
FROM python:3.10-slim

# 容器默认时区为UTC，如需使用上海时间请启用以下时区设置命令
# RUN apt-get update && apt-get install -y tzdata && cp /usr/share/zoneinfo/Asia/Shanghai /etc/localtime && echo Asia/Shanghai > /etc/timezone

# 安装系统依赖（ddddocr 的 onnxruntime 需要 libgomp）
RUN apt-get update && apt-get install -y \
    ca-certificates \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*

# 拷贝当前项目到/app目录下（.dockerignore中文件除外）
COPY . /app

# 设定当前的工作目录
WORKDIR /app

# 安装 Python 依赖，选用国内镜像源
RUN pip config set global.index-url http://mirrors.cloud.tencent.com/pypi/simple \
    && pip config set global.trusted-host mirrors.cloud.tencent.com \
    && pip install --upgrade pip \
    && pip install --user -r requirements.txt

# 暴露端口。必须与 container.config.json 中的 containerPort 一致
EXPOSE 80

# 执行启动命令（与模板 run.py 兼容）
CMD ["python3", "run.py", "0.0.0.0", "80"]
