#!/usr/bin/env python3
"""Obsidian Schedule Bot - Telegram bot for managing Obsidian Tasks"""

import os
import re
import logging
from datetime import datetime, timedelta, date as date_type
from pathlib import Path
from dataclasses import dataclass
from typing import Optional

import yaml
import git
from dotenv import load_dotenv
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes

load_dotenv()

# Static Configuration (from .env)
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = int(os.getenv("TELEGRAM_CHAT_ID", "0"))
OBSIDIAN_PATH = Path(os.getenv("OBSIDIAN_PATH", "./obsidian"))
TODO_PATH = Path(os.getenv("TODO_LISTS_PATH", "./obsidian/Todo Lists"))
CONFIG_PATH = Path(os.getenv("CONFIG_PATH", "./config.yml"))

# Dynamic Configuration (from config.yml)
def load_config() -> dict:
    """Load configuration from config.yml"""
    default = {
        "notification_times": ["09:00", "12:00", "15:00", "18:00", "21:00", "00:00"],
        "timezone": "Asia/Seoul",
        "test_mode": False,
    }
    if not CONFIG_PATH.exists():
        save_config(default)
        return default
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or default
    except Exception:
        return default


def save_config(config: dict) -> None:
    """Save configuration to config.yml"""
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        yaml.dump(config, f, default_flow_style=False, allow_unicode=True)


def get_notification_times() -> list[tuple[int, int]]:
    """Parse notification times from config"""
    config = load_config()
    times = []
    for t in config.get("notification_times", []):
        if ":" in t:
            h, m = t.split(":")
            times.append((int(h), int(m)))
    return times


def get_timezone() -> str:
    return load_config().get("timezone", "Asia/Seoul")


def is_test_mode() -> bool:
    return load_config().get("test_mode", False)

logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)


@dataclass
class Task:
    text: str
    completed: bool
    source: str
    due: Optional[datetime] = None
    scheduled: Optional[datetime] = None
    start: Optional[datetime] = None
    recurrence: Optional[str] = None
    time_range: Optional[str] = None  # e.g., "14:00-16:00"
    place: Optional[str] = None       # e.g., "E3-1 3444"

    @property
    def primary_dt(self) -> Optional[datetime]:
        return self.due or self.scheduled or self.start

    @property
    def has_time(self) -> bool:
        # Has time if time_range exists OR if primary_dt has non-zero time
        if self.time_range:
            return True
        dt = self.primary_dt
        return dt is not None and (dt.hour != 0 or dt.minute != 0)
    
    @property
    def display_time(self) -> Optional[str]:
        """Get display time: prefer time_range, fallback to primary_dt time"""
        if self.time_range:
            return self.time_range
        dt = self.primary_dt
        if dt and (dt.hour != 0 or dt.minute != 0):
            return dt.strftime('%H:%M')
        return None

    def sort_key(self) -> tuple:
        # Sort by time_range first if exists, then by primary_dt
        if self.time_range:
            # Extract start time from range (e.g., "14:00-16:00" -> "14:00")
            start_time = self.time_range.split('-')[0]
            try:
                h, m = map(int, start_time.split(':'))
                return (0, datetime.min.replace(hour=h, minute=m))
            except:
                pass
        dt = self.primary_dt
        if dt is None:
            return (2, datetime.max)
        return (0 if self.has_time else 1, dt)


# Git Operations
def pull_repo() -> tuple[bool, str]:
    try:
        repo = git.Repo(OBSIDIAN_PATH)
        
        # Check for GitHub token (for Docker/portable usage)
        github_token = os.getenv("GITHUB_TOKEN")
        github_repo = os.getenv("GITHUB_REPO")
        
        if github_token and github_repo:
            # Use HTTPS with token for authentication
            # Format: https://TOKEN@github.com/user/repo.git
            auth_url = github_repo.replace("https://", f"https://{github_token}@")
            # Fetch and pull using authenticated URL
            repo.git.fetch(auth_url, "main")
            repo.git.reset("--hard", "FETCH_HEAD")
            return True, "Synced"
        else:
            # Fallback to default remote (SSH or existing config)
            if not repo.remotes:
                logger.warning("No remotes configured")
                return False, "No remotes"
            origin = repo.remotes.origin if hasattr(repo.remotes, 'origin') else repo.remotes[0]
            origin.pull()
            return True, "Synced"
    except git.InvalidGitRepositoryError:
        logger.warning(f"{OBSIDIAN_PATH} is not a git repository")
        return False, "Not a git repo"
    except Exception as e:
        logger.error(f"Git pull failed: {e}")
        return False, "Sync failed"


# Task Parsing
def parse_datetime(s: str) -> Optional[datetime]:
    for fmt in ["%Y-%m-%d %H:%M", "%Y-%m-%d"]:
        try:
            return datetime.strptime(s.strip(), fmt)
        except ValueError:
            continue
    return None


TASK_PATTERN = re.compile(r"^\s*-\s*\[([ xX])\]\s*(.+)$")
METADATA_PATTERN = re.compile(r"\[(?:due|scheduled|start|completion|recurs|repeat|created)::\s*[^\]]*\]")
DATE_PATTERNS = {
    "due": re.compile(r"\[due::\s*(\d{4}-\d{2}-\d{2}(?:\s+\d{1,2}:\d{2})?)\]"),
    "scheduled": re.compile(r"\[scheduled::\s*(\d{4}-\d{2}-\d{2}(?:\s+\d{1,2}:\d{2})?)\]"),
    "start": re.compile(r"\[start::\s*(\d{4}-\d{2}-\d{2}(?:\s+\d{1,2}:\d{2})?)\]"),
}
RECUR_PATTERN = re.compile(r"\[(?:recurs|repeat)::\s*([^\]]+)\]|🔁\s*([^\[]+)")# Pattern for @[time]/[place] format
# Matches: @[14:00-16:00]/[E3-1 3444], @/[place], @[time], or nothing
TIME_PLACE_PATTERN = re.compile(r"@(?:\[([^\]]+)\])?(?:/\[([^\]]+)\])?\s*")

def parse_task(line: str, source: str) -> Optional[Task]:
    match = TASK_PATTERN.match(line)
    if not match:
        return None

    completed = match.group(1).lower() == "x"
    content = match.group(2)
    
    # Parse @[time]/[place] format
    time_range = None
    place = None
    tp_match = TIME_PLACE_PATTERN.search(content)
    if tp_match and (tp_match.group(1) or tp_match.group(2)):
        time_range = tp_match.group(1)  # e.g., "14:00-16:00" or None
        place = tp_match.group(2)        # e.g., "E3-1 3444" or None
        # Remove the @[time]/[place] part from text
        content_for_text = TIME_PLACE_PATTERN.sub("", content)
    else:
        content_for_text = content
    
    text = METADATA_PATTERN.sub("", content_for_text)
    text = re.sub(r"🔁\s*[^\[]*", "", text).strip()

    if not text:
        return None

    dates = {k: parse_datetime(m.group(1)) if (m := p.search(content)) else None for k, p in DATE_PATTERNS.items()}
    recur_match = RECUR_PATTERN.search(content)
    recurrence = (recur_match.group(1) or recur_match.group(2)).strip() if recur_match else None

    return Task(text=text, completed=completed, source=source, recurrence=recurrence, 
                time_range=time_range, place=place, **dates)


def get_all_tasks() -> list[Task]:
    tasks = []
    if not TODO_PATH.exists():
        return tasks

    for f in TODO_PATH.glob("*.md"):
        try:
            for line in f.read_text(encoding="utf-8").splitlines():
                if task := parse_task(line, f.stem):
                    tasks.append(task)
        except Exception as e:
            logger.error(f"Error parsing {f}: {e}")
    return tasks


# Filtering
def today() -> datetime:
    return datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)


def filter_tasks(tasks: list[Task], *, 
                 include_completed: bool = False,
                 date_filter: Optional[tuple[datetime, datetime]] = None,
                 field: str = "due",
                 overdue: bool = False) -> list[Task]:
    result = []
    td = today()
    for t in tasks:
        if not include_completed and t.completed:
            continue
        dt = getattr(t, field, None)
        if dt is None:
            continue
        if overdue and dt >= td:
            continue
        if date_filter and not (date_filter[0] <= dt < date_filter[1]):
            continue
        result.append(t)
    return result


def get_today_tasks(tasks: list[Task], include_completed: bool = False) -> list[Task]:
    start, end = today(), today() + timedelta(days=1)
    seen, result = set(), []
    
    for field in ["due", "scheduled", "start"]:
        for t in filter_tasks(tasks, include_completed=include_completed, date_filter=(start, end), field=field):
            key = (t.text, t.source)
            if key not in seen:
                seen.add(key)
                result.append(t)
    return result


def get_week_tasks(tasks: list[Task], include_completed: bool = False) -> list[Task]:
    # Monday to Sunday of current week
    td = today()
    week_start = td - timedelta(days=td.weekday())  # Monday
    week_end = week_start + timedelta(days=7)  # Next Monday
    seen, result = set(), []
    
    for field in ["due", "scheduled"]:
        for t in filter_tasks(tasks, include_completed=include_completed, date_filter=(week_start, week_end), field=field):
            key = (t.text, t.source)
            if key not in seen:
                seen.add(key)
                result.append(t)
    return result


def get_overdue(tasks: list[Task]) -> list[Task]:
    seen, result = set(), []
    for field in ["due", "scheduled"]:
        for t in filter_tasks(tasks, overdue=True, field=field):
            key = (t.text, t.source)
            if key not in seen:
                seen.add(key)
                result.append(t)
    return result


def get_incomplete(tasks: list[Task]) -> list[Task]:
    return [t for t in tasks if not t.completed]


# Formatting (HTML mode)
def esc(text: str) -> str:
    """Escape HTML special characters"""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def fmt_task(t: Task, show_time: bool = True, show_date: bool = False, show_source: bool = False) -> str:
    """
    Format task with blockquote (HTML)
    Line 1: <code>time</code> · place · source
    Line 2: <blockquote>task name</blockquote>
    """
    recur = " (repeat)" if t.recurrence else ""
    
    # Build info parts: time/date, place, source
    parts = []
    
    if show_time and t.display_time:
        parts.append(f"<code>{t.display_time}</code>")
    elif show_date and t.primary_dt:
        parts.append(f"<code>{t.primary_dt.strftime('%m/%d')}</code>")
    elif show_time:
        parts.append("<code>all-day</code>")
    
    if t.place:
        parts.append(esc(t.place))
    
    if show_source:
        parts.append(esc(t.source))
    
    # First line: time · place · source
    info_line = " · ".join(parts) if parts else ""
    
    # Task text in blockquote
    text = f"{esc(t.text)}{recur}"
    
    if t.completed:
        return f"<s>{info_line}</s>\n<blockquote><s>{text}</s></blockquote>"
    
    return f"{info_line}\n<blockquote>{text}</blockquote>"


def fmt_tasks(tasks: list[Task], show_time: bool = True, show_date: bool = False, show_source: bool = False) -> str:
    if not tasks:
        return "<i>none</i>"
    
    sorted_tasks = sorted(tasks, key=Task.sort_key)
    lines = []
    
    for t in sorted_tasks:
        lines.append(fmt_task(t, show_time=show_time, show_date=show_date, show_source=show_source))
    
    return "\n".join(lines)


def fmt_overdue(tasks: list[Task]) -> str:
    """Format overdue tasks with blockquote (HTML)"""
    if not tasks:
        return "<i>none</i>"
    
    # Group by source, then by date
    by_source: dict[str, dict[Optional[date_type], list[Task]]] = {}
    for t in tasks:
        if t.source not in by_source:
            by_source[t.source] = {}
        dt = t.primary_dt
        date_key = dt.date() if dt else None
        by_source[t.source].setdefault(date_key, []).append(t)
    
    lines = []
    for src in sorted(by_source):
        src_tasks = by_source[src]
        lines.append(f"<b>{esc(src)}</b>")
        
        sorted_dates = sorted(
            src_tasks.keys(),
            key=lambda d: (d is None, d or date_type.max)
        )
        
        for d in sorted_dates:
            date_tasks = src_tasks[d]
            date_tasks_sorted = sorted(date_tasks, key=lambda t: t.primary_dt or datetime.max)
            
            for t in date_tasks_sorted:
                time_str = t.display_time or "all-day"
                date_str = d.strftime('%m/%d') if d else "no date"
                recur = " (repeat)" if t.recurrence else ""
                
                parts = [f"<code>{date_str}</code>", f"<code>{time_str}</code>"]
                if t.place:
                    parts.append(esc(t.place))
                
                lines.append(" · ".join(parts))
                lines.append(f"<blockquote>{esc(t.text)}{recur}</blockquote>")
    
    return "\n".join(lines)


def build_daily(tasks: list[Task], include_completed: bool = False) -> str:
    now = datetime.now()
    overdue = get_overdue(tasks)
    today_tasks = get_today_tasks(tasks, include_completed)

    lines = [f"<b>{today().strftime('%Y.%m.%d')}</b> | {now.strftime('%H:%M')}\n"]

    if overdue:
        lines += [f"<b>Overdue</b> ({len(overdue)})", fmt_overdue(overdue), ""]

    header = f"<b>Today</b> ({len(today_tasks)})" if today_tasks else "<b>Today</b>"
    lines += [header, fmt_tasks(today_tasks, show_time=True, show_source=True)]
    return "\n".join(lines)


def build_weekly(tasks: list[Task], include_completed: bool = False) -> str:
    td = today()
    # Week: Mon to Sun
    week_start = td - timedelta(days=td.weekday())  # Monday
    week_end = week_start + timedelta(days=6)  # Sunday
    
    week_tasks = get_week_tasks(tasks, include_completed)

    by_date: dict[date_type, list[Task]] = {}
    for t in week_tasks:
        dt = t.primary_dt
        if dt:
            key = dt.date() if isinstance(dt, datetime) else dt
            by_date.setdefault(key, []).append(t)

    lines = [f"<b>This Week</b>", f"{week_start.strftime('%m/%d')} - {week_end.strftime('%m/%d')}\n"]

    days = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    for i in range(7):
        d = (week_start + timedelta(days=i)).date()
        marker = " (today)" if d == td.date() else ""
        header = f"<b>{d.strftime('%m/%d')} {days[i]}</b>{marker}"
        lines.append(header)
        
        if d in by_date:
            for t in sorted(by_date[d], key=Task.sort_key):
                lines.append(f"  {fmt_task(t, show_time=True, show_source=True)}")
        else:
            lines.append("  -")
        lines.append("")

    return "\n".join(lines)


def build_all(tasks: list[Task]) -> str:
    incomplete = get_incomplete(tasks)
    
    # Group by source, then by date
    by_source: dict[str, dict[Optional[date_type], list[Task]]] = {}
    for t in incomplete:
        if t.source not in by_source:
            by_source[t.source] = {}
        dt = t.primary_dt
        date_key = dt.date() if dt else None
        by_source[t.source].setdefault(date_key, []).append(t)

    lines = [f"<b>All Incomplete</b>", f"total {len(incomplete)}\n"]

    if not incomplete:
        lines.append("<i>all done</i>")
    else:
        for src in sorted(by_source):
            src_tasks = by_source[src]
            total = sum(len(v) for v in src_tasks.values())
            lines.append(f"<b>{esc(src)}</b> ({total})")
            
            sorted_dates = sorted(
                src_tasks.keys(),
                key=lambda d: (d is None, d or date_type.max)
            )
            
            for d in sorted_dates:
                date_tasks = src_tasks[d]
                date_tasks_sorted = sorted(date_tasks, key=Task.sort_key)
                
                for t in date_tasks_sorted:
                    time_str = t.display_time or "all-day"
                    date_str = d.strftime('%m/%d') if d else "no date"
                    recur = " (repeat)" if t.recurrence else ""
                    
                    parts = [f"<code>{date_str}</code>", f"<code>{time_str}</code>"]
                    if t.place:
                        parts.append(esc(t.place))
                    
                    lines.append(" · ".join(parts))
                    lines.append(f"<blockquote>{esc(t.text)}{recur}</blockquote>")
            lines.append("")

    return "\n".join(lines)


# Telegram Handlers
KEYBOARD = InlineKeyboardMarkup([
    [InlineKeyboardButton("Refresh", callback_data="refresh")],
    [InlineKeyboardButton("Today (all)", callback_data="today_all"),
     InlineKeyboardButton("Week (all)", callback_data="week_all")],
    [InlineKeyboardButton("This Week", callback_data="weekly"),
     InlineKeyboardButton("Incomplete", callback_data="all")],
    [InlineKeyboardButton("Settings", callback_data="settings")],
])

SETTINGS_KEYBOARD = InlineKeyboardMarkup([
    [InlineKeyboardButton("Toggle Test Mode", callback_data="toggle_test")],
    [InlineKeyboardButton("Add Time", callback_data="add_time"),
     InlineKeyboardButton("Remove Time", callback_data="remove_time")],
    [InlineKeyboardButton("Back", callback_data="refresh")],
])


async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "<b>Obsidian Schedule Bot</b>\n\n"
        "Automatic notifications at scheduled times.\n"
        "Use buttons below to check your schedule.",
        parse_mode="HTML",
        reply_markup=KEYBOARD,
    )


async def cmd_help(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "<b>Commands</b>\n\n"
        "/start - start bot\n"
        "/today - today's schedule\n"
        "/week - this week\n"
        "/all - all incomplete\n"
        "/settings - bot settings\n"
        "/sync - sync repo\n"
        "/help - help",
        parse_mode="HTML",
    )


async def cmd_today(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    pull_repo()
    await update.message.reply_text(build_daily(get_all_tasks()), parse_mode="HTML", reply_markup=KEYBOARD)


async def cmd_week(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    pull_repo()
    await update.message.reply_text(build_weekly(get_all_tasks()), parse_mode="HTML", reply_markup=KEYBOARD)


async def cmd_all(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    pull_repo()
    await update.message.reply_text(build_all(get_all_tasks()), parse_mode="HTML", reply_markup=KEYBOARD)


async def cmd_sync(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    _, msg = pull_repo()
    await update.message.reply_text(msg)


CALLBACKS = {
    "refresh": lambda t: build_daily(t, False),
    "today_all": lambda t: build_daily(t, True),
    "week_all": lambda t: build_weekly(t, True),
    "weekly": lambda t: build_weekly(t, False),
    "all": lambda t: build_all(t),
}

# Global scheduler reference for restart
scheduler: Optional[AsyncIOScheduler] = None
app_ref: Optional[Application] = None


def build_settings() -> str:
    """Build settings view"""
    config = load_config()
    times = config.get("notification_times", [])
    tz = config.get("timezone", "Asia/Seoul")
    test = config.get("test_mode", False)
    
    lines = [
        "<b>Settings</b>\n",
        f"<b>Timezone:</b> {tz}",
        f"<b>Test Mode:</b> {'ON' if test else 'OFF'}",
        "",
        "<b>Notification Times:</b>",
    ]
    for t in sorted(times):
        lines.append(f"  {t}")
    if not times:
        lines.append("  (none)")
    
    return "\n".join(lines)


def restart_scheduler():
    """Restart scheduler with new config"""
    global scheduler
    if scheduler and app_ref:
        scheduler.shutdown(wait=False)
        scheduler = setup_scheduler(app_ref)
        scheduler.start()
        logger.info("Scheduler restarted with new config")


async def on_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    data = query.data
    chat_id = query.message.chat_id
    
    # Settings callbacks
    if data == "settings":
        await ctx.bot.send_message(chat_id=chat_id, text=build_settings(), parse_mode="HTML", reply_markup=SETTINGS_KEYBOARD)
        return
    
    if data == "toggle_test":
        config = load_config()
        config["test_mode"] = not config.get("test_mode", False)
        save_config(config)
        restart_scheduler()
        await ctx.bot.send_message(chat_id=chat_id, text=build_settings(), parse_mode="HTML", reply_markup=SETTINGS_KEYBOARD)
        return
    
    if data == "add_time":
        await ctx.bot.send_message(
            chat_id=chat_id,
            text="Send time to add (HH:MM format):\ne.g. <code>14:30</code>",
            parse_mode="HTML"
        )
        ctx.user_data["awaiting"] = "add_time"
        return
    
    if data == "remove_time":
        config = load_config()
        times = config.get("notification_times", [])
        if not times:
            await ctx.bot.send_message(chat_id=chat_id, text="No times to remove.", reply_markup=SETTINGS_KEYBOARD)
            return
        
        # Create keyboard with times to remove
        buttons = [[InlineKeyboardButton(t, callback_data=f"rm_{t}")] for t in sorted(times)]
        buttons.append([InlineKeyboardButton("Cancel", callback_data="settings")])
        await ctx.bot.send_message(
            chat_id=chat_id,
            text="Select time to remove:",
            reply_markup=InlineKeyboardMarkup(buttons)
        )
        return
    
    if data.startswith("rm_"):
        time_to_remove = data[3:]
        config = load_config()
        times = config.get("notification_times", [])
        if time_to_remove in times:
            times.remove(time_to_remove)
            config["notification_times"] = times
            save_config(config)
            restart_scheduler()
        await ctx.bot.send_message(chat_id=chat_id, text=build_settings(), parse_mode="HTML", reply_markup=SETTINGS_KEYBOARD)
        return
    
    # Default callbacks
    pull_repo()
    tasks = get_all_tasks()
    text = CALLBACKS.get(data, lambda _: "알 수 없는 명령")(tasks)
    await ctx.bot.send_message(chat_id=chat_id, text=text, parse_mode="HTML", reply_markup=KEYBOARD)


# Scheduler
async def send_notification(app: Application):
    logger.info("Sending scheduled notification...")
    pull_repo()
    try:
        await app.bot.send_message(chat_id=CHAT_ID, text=build_daily(get_all_tasks()), parse_mode="HTML", reply_markup=KEYBOARD)
        logger.info("Notification sent")
    except Exception as e:
        logger.error(f"Failed to send: {e}")


def setup_scheduler(app: Application) -> AsyncIOScheduler:
    tz = get_timezone()
    sched = AsyncIOScheduler(timezone=tz)

    if is_test_mode():
        sched.add_job(send_notification, IntervalTrigger(minutes=1), args=[app], id="test")
        logger.info("TEST MODE: notification every 1 minute")
    else:
        for hour, minute in get_notification_times():
            sched.add_job(
                send_notification,
                CronTrigger(hour=hour, minute=minute, timezone=tz),
                args=[app],
                id=f"notif_{hour}_{minute}",
            )
            logger.info(f"Scheduled: {hour:02d}:{minute:02d}")

    return sched


async def handle_message(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Handle text messages for settings input"""
    if ctx.user_data.get("awaiting") == "add_time":
        ctx.user_data["awaiting"] = None
        text = update.message.text.strip()
        
        # Validate time format
        import re
        if not re.match(r"^\d{1,2}:\d{2}$", text):
            await update.message.reply_text("Invalid format. Use HH:MM (e.g. 14:30)")
            return
        
        try:
            h, m = text.split(":")
            h, m = int(h), int(m)
            if not (0 <= h <= 23 and 0 <= m <= 59):
                raise ValueError()
            time_str = f"{h:02d}:{m:02d}"
        except:
            await update.message.reply_text("Invalid time. Use HH:MM (e.g. 14:30)")
            return
        
        config = load_config()
        times = config.get("notification_times", [])
        if time_str not in times:
            times.append(time_str)
            times.sort()
            config["notification_times"] = times
            save_config(config)
            restart_scheduler()
        
        await update.message.reply_text(build_settings(), parse_mode="HTML", reply_markup=SETTINGS_KEYBOARD)
        return


async def cmd_settings(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(build_settings(), parse_mode="HTML", reply_markup=SETTINGS_KEYBOARD)


def main():
    global scheduler, app_ref
    
    if not BOT_TOKEN or not CHAT_ID:
        logger.error("Missing TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID")
        return

    logger.info(f"Starting bot... (test_mode={is_test_mode()})")

    app = Application.builder().token(BOT_TOKEN).build()
    app_ref = app
    
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("today", cmd_today))
    app.add_handler(CommandHandler("week", cmd_week))
    app.add_handler(CommandHandler("all", cmd_all))
    app.add_handler(CommandHandler("settings", cmd_settings))
    app.add_handler(CommandHandler("sync", cmd_sync))
    app.add_handler(CallbackQueryHandler(on_callback))
    
    # Message handler for settings input (must be last)
    from telegram.ext import MessageHandler, filters
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    scheduler = setup_scheduler(app)
    scheduler.start()

    logger.info("Bot running...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
