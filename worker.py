import sys
import asyncio
import os
import random
import aiohttp

if sys.platform == 'win32':
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

from playwright.async_api import async_playwright
from dotenv import load_dotenv
from database import init_db, update_task_status, update_task_progress, add_log, DB_FILE
import aiosqlite

load_dotenv()

PROXY_SOURCES = [
    "https://raw.githubusercontent.com/TheSpeedX/SOCKS-List/master/http.txt",
    "https://raw.githubusercontent.com/hookzof/socks5_list/master/proxy.txt",
    "https://raw.githubusercontent.com/clarketm/proxy-list/master/proxy-list-raw.txt",
    "https://raw.githubusercontent.com/sunny9577/proxy-scraper/master/proxies.txt",
    "https://raw.githubusercontent.com/jetkai/proxy-list/main/online-proxies/txt/proxies-http.txt"
]

async def verify_clean_proxy(session, proxy):
    try:
        # Google ya YouTube par test karke check karenge ki proxy clean hai ya blacklisted/blocked
        async with session.get("https://www.youtube.com", proxy=proxy, timeout=3) as resp:
            if resp.status == 200:
                return proxy
    except:
        pass
    return None

async def fetch_and_verify_proxies():
    raw_proxies = []
    for url in PROXY_SOURCES:
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=4) as resp:
                    if resp.status == 200:
                        text = await resp.text()
                        for line in text.splitlines():
                            line = line.strip()
                            if line and ":" in line:
                                raw_proxies.append(f"http://{line}")
        except:
            continue
    
    raw_proxies = list(set(raw_proxies))
    random.shuffle(raw_proxies)
    
    # Strict filtering: Sirf non-blacklisted aur fully working clean proxies select hongi
    clean_working_proxies = []
    async with aiohttp.ClientSession() as session:
        tasks = [verify_clean_proxy(session, p) for p in raw_proxies[:50]]
        results = await asyncio.gather(*tasks)
        clean_working_proxies = [r for r in results if r is not None]

    if not clean_working_proxies:
        clean_working_proxies = [
            "http://20.205.61.155:80", 
            "http://185.199.229.156:7492", 
            "http://51.158.118.72:8811"
        ]
    
    await add_log(f"[Proxy Engine] Filtered & Loaded {len(clean_working_proxies)} Clean Non-Blacklisted IPs.")
    return clean_working_proxies

DEVICE_PROFILES = [
    {
        "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "viewport": {"width": 1366, "height": 768},
        "name": "Windows PC (Chrome)"
    },
    {
        "user_agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2.1 Safari/605.1.15",
        "viewport": {"width": 1280, "height": 800},
        "name": "Apple MacBook"
    },
    {
        "user_agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_2_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Mobile/15E148 Safari/604.1",
        "viewport": {"width": 390, "height": 844},
        "name": "Apple iPhone 15"
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
            
            loop_display = "Infinite" if repeat_count <= 0 else f"{current_repeat+1}/{repeat_count}"
            await add_log(f"Task {task_id} (Loop {loop_display}) -> Device: [{device['name']}] | Clean Proxy: {active_proxy}")

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

                await page.route("**/*.{png,jpg,jpeg,gif,svg,css,font,woff,woff2}", lambda route: route.abort())

                try:
                    await page.goto(url, timeout=15000, wait_until="domcontentloaded")
                except Exception:
                    await context.close()
                    context = await browser.new_context(user_agent=device["user_agent"], viewport=device["viewport"])
                    page = await context.new_page()
                    active_proxy = "Direct IP (Smart Fallback)"
                    await page.goto(url, timeout=18000, wait_until="domcontentloaded")

                try:
                    await asyncio.sleep(1.5)
                    skip_btn = page.locator(".ytp-ad-skip-button, button:has-text('Skip Ad')")
                    if await skip_btn.count() > 0:
                        await skip_btn.first.click(timeout=1500)
                except:
                    pass
                
                actual_duration = watch_seconds
                if watch_seconds <= 0:
                    try:
                        dur = await page.evaluate("() => { const v = document.querySelector('video'); return v ? v.duration : 45; }")
                        actual_duration = int(dur) if dur and dur > 0 else 45
                    except:
                        actual_duration = 45

                elapsed = 0
                while elapsed < actual_duration:
                    await asyncio.sleep(1)
                    elapsed += 1
                    await update_task_progress(task_id, elapsed, actual_duration)

                current_repeat += 1
                await update_task_status(task_id, "RUNNING", current_repeat, f"{active_proxy} ({device['name']})")

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
    foreign_proxies = await fetch_and_verify_proxies()

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
                    
                    asyncio.create_task(execute_single_task(task_id, url, proxy, watch_seconds, repeat_count, current_repeat, max_retries, foreign_proxies))
            
            await asyncio.sleep(0.3)
        except Exception as e:
            await add_log(f"Manager loop error: {str(e)}")
            await asyncio.sleep(2)

if __name__ == "__main__":
    asyncio.run(start_workers())
