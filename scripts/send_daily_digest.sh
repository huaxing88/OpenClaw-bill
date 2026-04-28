#!/bin/bash
# 每日科技简报定时发送脚本

cd ~/.agents/skills/puppeteer-automation
node fetch_daily_digest.js > /tmp/digest_output.txt 2>&1

if [ $? -eq 0 ]; then
    # 读取消息内容
    MESSAGE=$(cat /root/.openclaw/workspace/temp/daily_digest.txt)

    # 保存到文件供 openclaw 读取
    echo "$MESSAGE" > /root/.openclaw/workspace/temp/to_send.txt
else
    echo "采集失败" > /root/.openclaw/workspace/temp/to_send.txt
fi
