import os
import json
import logging
from db import get_db_client

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def fetch_data():
    supabase = get_db_client()
    
    # Fetch processed videos
    videos_res = supabase.table("videos").select("*").eq("status", "processed").order("upload_date", desc=True).execute()
    videos = videos_res.data
    
    # Fetch insights
    insights_res = supabase.table("insights").select("*").execute()
    insights_map = {item['video_id']: item for item in insights_res.data}
    
    merged_data = []
    for v in videos:
        vid_id = v['video_id']
        if vid_id in insights_map:
            merged_data.append({
                'video_id': vid_id,
                'title': v['title'],
                'upload_date': v['upload_date'],
                'high_level_summary': insights_map[vid_id].get('high_level_summary', ''),
                'detailed_learnings': insights_map[vid_id].get('detailed_learnings', ''),
                'newsletter_text': insights_map[vid_id].get('newsletter_text', ''),
            })
            
    return merged_data

def generate_html(data):
    html = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
    <title>AI Engineer Newsletter Digest</title>
    
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
    
    <style>
        :root {
            --bg: #fafaf7;
            --bg-card: #ffffff;
            --text: #14110d;
            --text-muted: #6b665e;
            --accent: #d77a3a;
            --border: #e8e2d6;
            --radius: 12px;
            --shadow: 0 2px 8px rgba(20,17,13,.04);
        }
        
        * { box-sizing: border-box; }
        
        body {
            font-family: 'Inter', -apple-system, sans-serif;
            background: var(--bg);
            color: var(--text);
            line-height: 1.6;
            margin: 0;
            padding: 0;
        }
        
        header {
            max-width: 900px;
            margin: 0 auto;
            padding: 80px 20px 40px;
        }
        
        h1 {
            font-size: clamp(2rem, 5vw, 3.5rem);
            font-weight: 800;
            letter-spacing: -0.02em;
            margin: 0 0 10px;
        }
        
        p.subtitle {
            font-size: 1.25rem;
            color: var(--text-muted);
            margin-bottom: 40px;
        }
        
        main {
            max-width: 900px;
            margin: 0 auto;
            padding: 0 20px 80px;
        }
        
        .card {
            background: var(--bg-card);
            border: 1px solid var(--border);
            border-radius: var(--radius);
            padding: 32px;
            margin-bottom: 32px;
            box-shadow: var(--shadow);
            transition: transform 0.2s ease, box-shadow 0.2s ease;
        }
        
        .card:hover {
            transform: translateY(-2px);
            box-shadow: 0 8px 24px rgba(20,17,13,.08);
        }
        
        .card-header {
            display: flex;
            justify-content: space-between;
            align-items: baseline;
            margin-bottom: 16px;
            flex-wrap: wrap;
            gap: 8px;
        }
        
        h2 {
            font-size: 1.5rem;
            font-weight: 700;
            margin: 0;
            line-height: 1.3;
        }
        
        .date {
            font-family: 'JetBrains Mono', monospace;
            font-size: 0.875rem;
            color: var(--text-muted);
            background: var(--bg);
            padding: 4px 8px;
            border-radius: 4px;
            border: 1px solid var(--border);
        }
        
        h3 {
            font-size: 1.1rem;
            color: var(--accent);
            margin: 24px 0 12px;
        }
        
        p {
            margin-bottom: 16px;
        }
        
        .detailed-learnings {
            white-space: pre-wrap;
            color: var(--text-muted);
            font-size: 0.95rem;
        }
        
        a.youtube-link {
            display: inline-flex;
            align-items: center;
            gap: 8px;
            background: var(--text);
            color: var(--bg);
            padding: 10px 16px;
            border-radius: 8px;
            text-decoration: none;
            font-weight: 600;
            font-size: 0.9rem;
            margin-top: 24px;
            transition: opacity 0.2s ease;
        }
        
        a.youtube-link:hover {
            opacity: 0.9;
        }
        
        #backTop {
            position: fixed;
            bottom: 24px;
            right: 24px;
            background: var(--text);
            color: var(--bg);
            border: none;
            border-radius: 50%;
            width: 48px;
            height: 48px;
            font-size: 24px;
            cursor: pointer;
            opacity: 0;
            pointer-events: none;
            transition: opacity 0.3s ease;
            box-shadow: var(--shadow);
            z-index: 100;
        }
        
        #backTop.visible {
            opacity: 1;
            pointer-events: auto;
        }
    </style>
</head>
<body>

    <header>
        <h1>AI Engineer Digest</h1>
        <p class="subtitle">The complete operator-mode digest of the best AI engineering content.</p>
    </header>

    <main>
"""
    
    for item in data:
        # Simple string escaping for safety on title
        title = str(item['title']).replace('<', '&lt;').replace('>', '&gt;')
        date = item['upload_date']
        video_id = item['video_id']
        
        # Display the full Telegram newsletter text (safely allowing HTML tags like <b>, <i>, <code>, <pre>, <a>)
        newsletter_text = item.get('newsletter_text') or ""
        if not newsletter_text:
            # Fallback to high level summary + detailed learnings if newsletter_text is empty
            summary = str(item.get('high_level_summary', '')).replace('<', '&lt;').replace('>', '&gt;')
            learnings = str(item.get('detailed_learnings', '')).replace('<', '&lt;').replace('>', '&gt;')
            newsletter_text = f"<h3>High-Level Summary</h3><p>{summary}</p><h3>Detailed Learnings</h3><div class='detailed-learnings'>{learnings}</div>"
        
        html += f"""
        <article class="card">
            <div class="card-header">
                <h2>{title}</h2>
                <span class="date">{date}</span>
            </div>
            
            <div class="newsletter-content" style="white-space: pre-wrap; font-size: 0.95rem; color: #2d2a25;">{newsletter_text}</div>
            
            <a href="https://youtube.com/watch?v={video_id}" target="_blank" class="youtube-link">
                <svg width="20" height="20" viewBox="0 0 24 24" fill="currentColor">
                    <path d="M19.615 3.184c-3.604-.246-11.631-.245-15.23 0-3.897.266-4.356 2.62-4.385 8.816.029 6.185.484 8.549 4.385 8.816 3.6.245 11.626.246 15.23 0 3.897-.266 4.356-2.62 4.385-8.816-.029-6.185-.484-8.549-4.385-8.816zm-10.615 12.816v-8l8 3.993-8 4.007z"/>
                </svg>
                Watch on YouTube
            </a>
        </article>
        """
        
    html += """
    </main>
    
    <button id="backTop">↑</button>

    <script>
        const backTop = document.getElementById('backTop');
        window.addEventListener('scroll', () => {
            backTop.classList.toggle('visible', window.scrollY > 400);
        });
        backTop.addEventListener('click', () => window.scrollTo({ top: 0, behavior: 'smooth' }));
    </script>
</body>
</html>
"""
    return html

def build_site():
    logging.info("Generating static site...")
    data = fetch_data()
    logging.info(f"Fetched {len(data)} processed videos with insights.")
    
    html_content = generate_html(data)
    
    # Ensure public directory exists
    os.makedirs("public", exist_ok=True)
    
    # Write the output file
    output_path = os.path.join("public", "index.html")
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html_content)
        
    logging.info(f"Static site successfully built at {output_path}")

if __name__ == "__main__":
    build_site()
