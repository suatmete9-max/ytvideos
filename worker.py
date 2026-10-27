import sys
import asyncio
import os
import random

if sys.platform == 'win32':
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

from playwright.async_api import async_playwright
from dotenv import load_dotenv
from database import init_db, update_task_status, update_task_progress, add_log, DB_FILE
import aiosqlite

load_dotenv()

SAFE_PROXIES = [
    "http://20.205.61.155:80",
    "http://185.199.229.156:7492",
    "http://51.158.118.72:8811"
]

DEVICE_PROFILES = [
    {
        "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "viewport": {"width": 1366, "height": 768},
        "name": "Windows PC"
    },
    {
        "user_agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_2_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Mobile/15E148 Safari/604.1",
        "viewport": {"width": 390, "height": 844},
        "name": "iPhone 15"
    },
    {
        "user_agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2.1 Safari/605.1.15",
        "viewport": {"width": 1280, "height": 800},
        "name": "MacBook"
    }
]

async def execute_single_task(task_id, url, custom_proxy, watch_seconds, repeat_count, current_repeat, max_retries, foreign_proxies):
    async with async_playwright() as p:
        browser = None
        try:
            browser = await p.chromium.launch(
                headless=True,
                args=["--disable-dev-shm-usage", "--no-sandbox", "--disable-setuid-sandbox", "--disable-gpu"]
            )
        except Exception as e:
            await add_log(f"Task {task_id} Browser launch error: {e}")
            await update_task_status(task_id, "QUEUED")
            return

        target_loops = float('inf') if repeat_count <= 0 else repeat_count
        attempts = 0

        while current_repeat < target_loops:
            active_proxy = custom_proxy if custom_proxy else random.choice(foreign_proxies)
            device = random.choice(DEVICE_PROFILES)
            
            proxy_with_device = f"{active_proxy.split('//')[-1]} [{device['name']}]"
            await update_task_status(task_id, "RUNNING", current_repeat, proxy_with_device)

            context = None
            try:
                context_options = {
                    "user_agent": device["user_agent"],
                    "viewport": device["viewport"]
                }
                if active_proxy and "Direct" not in active_proxy:
                    context_options["proxy"] = {"server": active_proxy}
                
                context = await browser.new_context(**context_options)
                page = await context.new_page()

                # Block heavy assets to save memory and speed up loading
                await page.route("**/*.{png,jpg,jpeg,gif,svg,css,font,woff,woff2}", lambda route: route.abort())

                try:
                    await page.goto(url, timeout=15000, wait_until="domcontentloaded")
                except Exception:
                    await context.close()
                    context = await browser.new_context(user_agent=device["user_agent"], viewport=device["viewport"])
                    page = await context.new_page()
                    proxy_with_device = f"Direct IP [{device['name']}]"
                    await update_task_status(task_id, "RUNNING", current_repeat, proxy_with_device)
                    await page.goto(url, timeout=18000, wait_until="domcontentloaded")

                # Try skipping ads if present
                try:
                    await asyncio.sleep(1)
                    skip_btn = page.locator(".ytp-ad-skip-button, button:has-text('Skip Ad')")
                    if await skip_btn.count() > 0:
                        await skip_btn.first.click(timeout=1000)
                except:
                    pass
                
                # Determine watch duration
                actual_duration = watch_seconds
                if watch_seconds <= 0:
                    try:
                        dur = await page.evaluate("() => { const v = document.querySelector('video'); return v ? v.duration : 30; }")
                        actual_duration = int(dur) if dur and dur > 0 else 30
                    except:
                        actual_duration = 30

                # Live timer progress loop
                elapsed = 0
                while elapsed < actual_duration:
                    await asyncio.sleep(1)
                    elapsed += 1
                    await update_task_progress(task_id, elapsed, actual_duration)

                current_repeat += 1
                await update_task_status(task_id, "RUNNING", current_repeat, proxy_with_device)

            except Exception as loop_err:
                await add_log(f"Task {task_id} error: {str(loop_err)}")
                attempts += 1
                if attempts >= max_retries:
                    break
            finally:
                if context:
                    try:
                        await context.close()
                    except:
                        pass

            if repeat_count > 0 and current_repeat >= repeat_count:
                break

        if current_repeat > 0 and (repeat_count <= 0 or current_repeat >= repeat_count):
            await update_task_status(task_id, "SUCCESS", current_repeat)
            await add_log(f"Task {task_id}: Completed successfully!")
        else:
            await update_task_status(task_id, "FAILED")

        if browser:
            try:
                await browser.close()
            except:
                pass

async def start_workers():
    await init_db()
    await add_log("Worker engine active & ready.")
    
    while True:
        try:
            async with aiosqlite.connect(DB_FILE) as db:
                async with db.execute("SELECT id, url, proxy, watch_seconds, repeat_count, current_repeat, max_retries FROM tasks WHERE status = 'QUEUED'") as cursor:
                    rows = await cursor.fetchall()
            
            if rows:
                for row in rows:
                    task_id, url, proxy, watch_seconds, repeat_count, current_repeat, max_retries = row
                    async with aiosqlite.connect(DB_FILE) as db:
                        await db.execute("UPDATE tasks SET status = 'RUNNING', attempts = attempts + 1 WHERE id = ?", (task_id,))
                        await db.commit()
                    
                    asyncio.create_task(execute_single_task(task_id, url, proxy, watch_seconds, repeat_count, current_repeat, max_retries, SAFE_PROXIES))
            
            await asyncio.sleep(0.3)
        except Exception as e:
            await add_log(f"Manager error: {str(e)}")
            await asyncio.sleep(2)

if __name__ == "__main__":
    asyncio.run(start_workers())
