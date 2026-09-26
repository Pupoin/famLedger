FROM python:3.12-slim

WORKDIR /app

# 仅安装核心依赖：
# - fastapi/uvicorn: 用于提供网页服务与数据接口
# - pandas: 用于复用原项目的复杂账单处理逻辑
# - psycopg[binary]: 用于连接数据库
RUN pip config set global.index-url https://pypi.tuna.tsinghua.edu.cn/simple && \
    pip install --no-cache-dir fastapi uvicorn pandas psycopg[binary] msal cryptography python-dotenv

# 复制应用代码
COPY main.py .
COPY logic.py .
COPY static/ ./static/

EXPOSE 8502

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8502"]
