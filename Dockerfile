FROM python:3.12-alpine
RUN apk add --no-cache git tzdata && cp /usr/share/zoneinfo/Asia/Shanghai /etc/localtime
ENV TZ=Asia/Shanghai
WORKDIR /app
COPY . .
RUN chmod +x start.sh
EXPOSE 8000
CMD ["sh", "start.sh"]
