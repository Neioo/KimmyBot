# Kimmy Discord Bot

Kimmy is a Discord bot with one-time and monthly reminders. It uses Render
Postgres for persistent reminder data and exposes a small health endpoint at
`/` for Render.

## Run locally

1. Install Python 3.10 and [uv](https://docs.astral.sh/uv/).
2. Create a PostgreSQL database and copy its connection URL.
3. Create a `.env` file (never commit it):

   ```env
   DISCORD_TOKEN=your_discord_bot_token
   DATABASE_URL=postgresql://user:password@host:5432/database
   ```

4. Install and run:

   ```powershell
   uv sync
   uv run python main.py
   ```

The health endpoint is available at `http://localhost:8080/`.

## Deploy to Render (Free)

1. Push this project to a private GitHub repository. Do not commit `.env`.
2. In the Discord Developer Portal, enable **Message Content Intent** and
   **Server Members Intent** for the bot.
3. In Render, select **New > Postgres**, choose **Free**, and create the
   database. Copy its external connection URL.
4. In Render, select **New > Web Service**, connect the GitHub repository,
   and choose the **Free** plan.
5. Configure the service:

   | Setting | Value |
   | --- | --- |
   | Runtime | Python 3 |
   | Build Command | `uv sync --frozen --no-dev` |
   | Start Command | `uv run --no-sync python main.py` |
   | `PYTHON_VERSION` | `3.10` |
   | `DISCORD_TOKEN` | Your Discord bot token |
   | `DATABASE_URL` | The Render Postgres external connection URL |

6. Deploy. Open the generated Render URL and confirm it returns JSON with
   `"status": "ok"`. Check the Render logs for the bot's ready message.

## Important free-tier limits

- This project intentionally does **not** use SQLite on Render. Free Render
  web services use an ephemeral filesystem, so a SQLite file is erased on a
  restart, redeploy, or idle spin-down.
- Free Render web services spin down after 15 minutes with no inbound HTTP or
  WebSocket traffic. Because a Discord gateway connection is outbound, it does
  not prevent this. A health endpoint is included, but the bot is not a
  reliable 24/7 service on the free plan.
- A free Render Postgres database expires after 30 days. Export your reminder
  data and upgrade or move the database before it expires.

For an always-online bot with permanent data, use a paid always-on worker or
web service with a paid Postgres database.
