import aiosqlite

DB_FILE = "system_queue.db"

async def init_db():
    async with aiosqlite.connect(DB_FILE) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                url TEXT,
                proxy TEXT,
                used_proxy TEXT,
                watch_seconds INTEGER DEFAULT 0,
                repeat_count INTEGER DEFAULT 1,
                current_repeat INTEGER DEFAULT 0,
                elapsed_seconds INTEGER DEFAULT 0,
                total_duration INTEGER DEFAULT 0,
                status TEXT DEFAULT 'QUEUED',
                attempts INTEGER DEFAULT 0,
                max_retries INTEGER DEFAULT 3,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                message TEXT,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await db.commit()

async def add_task(url, proxy=None, watch_seconds=0, repeat_count=1, max_retries=3):
    async with aiosqlite.connect(DB_FILE) as db:
        await db.execute(
            "INSERT INTO tasks (url, proxy, watch_seconds, repeat_count, max_retries) VALUES (?, ?, ?, ?, ?)",
            (url, proxy, watch_seconds, repeat_count, max_retries)
        )
        await db.commit()

async def add_log(msg):
    async with aiosqlite.connect(DB_FILE) as db:
        await db.execute("INSERT INTO logs (message) VALUES (?)", (msg,))
        await db.commit()
        await db.execute("DELETE FROM logs WHERE id NOT IN (SELECT id FROM logs ORDER BY id DESC LIMIT 150)")
        await db.commit()

async def get_next_task():
    async with aiosqlite.connect(DB_FILE) as db:
        async with db.execute("SELECT id, url, proxy, watch_seconds, repeat_count, current_repeat, attempts, max_retries FROM tasks WHERE status = 'QUEUED' LIMIT 1") as cursor:
            row = await cursor.fetchone()
            if row:
                task_id, url, proxy, watch_seconds, repeat_count, current_repeat, attempts, max_retries = row
                await db.execute("UPDATE tasks SET status = 'RUNNING', attempts = attempts + 1 WHERE id = ?", (task_id,))
                await db.commit()
                return task_id, url, proxy, watch_seconds, repeat_count, current_repeat, attempts + 1, max_retries
    return None

async def update_task_progress(task_id, elapsed, total):
    async with aiosqlite.connect(DB_FILE) as db:
        await db.execute("UPDATE tasks SET elapsed_seconds = ?, total_duration = ? WHERE id = ?", (elapsed, total, task_id))
        await db.commit()

async def update_task_status(task_id, status, current_repeat=None, used_proxy=None):
    async with aiosqlite.connect(DB_FILE) as db:
        if current_repeat is not None and used_proxy is not None:
            await db.execute("UPDATE tasks SET status = ?, current_repeat = ?, used_proxy = ? WHERE id = ?", (status, current_repeat, used_proxy, task_id))
        elif current_repeat is not None:
            await db.execute("UPDATE tasks SET status = ?, current_repeat = ? WHERE id = ?", (status, current_repeat, task_id))
        elif used_proxy is not None:
            await db.execute("UPDATE tasks SET status = ?, used_proxy = ? WHERE id = ?", (status, used_proxy, task_id))
        else:
            await db.execute("UPDATE tasks SET status = ? WHERE id = ?", (status, task_id))
        await db.commit()