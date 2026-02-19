#!/usr/bin/env python3
#!/usr/bin/env python3
import click
import sqlite3
import json
import re
from datetime import datetime
from typing import Dict, List
import httpx

DB_FILE = "reddit_analyzer.db"

def init_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS posts
                 (id TEXT PRIMARY KEY, title TEXT, content TEXT, score INTEGER, 
                  url TEXT, created_at TEXT, analysis TEXT)''')
    conn.commit()
    conn.close()

def fetch_reddit_posts(subreddit: str, limit: int = 25) -> List[Dict]:
    url = f"https://www.reddit.com/r/{subreddit}/hot.json?limit={limit}"
    headers = {"User-Agent": "RedditAnalyzer/1.0"}
    
    try:
        with httpx.Client(timeout=30.0) as client:
            resp = client.get(url, headers=headers)
            resp.raise_for_status()
            data = resp.json()
            
        posts = []
        for child in data.get("data", {}).get("children", []):
            post = child.get("data", {})
            posts.append({
                "id": post.get("id", ""),
                "title": post.get("title", ""),
                "content": post.get("selftext", ""),
                "score": post.get("score", 0),
                "url": f"https://reddit.com{post.get('permalink', '')}",
                "created_at": datetime.fromtimestamp(post.get("created_utc", 0)).isoformat()
            })
        return posts
    except Exception as e:
        raise click.ClickException(f"获取Reddit数据失败: {str(e)}")

def analyze_post(post: Dict) -> Dict:
    text = f"{post['title']} {post['content']}".lower()
    
    # 识别公司类型关键词
    big_corp_keywords = ["google", "amazon", "microsoft", "meta", "apple", "faang", "big tech", "large company", "enterprise"]
    startup_keywords = ["startup", "early stage", "seed", "series a", "small team", "founding", "pre-ipo"]
    
    big_corp_score = sum(1 for kw in big_corp_keywords if kw in text)
    startup_score = sum(1 for kw in startup_keywords if kw in text)
    
    # 识别招聘/职场主题
    hiring_keywords = ["interview", "hiring", "recruit", "candidate", "resume", "cv", "job search"]
    culture_keywords = ["culture", "work-life", "remote", "office", "team", "management"]
    compensation_keywords = ["salary", "compensation", "equity", "stock", "bonus", "pay"]
    
    themes = []
    if any(kw in text for kw in hiring_keywords):
        themes.append("hiring_process")
    if any(kw in text for kw in culture_keywords):
        themes.append("work_culture")
    if any(kw in text for kw in compensation_keywords):
        themes.append("compensation")
    
    # 提取关键见解（简单句子提取）
    sentences = re.split(r'[.!?]\s+', post['content'])
    insights = [s.strip() for s in sentences if len(s.strip()) > 50 and any(kw in s.lower() for kw in hiring_keywords + culture_keywords)][:3]
    
    company_type = "big_corp" if big_corp_score > startup_score else "startup" if startup_score > 0 else "general"
    
    return {
        "post_id": post["id"],
        "company_type": company_type,
        "themes": themes,
        "insights": insights,
        "relevance_score": big_corp_score + startup_score + len(themes),
        "metadata": {
            "title": post["title"],
            "score": post["score"],
            "url": post["url"]
        }
    }

def save_to_db(post: Dict, analysis: Dict):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('''INSERT OR REPLACE INTO posts VALUES (?, ?, ?, ?, ?, ?, ?)''',
              (post["id"], post["title"], post["content"], post["score"], 
               post["url"], post["created_at"], json.dumps(analysis, ensure_ascii=False)))
    conn.commit()
    conn.close()

@click.group()
def cli():
    """Reddit招聘经验分析工具"""
    init_db()

@cli.command()
@click.option("--subreddit", default="cscareerquestions", help="目标subreddit")
@click.option("--limit", default=25, help="抓取帖子数量")
def fetch(subreddit, limit):
    """抓取Reddit帖子并分析"""
    click.echo(f"正在从 r/{subreddit} 抓取 {limit} 条帖子...")
    posts = fetch_reddit_posts(subreddit, limit)
    
    analyzed = 0
    for post in posts:
        if post["content"]:  # 只分析有内容的帖子
            analysis = analyze_post(post)
            save_to_db(post, analysis)
            analyzed += 1
    
    click.echo(f"✓ 成功分析 {analyzed} 条帖子")

@cli.command()
@click.option("--company-type", type=click.Choice(["big_corp", "startup", "all"]), default="all")
@click.option("--min-score", default=0, help="最低票数过滤")
@click.option("--output", default="analysis.json", help="输出文件")
def analyze(company_type, min_score, output):
    """生成结构化分析报告"""
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT id, title, score, analysis FROM posts WHERE score >= ?", (min_score,))
    rows = c.fetchall()
    conn.close()
    
    results = {"big_corp": [], "startup": [], "general": []}
    theme_stats = {"hiring_process": 0, "work_culture": 0, "compensation": 0}
    
    for row in rows:
        analysis = json.loads(row[3])
        if company_type == "all" or analysis["company_type"] == company_type:
            results[analysis["company_type"]].append(analysis)
            for theme in analysis["themes"]:
                theme_stats[theme] = theme_stats.get(theme, 0) + 1
    
    report = {
        "generated_at": datetime.now().isoformat(),
        "summary": {
            "total_posts": sum(len(v) for v in results.values()),
            "big_corp_posts": len(results["big_corp"]),
            "startup_posts": len(results["startup"]),
            "theme_distribution": theme_stats
        },
        "insights_by_type": results
    }
    
    with open(output, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
    
    click.echo(f"✓ 分析报告已保存到 {output}")
    click.echo(f"  大公司相关: {len(results['big_corp'])} 条")
    click.echo(f"  创业公司相关: {len(results['startup'])} 条")

@cli.command()
def stats():
    """显示数据库统计"""
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT COUNT(*), AVG(score) FROM posts")
    count, avg_score = c.fetchone()
    conn.close()
    
    click.echo(f"数据库统计:")
    click.echo(f"  总帖子数: {count}")
    click.echo(f"  平均票数: {avg_score:.1f}" if avg_score else "  平均票数: 0")

if __name__ == "__main__":
    cli()