import sys
import asyncio

if sys.platform == 'win32':
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

from fastapi import FastAPI, Form
from fastapi.responses import HTMLResponse, RedirectResponse
import aiosqlite
from database import init_db, add_task, DB_FILE
from worker import start_workers
import os

app = FastAPI()

@app.on_event("startup")
async def startup_event():
    await init_db()
    loop = asyncio.get_event_loop()
    loop.create_task(start_workers())

def format_time(seconds):
    m = seconds // 60
    s = seconds % 60
    return f"{m:02d}:{s:02d}"

@app.get("/", response_class=HTMLResponse)
async def dashboard():
    async with aiosqlite.connect(DB_FILE) as db:
        cursor_active = await db.execute("SELECT id, url, proxy, used_proxy, watch_seconds, repeat_count, current_repeat, elapsed_seconds, total_duration, status FROM tasks WHERE status IN ('QUEUED', 'RUNNING') ORDER BY id DESC")
        active_tasks = await cursor_active.fetchall()
        
        cursor_history = await db.execute("SELECT id, url, used_proxy, watch_seconds, repeat_count, current_repeat, status FROM tasks WHERE status IN ('SUCCESS', 'FAILED') ORDER BY id DESC LIMIT 50")
        history_tasks = await cursor_history.fetchall()
        
        cursor_logs = await db.execute("SELECT message, timestamp FROM logs ORDER BY id DESC LIMIT 25")
        logs = await cursor_logs.fetchall()

    active_html = ""
    for t in active_tasks:
        task_id, url, proxy, used_proxy, watch_sec, repeat_cnt, cur_rep, elapsed, total, status = t
        proxy_display = used_proxy if used_proxy else "Running Proxy..."
        
        if status == 'RUNNING' and total > 0:
            percent = int((elapsed / total) * 100)
            progress_str = f"{format_time(elapsed)} / {format_time(total)} ({percent}% Done)"
        else:
            progress_str = "Starting..."

        active_html += f"<tr><td>{task_id}</td><td style='word-break: break-all;'>{url}</td><td>{proxy_display}</td><td><b>{progress_str}</b></td><td>{cur_rep}/{'Infinite' if repeat_cnt<=0 else repeat_cnt}</td><td><b style='color: #007bff;'>{status}</b></td></tr>"

    if not active_html:
        active_html = "<tr><td colspan='6' style='text-align: center; color: #777;'>No active tasks running right now. Add links above!</td></tr>"

    history_html = "".join([f"<tr><td>{t[0]}</td><td style='word-break: break-all;'>{t[1]}</td><td>{t[2] if t[2] else 'Auto Proxy'}</td><td>{'Full Video' if t[3]<=0 else str(t[3]) + 's'}</td><td>{t[5]}/{'Infinite' if t[4]<=0 else t[4]}</td><td><b style='color: {'#28a745' if t[6]=='SUCCESS' else '#dc3545'};'>{t[6]}</b></td></tr>" for t in history_tasks])
    if not history_html:
        history_html = "<tr><td colspan='6' style='text-align: center; color: #777;'>No history records yet. Completed tasks will stay here.</td></tr>"

    logs_html = "".join([f"<li>[{l[1]}] {l[0]}</li>" for l in logs])

    return f"""
    <html>
        <head>
            <title>Cloud Automation Dashboard</title>
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <style>
                body {{ font-family: Arial, sans-serif; margin: 15px; background: #f4f6f8; }}
                h1 {{ font-size: 22px; color: #333; }}
                .top-bar {{ display: flex; justify-content: space-between; align-items: center; margin-bottom: 15px; flex-wrap: wrap; gap: 10px; }}
                table {{ width: 100%; border-collapse: collapse; background: white; margin-top: 10px; margin-bottom: 25px; font-size: 13px; box-shadow: 0 2px 5px rgba(0,0,0,0.05); overflow-x: auto; display: block; }}
                th, td {{ padding: 10px; border: 1px solid #ddd; text-align: left; }}
                th {{ background: #007bff; color: white; }}
                ul {{ background: white; padding: 12px; border: 1px solid #ddd; max-height: 180px; overflow-y: auto; font-family: monospace; font-size: 11px; }}
                form {{ background: white; padding: 20px; border: 1px solid #ddd; border-radius: 8px; margin-bottom: 20px; box-shadow: 0 2px 8px rgba(0,0,0,0.08); }}
                .form-grid {{ display: grid; grid-template-columns: 1fr; gap: 15px; margin-bottom: 15px; }}
                @media(min-width: 768px) {{ .form-grid {{ grid-template-columns: 1fr 1fr; }} }}
                .field-group {{ display: flex; flex-direction: column; gap: 5px; }}
                .full-width {{ grid-column: span 1; }}
                @media(min-width: 768px) {{ .full-width {{ grid-column: span 2; }} }}
                label {{ font-size: 12px; font-weight: bold; color: #444; }}
                input {{ padding: 10px; font-size: 14px; border: 1px solid #ccc; border-radius: 4px; width: 100%; box-sizing: border-box; }}
                button {{ padding: 12px 20px; background: #28a745; color: white; border: none; border-radius: 4px; cursor: pointer; font-size: 15px; font-weight: bold; width: 100%; }}
                button:hover {{ background: #218838; }}
                .refresh-btn {{ background: #007bff; width: auto; padding: 8px 15px; font-size: 13px; }}
            </style>
        </head>
        <body>
            <div class="top-bar">
                <div>
                    <h1>Cloud Automation Dashboard</h1>
                    <p style="margin: 5px 0 0 0; font-size: 13px; color: #666;">Multi-Tab Instant Multiplier | Real Proxy & Device Rotation</p>
                </div>
                <button class="refresh-btn" onclick="window.location.reload();">🔄 Refresh Page</button>
            </div>
            
            <form action="/add-task" method="post">
                <div class="form-grid">
                    <div class="field-group full-width">
                        <label>🔗 Video URL (Target Link):</label>
                        <input type="text" name="url" placeholder="https://youtu.be/..." required>
                    </div>
                    <div class="field-group">
                        <label>📑 Number of Tabs / Instances:</label>
                        <input type="number" name="tab_count" value="1" min="1" max="100">
                    </div>
                    <div class="field-group">
                        <label>🌐 Custom Proxy (Optional):</label>
                        <input type="text" name="proxy" placeholder="http://ip:port">
                    </div>
                    <div class="field-group">
                        <label>⏱️ Watch Duration (0 = Full Video):</label>
                        <input type="number" name="watch_seconds" value="0">
                    </div>
                    <div class="field-group">
                        <label>🔁 Repeat Count (0 = Infinite Loop):</label>
                        <input type="number" name="repeat_count" value="1">
                    </div>
                </div>
                <button type="submit">Add Task(s) to Queue</button>
            </form>

            <h2>⚡ Live Active Tasks & Progress</h2>
            <table>
                <tr><th>ID</th><th>URL</th><th>Proxy IP & Device</th><th>Watch Progress</th><th>Loops</th><th>Status</th></tr>
                {active_html}
            </table>

            <h2>📜 Completed Task History (Saved Permanently)</h2>
            <table>
                <tr><th>ID</th><th>URL</th><th>Proxy Used</th><th>Duration</th><th>Loops</th><th>Status</th></tr>
                {history_html}
            </table>
            
            <h2>Live System Logs</h2>
            <ul>{logs_html}</ul>
        </body>
    </html>
    """

@app.get("/add-task")
async def get_add_task():
    return RedirectResponse(url="/", status_code=303)

@app.post("/add-task")
async def create_task(url: str = Form(...), proxy: str = Form(None), watch_seconds: int = Form(0), repeat_count: int = Form(1), tab_count: int = Form(1)):
    clean_proxy = proxy.strip() if proxy and proxy.strip() else None
    for _ in range(max(1, tab_count)):
        await add_task(url, clean_proxy, watch_seconds, repeat_count)
    return RedirectResponse(url="/", status_code=303)

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("app:app", host="0.0.0.0", port=port)
