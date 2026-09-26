FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app

WORKDIR /app

# 复制依赖文件并安装
COPY requirements.txt .
RUN pip config set global.index-url https://pypi.tuna.tsinghua.edu.cn/simple && \
    pip install --no-cache-dir -r requirements.txt

# 将整个 backend 目录复制到容器内的 backend/ 目录下
# 这样可以保持 "from backend.xxx import yyy" 的导入路径一致性
COPY . ./backend/

# 暴露端口（如果是旧的 Streamlit 用的）
EXPOSE 8501

# 启动调度器
CMD ["python", "backend/run.py"]
