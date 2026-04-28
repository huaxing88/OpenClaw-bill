#!/bin/bash

# 每日科技简报采集脚本
# 作者：小茶茶
# 功能：采集 diget.bytenote.net 最新文章并通过 QQ 推送

WORKSPACE="/root/.openclaw/workspace"
LOG_FILE="$WORKSPACE/logs/daily_digest.log"
TEMP_SCRIPT="$WORKSPACE/temp/fetch_article.js"

# 创建必要的目录
mkdir -p "$WORKSPACE/logs"
mkdir -p "$WORKSPACE/temp"

# 日志函数
log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" | tee -a "$LOG_FILE"
}

log "开始采集每日科技简报..."

# 创建 Node.js 脚本
cat > "$TEMP_SCRIPT" << 'EOF'
const puppeteer = require('puppeteer');

async function fetchLatestDigest() {
    const browser = await puppeteer.launch({
        headless: 'new',
        args: ['--no-sandbox', '--disable-setuid-sandbox']
    });

    try {
        const page = await browser.newPage();
        await page.setUserAgent('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36');

        // 访问归档页面获取最新文章链接
        await page.goto('https://diget.bytenote.net/archive/', {
            waitUntil: 'networkidle2',
            timeout: 30000
        });

        await new Promise(resolve => setTimeout(resolve, 2000));

        const latestUrl = await page.evaluate(() => {
            const firstArticle = document.querySelector('.digest-item a');
            return firstArticle?.href || '';
        });

        if (!latestUrl) {
            console.log('ERROR: 未找到最新文章链接');
            return null;
        }

        // 访问最新文章
        await page.goto(latestUrl, {
            waitUntil: 'networkidle2',
            timeout: 30000
        });

        await new Promise(resolve => setTimeout(resolve, 2000));

        // 提取文章内容
        const article = await page.evaluate(() => {
            const title = document.querySelector('h1')?.textContent || '';
            const date = document.querySelector('.date-badge')?.textContent || '';
            const main = document.querySelector('main');

            if (!main) return { title, date, content: '' };

            const paragraphs = Array.from(main.querySelectorAll('p'))
                .map(p => p.textContent.trim())
                .filter(t => t.length > 20);

            const links = Array.from(main.querySelectorAll('a'))
                .map(a => ({
                    text: a.textContent.trim(),
                    href: a.href
                }))
                .filter(l => l.text && l.href && l.text.length > 5 && l.text.length < 100)
                .slice(0, 10);

            return {
                title,
                date,
                paragraphs: paragraphs.slice(0, 15),
                links
            };
        });

        console.log(JSON.stringify(article));

    } catch (error) {
        console.error(`ERROR: ${error.message}`);
        return null;
    } finally {
        await browser.close();
    }
}

fetchLatestDigest();
EOF

# 运行采集脚本
ARTICLE_JSON=$(cd ~/.agents/skills/puppeteer-automation && node "$TEMP_SCRIPT" 2>&1)

if [ $? -ne 0 ]; then
    log "采集失败: $ARTICLE_JSON"
    exit 1
fi

# 提取文章数据
TITLE=$(echo "$ARTICLE_JSON" | grep -o '"title":"[^"]*"' | cut -d'"' -f4)
DATE=$(echo "$ARTICLE_JSON" | grep -o '"date":"[^"]*"' | cut -d'"' -f4)

log "采集成功: $TITLE ($DATE)"

# 格式化文章内容
MESSAGE="# 📰 $TITLE

**📅 日期：** $DATE

"

# 提取段落
echo "$ARTICLE_JSON" | sed -n 's/.*"paragraphs":\[\([^]]*\)\].*/\1/p' | tr ',' '\n' | while read -r para; do
    para=$(echo "$para" | sed 's/\\n/ /g' | sed 's/^"//;s/"$//')
    if [ -n "$para" ] && [ ${#para} -gt 30 ]; then
        MESSAGE="$MESSAGE$para\n\n"
    fi
done

# 提取链接
MESSAGE="$MESSAGE## 🔗 相关链接\n\n"
LINK_NUM=1
echo "$ARTICLE_JSON" | sed -n 's/.*"links":\[[^]]*\].*//p' | sed 's/},/{/g' | tr '{' '\n' | while read -r link; do
    link_text=$(echo "$link" | grep -o '"text":"[^"]*"' | cut -d'"' -f4)
    link_href=$(echo "$link" | grep -o '"href":"[^"]*"' | cut -d'"' -f4)

    if [ -n "$link_text" ] && [ -n "$link_href" ]; then
        MESSAGE="$MESSAGE$LINK_NUM. $link_text\n   $link_href\n\n"
        LINK_NUM=$((LINK_NUM + 1))
    fi
done

MESSAGE="$MESSAGE---

🤖 由小茶茶自动采集 | $(date '+%Y-%m-%d %H:%M:%S')"

# 保存消息到临时文件
echo -e "$MESSAGE" > "$WORKSPACE/temp/daily_digest.txt"

log "文章已准备好，准备发送..."

# 发送消息（这部分需要通过 openclaw 的 message 工具）
# 将内容写入标准输出，供调用者使用
cat "$WORKSPACE/temp/daily_digest.txt"

# 清理临时文件
rm -f "$TEMP_SCRIPT"

log "任务完成"
