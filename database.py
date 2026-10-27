import aiosqlite

DB_FILE = "system_queue.db"

async def init_db():
    async with aiosqlite.connect(DB_FILE) as db:
        await db.execute('''
            CREATE TABLE IF NOT EXISTS tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                url TEXT NOT NULL,
                proxy TEXT,
                used_proxy TEXT,
                watch_seconds INTEGER DEFAULT 0,
                repeat_count INTEGER DEFAULT 1,
                current_repeat INTEGER DEFAULT 0,
                elapsed_seconds INTEGER DEFAULT 0,
                total_duration INTEGER DEFAULT 0,
                max_retries INTEGER DEFAULT 3,
                attempts INTEGER DEFAULT 0,
                status TEXT DEFAULT 'QUEUED'
            )
        ''')
        await db.execute('''
            CREATE TABLE IF NOT EXISTS logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                message TEXT NOT NULL,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        await db.commit()

async def add_task(url, proxy=None, watch_seconds=0, repeat_count=1):
    async with aiosqlite.connect(DB_FILE) as db:
        await db.execute('''
            INSERT INTO tasks (url, proxy, watch_seconds, repeat_count, status)
            VALUES (?, ?, ?, ?, 'QUEUED')
        ''', (url, proxy, watch_seconds, repeat_count))
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

async def update_task_progress(task_id, elapsed, total):
    async with aiosqlite.connect(DB_FILE) as db:
        await db.execute("UPDATE tasks SET elapsed_seconds = ?, total_duration = ? WHERE id = ?", (elapsed, total, task_id))
        await db.commit()

async def add_log(message):
    async with aiosqlite.connect(DB_FILE) as db:
        await db.execute("INSERT INTO logs (message) VALUES (?)", (message,))
        await db.commit()
