FROM python:3.13-slim
RUN apt-get update && apt-get install -y --no-install-recommends nodejs npm git \
    && npm install -g @openai/codex \
    && rm -rf /var/lib/apt/lists/* /root/.npm
WORKDIR /opt/webtree
COPY pyproject.toml ./
COPY webtree ./webtree
RUN pip install --no-cache-dir .
ENTRYPOINT ["webtree"]
