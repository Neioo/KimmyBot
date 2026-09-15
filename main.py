import asyncio
import logging
import os
import random
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import discord
from aiohttp import web
from discord.ext import commands, tasks
from dotenv import load_dotenv
from psycopg import connect
from psycopg.rows import dict_row


# =========================================================
# CONFIG
# =========================================================

load_dotenv()

TOKEN = os.getenv("DISCORD_TOKEN")

if not TOKEN:
    raise RuntimeError("DISCORD_TOKEN environment variable is not set.")

TIMEZONE = ZoneInfo("Asia/Manila")
DATABASE_URL = os.getenv("DATABASE_URL")

if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL environment variable is not set.")


# =========================================================
# LOGGING
# =========================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)

logger = logging.getLogger("kimmy")


# =========================================================
# DISCORD
# =========================================================

intents = discord.Intents.default()

intents.message_content = True
intents.guild_scheduled_events = True
intents.guild_polls = True
intents.guild_messages = True
intents.members = True

bot = commands.Bot(
    command_prefix="!k ",
    intents=intents,
    help_command=None,
)


# =========================================================
# DATABASE
# =========================================================

def get_db():
    return connect(DATABASE_URL, row_factory=dict_row)


def init_database():
    connection = get_db()

    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS reminders (
            id BIGSERIAL PRIMARY KEY,
            type TEXT NOT NULL,
            channel_id BIGINT NOT NULL,
            message TEXT NOT NULL,

            reminder_datetime TEXT,

            day_of_month INTEGER,
            hour INTEGER,
            minute INTEGER,

            last_triggered TEXT
        )
        """
    )

    connection.commit()
    connection.close()

    logger.info("Database initialized.")


def create_reminder(
    reminder_type,
    channel_id,
    message,
    reminder_datetime=None,
    day_of_month=None,
    hour=None,
    minute=None
):
    connection = get_db()

    cursor = connection.execute(
        """
        INSERT INTO reminders (
            type,
            channel_id,
            message,
            reminder_datetime,
            day_of_month,
            hour,
            minute,
            last_triggered
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        RETURNING id
        """,
        (
            reminder_type,
            channel_id,
            message,
            reminder_datetime,
            day_of_month,
            hour,
            minute,
            None
        )
    )

    reminder_id = cursor.fetchone()["id"]

    connection.commit()
    connection.close()

    return reminder_id


def get_reminder(reminder_id):
    connection = get_db()

    reminder = connection.execute(
        """
        SELECT *
        FROM reminders
        WHERE id = %s
        """,
        (reminder_id,)
    ).fetchone()

    connection.close()

    return reminder


def get_all_reminders():
    connection = get_db()

    reminders = connection.execute(
        """
        SELECT *
        FROM reminders
        ORDER BY id
        """
    ).fetchall()

    connection.close()

    return reminders


def delete_reminder(reminder_id):
    connection = get_db()

    cursor = connection.execute(
        """
        DELETE FROM reminders
        WHERE id = %s
        """,
        (reminder_id,)
    )

    deleted = cursor.rowcount > 0

    connection.commit()
    connection.close()

    return deleted


def mark_monthly_triggered(reminder_id, trigger_date):
    connection = get_db()

    connection.execute(
        """
        UPDATE reminders
        SET last_triggered = %s
        WHERE id = %s
        """,
        (
            trigger_date,
            reminder_id
        )
    )

    connection.commit()
    connection.close()


def delete_expired_once_reminder(reminder_id):
    delete_reminder(reminder_id)


# =========================================================
# TIME HELPERS
# =========================================================

def now():
    """
    Current time in Philippine time.
    """
    return datetime.now(TIMEZONE)


def parse_time(time_string):
    """
    Parse HH:MM.
    """

    try:
        return datetime.strptime(
            time_string,
            "%H:%M"
        ).time()

    except ValueError:
        raise ValueError(
            "Invalid time format. Use `HH:MM`, "
            "for example `18:30`."
        )


def parse_full_datetime(date_string, time_string):
    """
    Parse YYYY-MM-DD HH:MM.
    """

    try:
        naive_datetime = datetime.strptime(
            f"{date_string} {time_string}",
            "%Y-%m-%d %H:%M"
        )

        return naive_datetime.replace(
            tzinfo=TIMEZONE
        )

    except ValueError:
        raise ValueError(
            "Invalid date/time. Use "
            "`YYYY-MM-DD HH:MM`, "
            "for example `2026-09-20 18:30`."
        )


# =========================================================
# REMINDER ID FORMAT
# =========================================================

def format_reminder_id(reminder):
    """
    O1 = one-time reminder
    M2 = monthly reminder
    """

    prefix = (
        "O"
        if reminder["type"] == "once"
        else "M"
    )

    return f"{prefix}{reminder['id']}"


def parse_reminder_id(reminder_id):
    """
    Convert O12 / M12 into the database ID 12.
    """

    reminder_id = reminder_id.upper().strip()

    if len(reminder_id) < 2:
        return None

    prefix = reminder_id[0]

    if prefix not in ("O", "M"):
        return None

    try:
        return int(reminder_id[1:])

    except ValueError:
        return None


# =========================================================
# DISCORD EVENTS
# =========================================================

@bot.event
async def on_ready():
    logger.info(
        "%s is ready to serve!",
        bot.user
    )

    if not monthly_check_loop.is_running():
        monthly_check_loop.start()

    await restore_once_reminders()


@bot.event
async def on_member_join(member):
    try:
        await member.send(
            f"Hi {member.name}, hope you have fun here! 💋"
        )

    except discord.Forbidden:
        logger.info(
            "Could not send DM to %s (DMs disabled).",
            member.name
        )


@bot.event
async def on_message(message):
    if message.author == bot.user:
        return

    if (
        "nigga" in message.content.lower()
        and message.author.name.lower() == "kappann"
    ):
        await message.channel.send(
            f"Hey {message.author.name}, don't say that word!"
        )

    await bot.process_commands(message)


# =========================================================
# BASIC COMMANDS
# =========================================================

@bot.command(name="help")
async def help_command(ctx):
    """Show Kimmy's available commands and examples."""
    await ctx.send(
        "**Kimmy commands**\n"
        "Use `!k ` before each command.\n\n"
        "`!k hello` — Check that Kimmy is online.\n"
        "`!k whatgame2play valheim lol cod` — Pick a game randomly.\n\n"
        "**One-time reminders**\n"
        "`!k remind_once 18:30 Take the chicken out`\n"
        "`!k remind_once 2026-09-20 18:30 Birthday dinner`\n\n"
        "**Monthly reminders**\n"
        "`!k remind_monthly 15 09:00 Pay the bills`\n"
        "`!k remind_monthly 15 -- Pay the bills`\n\n"
        "`!k reminders` — List active reminders.\n"
        "`!k remove_reminder O1` — Remove a one-time reminder.\n"
        "`!k remove_reminder M2` — Remove a monthly reminder.\n\n"
        "Times use Philippine time (Asia/Manila)."
    )


@bot.command()
async def hello(ctx):
    await ctx.send(
        "Hello, I'm Kimmy! How can I help you?"
    )


@bot.command()
async def whatgame2play(ctx, *games: str):
    """
    Usage:
    !k whatgame2play valheim lol cod
    """

    if not games:
        await ctx.send(
            "Please list some games!\n"
            "Example: `!k whatgame2play valheim lol cod`"
        )
        return

    chosen_game = random.choice(games)

    await ctx.send(
        f"🎲 The wheel of fate has spoken! "
        f"You guys are playing: **{chosen_game}**"
    )


# =========================================================
# ONE-TIME REMINDER
# =========================================================

@bot.command()
async def remind_once(ctx, first: str, *args):
    """
    Examples:

    !k remind_once 18:30 Take the chicken out

    !k remind_once 2026-09-20 18:30 Mom's birthday dinner
    """

    if not args:
        await ctx.send(
            "Please provide a reminder message."
        )
        return

    try:
        # -------------------------------------------------
        # TIME ONLY
        #
        # !k remind_once 18:30 Take the chicken out
        # -------------------------------------------------

        if ":" in first and "-" not in first:

            reminder_time = parse_time(first)

            current = now()

            reminder_datetime = datetime.combine(
                current.date(),
                reminder_time,
                tzinfo=TIMEZONE
            )

            # If today's time has passed,
            # schedule it for tomorrow.
            if reminder_datetime <= current:
                reminder_datetime += timedelta(days=1)

            message = " ".join(args)

        # -------------------------------------------------
        # DATE + TIME
        #
        # !k remind_once 2026-09-20 18:30 Dinner
        # -------------------------------------------------

        else:

            if len(args) < 2:
                await ctx.send(
                    "For a specific date use:\n"
                    "`!k remind_once YYYY-MM-DD HH:MM message`"
                )
                return

            time_string = args[0]
            message = " ".join(args[1:])

            reminder_datetime = parse_full_datetime(
                first,
                time_string
            )

            if reminder_datetime <= now():
                await ctx.send(
                    "That date/time has already passed."
                )
                return

    except ValueError as error:
        await ctx.send(str(error))
        return

    reminder_id = create_reminder(
        reminder_type="once",
        channel_id=ctx.channel.id,
        message=message,
        reminder_datetime=reminder_datetime.isoformat()
    )

    formatted_id = f"O{reminder_id}"

    await ctx.send(
        f"Reminder **{formatted_id}** set for "
        f"**{reminder_datetime.strftime('%Y-%m-%d %H:%M')}**:\n"
        f"{message}"
    )

    asyncio.create_task(
        run_once_reminder(reminder_id)
    )


async def run_once_reminder(reminder_id):
    """
    Wait for a one-time reminder and send it.
    """

    reminder = get_reminder(reminder_id)

    if reminder is None:
        return

    try:
        reminder_datetime = datetime.fromisoformat(
            reminder["reminder_datetime"]
        )

        delay = (
            reminder_datetime - now()
        ).total_seconds()

        if delay > 0:
            await asyncio.sleep(delay)

        # Check that it wasn't deleted while sleeping.
        reminder = get_reminder(reminder_id)

        if reminder is None:
            return

        channel = bot.get_channel(
            reminder["channel_id"]
        )

        if channel is None:
            try:
                channel = await bot.fetch_channel(
                    reminder["channel_id"]
                )

            except discord.DiscordException as error:
                logger.error(
                    "Could not fetch channel for reminder %s: %s",
                    reminder_id,
                    error
                )
                return

        await channel.send(
            content=(
                "@everyone 📢 **Reminder!**\n"
                f"{reminder['message']}"
            ),
            allowed_mentions=discord.AllowedMentions(
                everyone=True
            )
        )

        delete_expired_once_reminder(
            reminder_id
        )

        logger.info(
            "Executed one-time reminder O%s.",
            reminder_id
        )

    except asyncio.CancelledError:
        logger.info(
            "Reminder O%s task cancelled.",
            reminder_id
        )

    except Exception:
        logger.exception(
            "Error executing reminder O%s.",
            reminder_id
        )


# =========================================================
# RESTORE ONE-TIME REMINDERS AFTER RESTART
# =========================================================

async def restore_once_reminders():
    """
    When the bot starts, restore all pending
    one-time reminders from PostgreSQL.
    """

    reminders = get_all_reminders()

    for reminder in reminders:

        if reminder["type"] != "once":
            continue

        reminder_datetime = datetime.fromisoformat(
            reminder["reminder_datetime"]
        )

        # If the bot restarted after the reminder time,
        # send it immediately.
        if reminder_datetime <= now():
            logger.info(
                "Restoring overdue reminder O%s.",
                reminder["id"]
            )

        asyncio.create_task(
            run_once_reminder(
                reminder["id"]
            )
        )


# =========================================================
# MONTHLY REMINDER
# =========================================================

@bot.command()
async def remind_monthly(ctx, day: int, *args):
    """
    Examples:

    !k remind_monthly 15 09:00 Pay the bills

    !k remind_monthly 15 -- Pay the bills
    """

    if day < 1 or day > 28:
        await ctx.send(
            "Please pick a day between 1 and 28 "
            "so every month supports it."
        )
        return

    if not args:
        await ctx.send(
            "Please provide a reminder message."
        )
        return

    # -----------------------------------------------------
    # TIME PROVIDED
    #
    # !k remind_monthly 15 09:00 Pay the bills
    # -----------------------------------------------------

    if args[0] != "--":

        try:
            reminder_time = parse_time(args[0])

        except ValueError as error:
            await ctx.send(str(error))
            return

        message = " ".join(args[1:])

        if not message:
            await ctx.send(
                "Please provide a reminder message."
            )
            return

    # -----------------------------------------------------
    # NO TIME PROVIDED
    #
    # !k remind_monthly 15 -- Pay the bills
    #
    # Use the time when the command was invoked.
    # -----------------------------------------------------

    else:

        current = now()

        reminder_time = current.time()

        message = " ".join(args[1:])

        if not message:
            await ctx.send(
                "Please provide a reminder message."
            )
            return

    reminder_id = create_reminder(
        reminder_type="monthly",
        channel_id=ctx.channel.id,
        message=message,
        day_of_month=day,
        hour=reminder_time.hour,
        minute=reminder_time.minute
    )

    formatted_id = f"M{reminder_id}"

    await ctx.send(
        f"Monthly reminder **{formatted_id}** set for "
        f"day **{day}** at "
        f"**{reminder_time.strftime('%H:%M')}** "
        f"every month:\n"
        f"{message}"
    )


# =========================================================
# MONTHLY CHECK LOOP
# =========================================================

@tasks.loop(seconds=20)
async def monthly_check_loop():
    current = now()

    reminders = get_all_reminders()

    current_month = (
        current.year,
        current.month
    )

    for reminder in reminders:

        if reminder["type"] != "monthly":
            continue

        if reminder["day_of_month"] != current.day:
            continue

        if reminder["hour"] != current.hour:
            continue

        if reminder["minute"] != current.minute:
            continue

        if reminder["last_triggered"]:
            try:
                last_triggered = datetime.fromisoformat(
                    reminder["last_triggered"]
                )

                last_month = (
                    last_triggered.year,
                    last_triggered.month
                )

                if last_month == current_month:
                    continue

            except ValueError:
                pass

        channel = bot.get_channel(
            reminder["channel_id"]
        )

        if channel is None:

            try:
                channel = await bot.fetch_channel(
                    reminder["channel_id"]
                )

            except discord.DiscordException as error:
                logger.error(
                    "Could not fetch channel for monthly "
                    "reminder %s: %s",
                    reminder["id"],
                    error
                )
                continue

        await channel.send(
            content=(
                "@everyone 🗓️ **Monthly Reminder!**\n"
                f"{reminder['message']}"
            ),
            allowed_mentions=discord.AllowedMentions(
                everyone=True
            )
        )

        mark_monthly_triggered(
            reminder["id"],
            current.isoformat()
        )

        logger.info(
            "Executed monthly reminder M%s.",
            reminder["id"]
        )


@monthly_check_loop.before_loop
async def before_monthly_loop():
    await bot.wait_until_ready()


# =========================================================
# LIST REMINDERS
# =========================================================

@bot.command(name="reminders")
async def list_reminders(ctx):
    """
    !k reminders
    """

    reminders = get_all_reminders()

    if not reminders:
        await ctx.send(
            "There are no active reminders."
        )
        return

    lines = ["**Active reminders:**"]

    for reminder in reminders:

        reminder_id = format_reminder_id(
            reminder
        )

        if reminder["type"] == "once":

            reminder_datetime = datetime.fromisoformat(
                reminder["reminder_datetime"]
            )

            lines.append(
                f"`{reminder_id}` | "
                f"Once | "
                f"{reminder_datetime.strftime('%Y-%m-%d %H:%M')} | "
                f"{reminder['message']}"
            )

        else:

            lines.append(
                f"`{reminder_id}` | "
                f"Monthly | "
                f"Day {reminder['day_of_month']} "
                f"at "
                f"{reminder['hour']:02d}:"
                f"{reminder['minute']:02d} | "
                f"{reminder['message']}"
            )

    await ctx.send(
        "\n".join(lines)
    )


# =========================================================
# REMOVE REMINDER
# =========================================================

@bot.command(name="remove_reminder")
async def remove_reminder(ctx, reminder_id: str):
    """
    !k remove_reminder O1
    !k remove_reminder M2
    """

    database_id = parse_reminder_id(
        reminder_id
    )

    if database_id is None:
        await ctx.send(
            "Invalid reminder ID.\n"
            "Use something like `O1` or `M2`."
        )
        return

    reminder = get_reminder(
        database_id
    )

    if reminder is None:
        await ctx.send(
            f"I couldn't find reminder `{reminder_id.upper()}`."
        )
        return

    expected_prefix = (
        "O"
        if reminder["type"] == "once"
        else "M"
    )

    if not reminder_id.upper().startswith(
        expected_prefix
    ):
        await ctx.send(
            f"That reminder is actually "
            f"`{expected_prefix}{database_id}`."
        )
        return

    delete_reminder(
        database_id
    )

    await ctx.send(
        f"Removed reminder **{expected_prefix}{database_id}**."
    )


# =========================================================
# COMMAND ERROR HANDLING
# =========================================================

@bot.event
async def on_command_error(ctx, error):

    if isinstance(
        error,
        commands.MissingRequiredArgument
    ):
        await ctx.send(
            "You're missing an argument. "
            "Use the command with the required information."
        )
        return

    if isinstance(
        error,
        commands.BadArgument
    ):
        await ctx.send(
            "I couldn't understand that argument."
        )
        return

    if isinstance(
        error,
        commands.CommandNotFound
    ):
        return

    logger.exception(
        "Command error:",
        exc_info=error
    )


# =========================================================
# START BOT AND HEALTH ENDPOINT
# =========================================================

async def health_check(_request):
    """Render uses this endpoint to verify that the service is running."""
    return web.json_response({
        "status": "ok",
        "discord_ready": bot.is_ready(),
    })


async def start_health_server():
    app = web.Application()
    app.router.add_get("/", health_check)

    runner = web.AppRunner(app)
    await runner.setup()

    port = int(os.getenv("PORT", "8080"))
    site = web.TCPSite(runner, host="0.0.0.0", port=port)
    await site.start()

    logger.info("Health endpoint listening on port %s.", port)
    return runner


async def main():
    init_database()
    health_runner = await start_health_server()

    try:
        await bot.start(TOKEN)
    finally:
        await health_runner.cleanup()


if __name__ == "__main__":
    asyncio.run(main())

bot.run(TOKEN)
