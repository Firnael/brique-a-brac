FROM python:3.13-slim
WORKDIR /app
COPY server.py ./
COPY static ./static
ENV DATA_DIR=/data PORT=8642
VOLUME /data
EXPOSE 8642
CMD ["python", "server.py"]
