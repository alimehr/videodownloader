"""Small private-chat YouTube bot. Python 3.11+."""
import asyncio
import json
import logging
import os
from pathlib import Path
import re
import signal
import sqlite3
import sys
import tempfile
from urllib.parse import urlparse, parse_qs

from dotenv import load_dotenv
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.error import BadRequest
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters

load_dotenv()
TOKEN = os.getenv('BOT_TOKEN', '')
ALLOWED = {int(x.strip()) for x in os.getenv('ALLOWED_USER_IDS', '').split(',') if x.strip()}
DATA = Path(os.getenv('DATA_DIR', 'data'))
MAX_BYTES = 49_000_000
MAX_DURATION = 1200
QUEUE = asyncio.Queue(maxsize=10)
BUSY = set()
DB = None
LOG = logging.getLogger('youtube_bot')


def video_id(text):
    """Accept only explicit YouTube video URLs; reconstruct a canonical URL."""
    for raw in re.findall(r'https?://[^\s<>]+', text):
        p = urlparse(raw.rstrip(').,،'))
        if p.username or p.password or p.port not in (None, 443, 80):
            continue
        host = (p.hostname or '').lower()
        parts = p.path.strip('/').split('/')
        value = None
        if host == 'youtu.be' and len(parts) == 1:
            value = parts[0]
        elif host in {'youtube.com', 'www.youtube.com', 'm.youtube.com', 'music.youtube.com'}:
            if p.path == '/watch':
                value = parse_qs(p.query).get('v', [''])[0]
            elif len(parts) == 2 and parts[0] in {'shorts', 'embed', 'live'}:
                value = parts[1]
        if value and re.fullmatch(r'[A-Za-z0-9_-]{11}', value):
            return value
    return None


async def permitted(update):
    if update.effective_chat.type != 'private':
        return False
    if ALLOWED and update.effective_user.id not in ALLOWED:
        await update.effective_message.reply_text('این ربات خصوصی است.')
        return False
    return True


async def start(update, context):
    if await permitted(update):
        await update.message.reply_text('لینک ویدئو یا Shorts یوتیوب را بفرست. سپس کیفیت یا MP3 را انتخاب کن.\nحداکثر مدت: ۲۰ دقیقه؛ حجم خروجی: ۴۹ مگابایت.\nفقط محتوایی را دانلود کن که اجازه دریافتش را داری.\nشناسه شما: ' + str(update.effective_user.id))


async def link(update, context):
    if not await permitted(update):
        return
    try:
        vid = video_id(update.message.text)
    except ValueError:
        vid = None
    if not vid:
        await update.message.reply_text('یک لینک معتبر ویدئو از youtube.com یا youtu.be بفرست.')
        return
    keys = [[InlineKeyboardButton(f'تا {q}p', callback_data=f'{vid}:{q}') for q in ('360', '720', '1080')],
            [InlineKeyboardButton('فقط صدا • MP3', callback_data=f'{vid}:audio')]]
    await update.message.reply_text('خروجی را انتخاب کن؛ کیفیت نهایی به نسخه‌های موجود بستگی دارد:', reply_markup=InlineKeyboardMarkup(keys))


async def choose(update, context):
    if not await permitted(update):
        return
    query = update.callback_query
    await query.answer()
    if not re.fullmatch(r'[A-Za-z0-9_-]{11}:(360|720|1080|audio)', query.data or ''):
        return
    uid = update.effective_user.id
    if uid in BUSY:
        await query.message.reply_text('یک درخواست شما هنوز در صف یا در حال پردازش است.')
        return
    if QUEUE.full():
        await query.message.reply_text('صف پر است؛ کمی بعد دوباره امتحان کن.')
        return
    # Reserve before awaiting network I/O to prevent duplicate concurrent requests.
    BUSY.add(uid)
    try:
        status = await query.message.reply_text('در صف دانلود…')
        QUEUE.put_nowait((uid, update.effective_chat.id, query.data, status.message_id))
    except Exception:
        BUSY.discard(uid)
        raise


async def run_process(args, timeout, folder=None):
    proc = await asyncio.create_subprocess_exec(
        *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        start_new_session=(os.name != 'nt'))
    async def monitor():
        while True:
            await asyncio.sleep(1)
            if folder and sum(p.stat().st_size for p in folder.glob('*') if p.is_file()) > 150_000_000:
                raise ValueError('فایل‌های موقت بیش از حد بزرگ شدند؛ کیفیت پایین‌تر را انتخاب کن.')
    watcher = asyncio.create_task(monitor())
    reader = asyncio.create_task(proc.communicate())
    try:
        done, _ = await asyncio.wait({reader, watcher}, timeout=timeout, return_when=asyncio.FIRST_COMPLETED)
        if watcher in done:
            watcher.result()
        if reader not in done:
            raise ValueError('زمان پردازش تمام شد؛ بعداً یا با کیفیت پایین‌تر امتحان کن.')
        out, err = reader.result()
        if proc.returncode:
            # Do not expose URLs, cookies, or raw downstream errors to chat/logs.
            raise ValueError('دانلود انجام نشد؛ ویدئو ممکن است محدود باشد یا یوتیوب دسترسی سرور را مسدود کرده باشد. کیفیت دیگری را هم امتحان کن.')
        return out.decode('utf-8')
    finally:
        watcher.cancel()
        if proc.returncode is None:
            if os.name == 'nt':
                killer = await asyncio.create_subprocess_exec('taskkill', '/PID', str(proc.pid), '/T', '/F', stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
                await killer.wait()
            else:
                try:
                    os.killpg(proc.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            await proc.wait()
        await asyncio.gather(reader, watcher, return_exceptions=True)


def base_args():
    return [sys.executable, '-m', 'yt_dlp', '--ignore-config', '--no-playlist', '--no-progress',
            '--quiet', '--no-warnings', '--socket-timeout', '20', '--retries', '2',
            '--extractor-retries', '2', '--js-runtimes', 'node', '--js-runtimes', 'deno']


async def send(bot, chat, kind, media, title):
    kwargs = dict(chat_id=chat, caption=title[:900], read_timeout=120, write_timeout=180, connect_timeout=30)
    if kind == 'audio':
        return (await bot.send_audio(audio=media, **kwargs)).audio.file_id
    return (await bot.send_video(video=media, supports_streaming=True, **kwargs)).video.file_id


async def process(app, chat, key, status_id):
    vid, kind = key.split(':')
    async def status(text):
        await app.bot.edit_message_text(chat_id=chat, message_id=status_id, text=text)
    row = DB.execute('SELECT file_id, title FROM cache WHERE key=?', (key,)).fetchone()
    if row:
        try:
            await send(app.bot, chat, kind, row[0], row[1])
            await status('ارسال شد ✅')
            return
        except BadRequest:
            DB.execute('DELETE FROM cache WHERE key=?', (key,))
            DB.commit()
    await status('در حال بررسی ویدئو…')
    url = f'https://www.youtube.com/watch?v={vid}'
    info = json.loads(await run_process(base_args() + ['--dump-single-json', '--skip-download', url], 90))
    duration = info.get('duration')
    if info.get('is_live') or info.get('live_status') == 'is_upcoming' or not duration or duration > MAX_DURATION:
        raise ValueError('فقط ویدئوهای غیرزنده با مدت مشخص و حداکثر ۲۰ دقیقه پشتیبانی می‌شوند.')
    title = info.get('title') or vid
    await status('در حال دانلود و آماده‌سازی فایل…')
    with tempfile.TemporaryDirectory(prefix='job-', dir=DATA) as tmp:
        folder = Path(tmp)
        args = base_args() + ['--max-filesize', str(MAX_BYTES), '-o', str(folder / 'media.%(ext)s')]
        if kind == 'audio':
            args += ['-f', 'bestaudio/best', '-x', '--audio-format', 'mp3', '--audio-quality', '128K']
        else:
            args += ['-f', f'bv[height<={kind}][ext=mp4][vcodec^=avc1]+ba[ext=m4a]/b[height<={kind}][ext=mp4]', '--merge-output-format', 'mp4', '--postprocessor-args', 'ffmpeg:-movflags +faststart']
        await run_process(args + [url], 600, folder)
        target = folder / ('media.mp3' if kind == 'audio' else 'media.mp4')
        files = [target] if target.is_file() else []
        if len(files) != 1 or not (0 < files[0].stat().st_size <= MAX_BYTES):
            raise ValueError('فایل بیش از ۴۹ مگابایت است یا آماده نشد؛ کیفیت پایین‌تر یا ویدئوی کوتاه‌تر را انتخاب کن.')
        await status('در حال ارسال به تلگرام…')
        with files[0].open('rb') as stream:
            fid = await send(app.bot, chat, kind, stream, title)
        DB.execute('INSERT OR REPLACE INTO cache VALUES (?, ?, ?)', (key, fid, title))
        DB.commit()
    await status('ارسال شد ✅')


async def worker(app):
    while True:
        uid, chat, key, status_id = await QUEUE.get()
        try:
            await process(app, chat, key, status_id)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            LOG.warning('Job failed: %s', type(exc).__name__)
            message = str(exc) if isinstance(exc, ValueError) else 'خطای ارتباط یا پردازش رخ داد؛ دوباره امتحان کن.'
            try:
                await app.bot.send_message(chat, message)
            except Exception:
                pass
        finally:
            BUSY.discard(uid)
            QUEUE.task_done()


async def init(app):
    print(f'Connected: @{app.bot.username} | Open Telegram and send /start', flush=True)
    global DB
    DATA.mkdir(parents=True, exist_ok=True)
    DB = sqlite3.connect(DATA / f'cache-{app.bot.id}.sqlite3')
    DB.execute('CREATE TABLE IF NOT EXISTS cache (key TEXT PRIMARY KEY, file_id TEXT NOT NULL, title TEXT NOT NULL)')
    DB.commit()
    app.bot_data['worker'] = asyncio.create_task(worker(app))


async def stop(app):
    app.bot_data['worker'].cancel()
    await asyncio.gather(app.bot_data['worker'], return_exceptions=True)
    DB.close()


async def error(update, context):
    LOG.warning('Handler failed: %s', type(context.error).__name__)


if __name__ == '__main__':
    import shutil
    if not TOKEN or TOKEN == 'PASTE_BOT_TOKEN_HERE':
        raise SystemExit('Set BOT_TOKEN in .env first.')
    if not shutil.which('ffmpeg') or not shutil.which('ffprobe'):
        raise SystemExit('Install FFmpeg (including ffprobe) and add it to PATH.')
    if not (shutil.which('node') or shutil.which('deno')):
        raise SystemExit('Install a supported Node.js (22+) or Deno runtime.')
    logging.basicConfig(level=logging.WARNING)
    logging.getLogger('httpx').setLevel(logging.ERROR)
    app = Application.builder().token(TOKEN).post_init(init).post_stop(stop).build()
    app.add_handler(CommandHandler(['start', 'help'], start))
    app.add_handler(CallbackQueryHandler(choose))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, link))
    app.add_error_handler(error)
    app.run_polling(allowed_updates=['message', 'callback_query'], drop_pending_updates=True)
