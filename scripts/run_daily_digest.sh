#!/bin/bash
# 每日科技简报定时任务脚本
# 每天早上7:30自动采集最新文章并通过 QQ 推送

cd ~/.agents/skills/puppeteer-automation
node fetch_daily_digest.js > /tmp/digest.log 2>&1

if [ $? -eq 0 ]; then
    CONTENT=$(cat /root/.openclaw/workspace/temp/daily_digest.txt)
    
    # 通过 openclaw 发送消息（这需要通过 openclaw 的消息工具）
    # 临时保存内容供后续发送
    echo "$CONTENT" > /tmp/digest_to_send.txt
    
    echo "✅ 采集完成，等待发送..."
else
    echo "❌ 采集失败"
    exit 1
fi
