const puppeteer = require('puppeteer');
const fs = require('fs');

const LOG_FILE = '/root/.openclaw/workspace/logs/daily_digest.log';

function log(message) {
    const timestamp = new Date().toISOString();
    const logMsg = `[${timestamp}] ${message}\n`;
    fs.appendFileSync(LOG_FILE, logMsg);
    console.log(logMsg.trim());
}

async function fetchLatestDigest() {
    log('开始采集每日科技简报...');

    const browser = await puppeteer.launch({
        headless: 'new',
        args: ['--no-sandbox', '--disable-setuid-sandbox']
    });

    try {
        const page = await browser.newPage();
        await page.setUserAgent('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36');

        log('访问归档页面...');
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
            throw new Error('未找到最新文章链接');
        }

        log(`最新文章: ${latestUrl}`);

        log('访问文章详情页...');
        await page.goto(latestUrl, {
            waitUntil: 'networkidle2',
            timeout: 30000
        });

        await new Promise(resolve => setTimeout(resolve, 2000));

        const article = await page.evaluate(() => {
            const title = document.querySelector('h1')?.textContent || '';
            const date = document.querySelector('.date-badge')?.textContent || '';
            const mainText = document.querySelector('main')?.textContent || document.body.textContent;

            const introMatch = mainText.match(/导语[：:]([^.]+\.)/);
            const intro = introMatch ? introMatch[1].trim() : '';

            const items = [];
            const lines = mainText.split('\n').map(l => l.trim()).filter(l => l.length > 10);

            let currentItem = null;
            lines.forEach(line => {
                if (line.match(/^📈|🚀|📱|📚/)) {
                    currentItem = { section: line, articles: [] };
                } else if (currentItem && line.length > 20 && line.length < 500) {
                    currentItem.articles.push(line);
                    if (currentItem.articles.length >= 3) {
                        items.push(currentItem);
                        currentItem = null;
                    }
                }
            });

            return {
                title,
                date,
                intro,
                items: items.slice(0, 8)
            };
        });

        let message = `# 📰 ${article.title}\n\n**📅 日期：** ${article.date}\n\n`;

        if (article.intro) {
            message += `## 💡 导语\n\n${article.intro}\n\n`;
            message += `${'─'.repeat(60)}\n\n`;
        }

        article.items.forEach(item => {
            message += `## ${item.section}\n\n`;
            message += `${'─'.repeat(60)}\n\n`;
            item.articles.forEach((articleText, idx) => {
                message += `${idx + 1}. ${articleText}\n\n`;
            });
        });

        message += `${'─'.repeat(80)}\n`;
        message += `✅ 采集完成！共 ${article.items.reduce((sum, i) => sum + i.articles.length, 0)} 篇文章\n`;
        message += `${'─'.repeat(80)}\n\n`;
        message += `🤖 由小茶茶自动采集 | ${new Date().toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai' })}`;

        const outputPath = '/root/.openclaw/workspace/temp/daily_digest.txt';
        fs.writeFileSync(outputPath, message, 'utf-8');

        log(`采集成功: ${article.title}`);
        log(`文章已保存到: ${outputPath}`);

        console.log('\n' + '='.repeat(80));
        console.log(message);
        console.log('='.repeat(80));

        return message;

    } catch (error) {
        log(`采集失败: ${error.message}`);
        throw error;
    } finally {
        await browser.close();
    }
}

fetchLatestDigest().catch(error => {
    log(`致命错误: ${error.message}`);
    process.exit(1);
});
