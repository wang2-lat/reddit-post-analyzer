#!/usr/bin/env python3
#!/usr/bin/env python3
import click
import requests
import sqlite3
import json
import re
from datetime import datetime
from pathlib import Path

DB_PATH = Path.home() / ".reddit_analyzer.db"

def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS posts (
            id TEXT PRIMARY KEY,
            url TEXT,
            title TEXT,
            content TEXT,
            score INTEGER,
            analysis TEXT,
            created_at TEXT
        )
    """)
    conn.commit()
    return conn

def extract_post_id(url):
    match = re.search(r'/comments/([a-z0-9]+)', url)
    return match.group(1) if match else None

def fetch_reddit_post(url):
    post_id = extract_post_id(url)
    if not post_id:
        raise ValueError("Invalid Reddit URL")
    
    json_url = f"https://www.reddit.com/comments/{post_id}.json"
    headers = {'User-Agent': 'Mozilla/5.0'}
    
    resp = requests.get(json_url, headers=headers, timeout=10)
    resp.raise_for_status()
    
    data = resp.json()[0]['data']['children'][0]['data']
    return {
        'id': data['id'],
        'title': data['title'],
        'content': data.get('selftext', ''),
        'score': data['score'],
        'url': url
    }

def analyze_with_llm(post):
    # 使用简单规则提取关键点（实际项目中替换为真实LLM API）
    content = f"{post['title']} {post['content']}"
    words = content.lower().split()
    
    key_points = []
    if any(w in words for w in ['问题', 'issue', 'bug', 'error']):
        key_points.append("技术问题讨论")
    if any(w in words for w in ['建议', 'suggest', 'recommend']):
        key_points.append("建议或推荐")
    if post['score'] > 100:
        key_points.append("高热度内容")
    
    sentences = re.split(r'[.!?。！？]', content)
    summary = sentences[0][:200] if sentences else content[:200]
    
    return {
        'summary': summary,
        'key_points': key_points,
        'sentiment': 'positive' if post['score'] > 50 else 'neutral',
        'engagement_score': post['score']
    }

def save_post(conn, post, analysis):
    conn.execute("""
        INSERT OR REPLACE INTO posts (id, url, title, content, score, analysis, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (
        post['id'],
        post['url'],
        post['title'],
        post['content'],
        post['score'],
        json.dumps(analysis, ensure_ascii=False),
        datetime.now().isoformat()
    ))
    conn.commit()

@click.group()
def cli():
    """Reddit帖子分析工具"""
    pass

@cli.command()
@click.argument('url')
@click.option('--output', '-o', help='输出JSON文件路径')
def analyze(url, output):
    """分析单个Reddit帖子"""
    try:
        conn = init_db()
        post = fetch_reddit_post(url)
        analysis = analyze_with_llm(post)
        save_post(conn, post, analysis)
        
        result = {
            'post': post,
            'analysis': analysis
        }
        
        if output:
            Path(output).write_text(json.dumps(result, ensure_ascii=False, indent=2))
            click.echo(f"已保存到 {output}")
        else:
            click.echo(json.dumps(result, ensure_ascii=False, indent=2))
        
        conn.close()
    except Exception as e:
        click.echo(f"错误: {e}", err=True)
        raise SystemExit(1)

@cli.command()
@click.argument('urls', nargs=-1, required=True)
@click.option('--output', '-o', default='batch_results.json')
def batch(urls, output):
    """批量分析多个帖子"""
    conn = init_db()
    results = []
    
    for url in urls:
        try:
            post = fetch_reddit_post(url)
            analysis = analyze_with_llm(post)
            save_post(conn, post, analysis)
            results.append({'post': post, 'analysis': analysis})
            click.echo(f"✓ {post['title'][:50]}")
        except Exception as e:
            click.echo(f"✗ {url}: {e}", err=True)
    
    Path(output).write_text(json.dumps(results, ensure_ascii=False, indent=2))
    click.echo(f"\n完成 {len(results)}/{len(urls)} 个帖子，结果保存到 {output}")
    conn.close()

@cli.command()
@click.option('--limit', '-n', default=10, help='显示数量')
def list(limit):
    """列出已分析的帖子"""
    conn = init_db()
    rows = conn.execute(
        "SELECT title, score, created_at FROM posts ORDER BY created_at DESC LIMIT ?",
        (limit,)
    ).fetchall()
    
    for title, score, created in rows:
        click.echo(f"[{score:4d}↑] {title[:60]} ({created[:10]})")
    
    conn.close()

if __name__ == '__main__':
    cli()