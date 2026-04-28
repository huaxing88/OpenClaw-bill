#!/bin/bash
set -e

echo "🍵 img2ledger 本地部署脚本"

# 颜色输出
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

# 1. 部署后端
echo -e "${YELLOW}📦 部署后端...${NC}"
cd /root/.openclaw/workspace/project/img2ledger_poc_all/img2ledger_poc_service

# 创建虚拟环境
if [ ! -d "venv" ]; then
    python3 -m venv venv
    echo -e "${GREEN}✓ 虚拟环境已创建${NC}"
fi

# 激活虚拟环境并安装依赖
source venv/bin/activate || { echo "❌ 虚拟环境激活失败，重新创建..."; rm -rf venv && python3 -m venv venv && source venv/bin/activate; }
pip install -U pip -q
pip install -r requirements.txt -q
echo -e "${GREEN}✓ Python 依赖已安装${NC}"

# 创建 systemd 服务
cat > /etc/systemd/system/img2ledger-backend.service << 'EOF'
[Unit]
Description=Img2ledger Backend Service
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/root/.openclaw/workspace/project/img2ledger_poc_all/img2ledger_poc_service
Environment="PYTHONPATH=/root/.openclaw/workspace/project/img2ledger_poc_all/img2ledger_poc_service/src"
Environment="DISABLE_MODEL_SOURCE_CHECK=True"
ExecStart=/root/.openclaw/workspace/project/img2ledger_poc_all/img2ledger_poc_service/venv/bin/uvicorn ledger_poc_web.main:app --host 0.0.0.0 --port 8000
Restart=always

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable img2ledger-backend
systemctl restart img2ledger-backend
echo -e "${GREEN}✓ 后端服务已启动 (http://localhost:8000)${NC}"

# 2. 部署前端
echo -e "${YELLOW}🎨 部署前端...${NC}"
cd /root/.openclaw/workspace/project/img2ledger_poc_all/img2ledger-web

# 安装 Node.js 依赖（如果还没有）
if [ ! -d "node_modules" ]; then
    npm install --silent
    echo -e "${GREEN}✓ Node.js 依赖已安装${NC}"
fi

# 构建前端
npm run build
echo -e "${GREEN}✓ 前端已构建${NC}"

# 安装 nginx
if ! command -v nginx &> /dev/null; then
    apt-get update -qq
    apt-get install -y nginx -qq
    echo -e "${GREEN}✓ nginx 已安装${NC}"
fi

# 配置 nginx
cat > /etc/nginx/sites-available/img2ledger << 'EOF'
server {
    listen 80;
    server_name _;

    # 前端静态文件
    root /root/.openclaw/workspace/project/img2ledger_poc_all/img2ledger-web/dist;
    index index.html;

    location / {
        try_files $uri $uri/ /index.html;
        add_header Cache-Control "no-cache";
    }

    # 反向代理到后端 API
    location /api/ {
        proxy_pass http://127.0.0.1:8000/;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        # 上传文件大小限制
        client_max_body_size 50M;
    }

    # 下载文件代理
    location /downloads/ {
        proxy_pass http://127.0.0.1:8000/downloads/;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
EOF

ln -sf /etc/nginx/sites-available/img2ledger /etc/nginx/sites-enabled/
rm -f /etc/nginx/sites-enabled/default

# 测试并重启 nginx
nginx -t && systemctl reload nginx
echo -e "${GREEN}✓ nginx 已配置${NC}"

# 3. 显示访问信息
echo ""
echo -e "${GREEN}🎉 部署完成！${NC}"
echo ""
echo "访问地址："
echo "  • 前端: http://$(hostname -I | awk '{print $1}')"
echo "  • 后端: http://$(hostname -I | awk '{print $1}'):8000"
echo "  • 健康检查: http://$(hostname -I | awk '{print $1}'):8000/health"
echo ""
echo "管理命令："
echo "  • 查看后端日志: journalctl -u img2ledger-backend -f"
echo "  • 重启后端: systemctl restart img2ledger-backend"
echo "  • 查看 nginx 日志: tail -f /var/log/nginx/access.log"
echo ""
echo -e "${YELLOW}⚠️ 注意：首次使用需要下载 OCR 模型，可能会稍慢${NC}"
