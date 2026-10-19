# syntax=docker/dockerfile:1
FROM golang:1.26.9-bookworm AS build

ARG DEBIAN_FRONTEND=noninteractive
WORKDIR /src
RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential ca-certificates git \
    && rm -rf /var/lib/apt/lists/*

COPY go.mod go.sum ./
RUN go mod download
COPY cmd ./cmd
COPY internal ./internal
RUN CGO_ENABLED=1 GOOS=linux go build -trimpath -ldflags="-s -w" -o /out/server ./cmd/server \
    && CGO_ENABLED=1 GOOS=linux go build -trimpath -ldflags="-s -w" -o /out/migrate ./cmd/migrate

FROM debian:bookworm-slim AS runtime-assets

ARG DEBIAN_FRONTEND=noninteractive
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl unzip \
    && rm -rf /var/lib/apt/lists/*
RUN curl -fsSL --retry 3 --retry-delay 2 \
      -o /tmp/ddddocr.whl \
      https://files.pythonhosted.org/packages/0e/48/cbaed3981b8d8d51141b9b4779b811f4728e65d952a1e3e2e5e929539183/ddddocr-1.6.1-py3-none-any.whl \
    && echo "c7c70f4ae2d0335440ae8b272eea48c9f6888ecef46785fe2311f0c97a133935  /tmp/ddddocr.whl" \
      | sha256sum -c -
RUN curl -fsSL --retry 3 --retry-delay 2 \
      -o /tmp/onnxruntime.whl \
      https://files.pythonhosted.org/packages/e9/80/113381ba832d5e777accedc6cb41d10f9eca82321ae31ebb6bcede530cea/onnxruntime-1.23.2-cp311-cp311-manylinux_2_27_x86_64.manylinux_2_28_x86_64.whl \
    && echo "da44b99206e77734c5819aa2142c69e64f3b46edc3bd314f6a45a932defc0b3e  /tmp/onnxruntime.whl" \
      | sha256sum -c -
RUN mkdir -p /assets \
    && unzip -j /tmp/ddddocr.whl 'ddddocr/common_old.onnx' -d /assets \
    && mv /assets/common_old.onnx /assets/common.onnx \
    && echo "b8f2ad9cbc1f2e3922a6cb9459e30824e7e2467f3fb4fd61420640e34ea0bf68  /assets/common.onnx" \
      | sha256sum -c - \
    && unzip -j /tmp/onnxruntime.whl \
      'onnxruntime/capi/libonnxruntime.so.1.23.2' \
      'onnxruntime/capi/libonnxruntime_providers_shared.so' \
      -d /assets \
    && cp /assets/libonnxruntime.so.1.23.2 /assets/libonnxruntime.so

FROM debian:bookworm-slim

ARG DEBIAN_FRONTEND=noninteractive
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates libcap2-bin libgomp1 libstdc++6 tzdata wget \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --system app \
    && useradd --system --gid app --home-dir /app --shell /usr/sbin/nologin app
ENV TZ=Asia/Shanghai \
    STATIC_DIR=/app/wxcloudrun/static \
    CAPTCHA_OCR_MODEL_PATH=/app/common.onnx \
    ONNXRUNTIME_SHARED_LIBRARY_PATH=/app/libonnxruntime.so
WORKDIR /app

COPY --from=build /out/server /app/server
COPY --from=build /out/migrate /app/migrate
COPY --from=runtime-assets /assets/common.onnx /app/common.onnx
COPY --from=runtime-assets /assets/libonnxruntime.so /app/libonnxruntime.so
COPY --from=runtime-assets /assets/libonnxruntime.so.1.23.2 /app/libonnxruntime.so.1.23.2
COPY --from=runtime-assets /assets/libonnxruntime_providers_shared.so /app/libonnxruntime_providers_shared.so
COPY --chown=app:app internal/captcha/*.txt /app/licenses/
COPY --chown=app:app wxcloudrun/static /app/wxcloudrun/static
COPY --chown=app:app wxcloudrun/templates/admin.html /app/wxcloudrun/templates/admin.html

# 云托管固定使用 80 端口；保留非 root 运行，仅授予绑定低端口能力。
RUN setcap 'cap_net_bind_service=+ep' /app/server

USER app
EXPOSE 80
HEALTHCHECK --interval=30s --timeout=3s --start-period=15s --retries=3 \
    CMD wget -q -O /dev/null http://127.0.0.1/healthz || exit 1

# 先监听健康端口，再在进程内执行带 MySQL 命名锁的迁移。
# 迁移完成前业务接口返回 503；迁移失败时进程退出，云托管保留旧版本。
CMD ["/app/server"]
