import os, sqlite3, logging
from datetime import datetime, date
from contextlib import closing
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler, MessageHandler,
    ContextTypes, ConversationHandler, filters
)

TOKEN = os.getenv("BOT_TOKEN", "")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
DB = os.getenv("DB_PATH", "oxyzc.db")
CURRENCY = os.getenv("CURRENCY_NAME", "Points")
MIN_WITHDRAW = int(os.getenv("MIN_WITHDRAW", "100"))
REF_REWARD = int(os.getenv("REF_REWARD", "10"))
DAILY_REWARD = int(os.getenv("DAILY_REWARD", "5"))

METHOD, ACCOUNT, AMOUNT = range(3)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


def connect():
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    return c


def init_db():
    with closing(connect()) as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS users(
          id INTEGER PRIMARY KEY, username TEXT, name TEXT,
          balance INTEGER DEFAULT 0, referrals INTEGER DEFAULT 0,
          referred_by INTEGER, last_daily TEXT, created_at TEXT
        );
        CREATE TABLE IF NOT EXISTS tasks(
          id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT,
          description TEXT, reward INTEGER, url TEXT DEFAULT '',
          active INTEGER DEFAULT 1
        );
        CREATE TABLE IF NOT EXISTS claims(
          id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER,
          task_id INTEGER, status TEXT DEFAULT 'pending',
          created_at TEXT, UNIQUE(user_id,task_id)
        );
        CREATE TABLE IF NOT EXISTS withdrawals(
          id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER,
          amount INTEGER, method TEXT, account TEXT,
          status TEXT DEFAULT 'pending', created_at TEXT, reviewed_at TEXT
        );
        """)
        c.commit()


def register(u, ref=None):
    with closing(connect()) as c:
        old = c.execute("SELECT id FROM users WHERE id=?", (u.id,)).fetchone()
        if old:
            c.execute("UPDATE users SET username=?,name=? WHERE id=?",
                      (u.username or "", u.first_name or "", u.id))
        else:
            valid_ref = None
            if ref and ref != u.id and c.execute("SELECT id FROM users WHERE id=?", (ref,)).fetchone():
                valid_ref = ref
            c.execute("""INSERT INTO users(id,username,name,referred_by,created_at)
                         VALUES(?,?,?,?,?)""",
                      (u.id, u.username or "", u.first_name or "", valid_ref,
                       datetime.utcnow().isoformat(timespec="seconds")))
            if valid_ref:
                c.execute("UPDATE users SET referrals=referrals+1,balance=balance+? WHERE id=?",
                          (REF_REWARD, valid_ref))
        c.commit()


def user(uid):
    with closing(connect()) as c:
        return c.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()


def menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("💰 Balance", callback_data="balance"),
         InlineKeyboardButton("👤 Profile", callback_data="profile")],
        [InlineKeyboardButton("🎯 Tasks", callback_data="tasks"),
         InlineKeyboardButton("🎁 Daily Bonus", callback_data="daily")],
        [InlineKeyboardButton("👥 Refer & Earn", callback_data="refer"),
         InlineKeyboardButton("🏧 Withdraw", callback_data="withdraw")],
        [InlineKeyboardButton("ℹ️ Help", callback_data="help")]
    ])


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    ref = None
    if context.args:
        try: ref = int(context.args[0])
        except ValueError: pass
    register(update.effective_user, ref)
    u = user(update.effective_user.id)
    await update.message.reply_text(
        "✨ <b>Welcome to OXYZC</b>\n\n"
        "Earn points from available tasks, daily bonuses and referrals.\n\n"
        f"💰 Balance: <b>{u['balance']} {CURRENCY}</b>\n"
        f"👥 Referrals: <b>{u['referrals']}</b>\n\n"
        "👇 Select an option:",
        parse_mode=ParseMode.HTML, reply_markup=menu()
    )


async def show_balance(q):
    u = user(q.from_user.id)
    await q.message.reply_text(f"💰 <b>{u['balance']} {CURRENCY}</b>", parse_mode=ParseMode.HTML)


async def show_profile(q):
    u = user(q.from_user.id)
    await q.message.reply_text(
        f"👤 <b>OXYZC Profile</b>\n\nID: <code>{u['id']}</code>\n"
        f"Name: {u['name']}\nUsername: @{u['username'] or 'none'}\n"
        f"Balance: {u['balance']} {CURRENCY}\nReferrals: {u['referrals']}",
        parse_mode=ParseMode.HTML)


async def show_refer(q, context):
    me = await context.bot.get_me()
    link = f"https://t.me/{me.username}?start={q.from_user.id}"
    await q.message.reply_text(
        f"👥 <b>Refer & Earn</b>\n\n"
        f"Your link:\n<code>{link}</code>\n\n"
        f"🎁 Reward per valid new referral: {REF_REWARD} {CURRENCY}",
        parse_mode=ParseMode.HTML)


async def show_daily(q):
    uid = q.from_user.id
    today = date.today().isoformat()
    with closing(connect()) as c:
        row = c.execute("SELECT last_daily FROM users WHERE id=?", (uid,)).fetchone()
        if row["last_daily"] == today:
            await q.message.reply_text("🎁 Today's bonus is already claimed.")
            return
        c.execute("UPDATE users SET balance=balance+?,last_daily=? WHERE id=?",
                  (DAILY_REWARD, today, uid))
        c.commit()
    await q.message.reply_text(f"🎁 Daily bonus claimed: +{DAILY_REWARD} {CURRENCY}")


async def show_tasks(q):
    uid = q.from_user.id
    with closing(connect()) as c:
        tasks = c.execute("SELECT * FROM tasks WHERE active=1 ORDER BY id DESC").fetchall()
        claims = {x["task_id"]: x["status"] for x in
                  c.execute("SELECT task_id,status FROM claims WHERE user_id=?", (uid,)).fetchall()}
    if not tasks:
        await q.message.reply_text("🎯 No tasks available right now.")
        return
    for t in tasks:
        status = claims.get(t["id"])
        text = f"🎯 <b>{t['title']}</b>\n{t['description']}\n💰 Reward: {t['reward']} {CURRENCY}"
        buttons = []
        if t["url"]:
            buttons.append([InlineKeyboardButton("🔗 Open Task", url=t["url"])])
        if status == "approved":
            text += "\n\n✅ Approved"
        elif status == "pending":
            text += "\n\n⏳ Pending review"
        else:
            buttons.append([InlineKeyboardButton("📩 Submit Task", callback_data=f"claim:{t['id']}")])
        await q.message.reply_text(text, parse_mode=ParseMode.HTML,
                                   reply_markup=InlineKeyboardMarkup(buttons) if buttons else None)


async def claim(update, context):
    q = update.callback_query
    tid = int(q.data.split(":")[1])
    uid = q.from_user.id
    with closing(connect()) as c:
        t = c.execute("SELECT * FROM tasks WHERE id=? AND active=1", (tid,)).fetchone()
        if not t:
            await q.answer("Task not found.", show_alert=True); return
        try:
            c.execute("INSERT INTO claims(user_id,task_id,status,created_at) VALUES(?,?,?,?)",
                      (uid, tid, "pending", datetime.utcnow().isoformat(timespec="seconds")))
            c.commit()
        except sqlite3.IntegrityError:
            await q.answer("Already submitted.", show_alert=True); return
    await q.answer("Submitted!")
    await q.message.reply_text(f"⏳ Task #{tid} submitted for admin review.")
    if ADMIN_ID:
        await context.bot.send_message(
            ADMIN_ID, f"📩 Claim: user <code>{uid}</code>, task <b>#{tid}</b>\n"
            f"/approvetask {uid} {tid}\n/rejecttask {uid} {tid}", parse_mode=ParseMode.HTML)


async def help_cmd(update, context):
    await update.message.reply_text(
        f"ℹ️ <b>OXYZC Help</b>\n\n"
        f"🎯 Complete available tasks\n🎁 Claim daily bonus\n👥 Refer users\n"
        f"🏧 Withdraw from {MIN_WITHDRAW} {CURRENCY}+\n\n"
        "All task and withdrawal requests are manually reviewed.",
        parse_mode=ParseMode.HTML)


async def withdraw_start(update, context):
    u = user(update.effective_user.id)
    if u["balance"] < MIN_WITHDRAW:
        await update.message.reply_text(f"❌ Minimum withdrawal: {MIN_WITHDRAW} {CURRENCY}")
        return ConversationHandler.END
    await update.message.reply_text("🏧 Choose method: bKash, Nagad, or Bank.\nType the method:")
    return METHOD


async def get_method(update, context):
    m = update.message.text.strip()
    if m.lower() not in ("bkash", "nagad", "bank"):
        await update.message.reply_text("Please type: bKash, Nagad, or Bank.")
        return METHOD
    context.user_data["method"] = m
    await update.message.reply_text("Enter your payment/account number:")
    return ACCOUNT


async def get_account(update, context):
    a = update.message.text.strip()
    if not a:
        await update.message.reply_text("Enter a valid account number.")
        return ACCOUNT
    context.user_data["account"] = a[:100]
    await update.message.reply_text(f"Enter amount (minimum {MIN_WITHDRAW} {CURRENCY}):")
    return AMOUNT


async def get_amount(update, context):
    try: amount = int(update.message.text.strip())
    except ValueError:
        await update.message.reply_text("Enter a whole number.")
        return AMOUNT
    uid = update.effective_user.id
    u = user(uid)
    if amount < MIN_WITHDRAW or amount > u["balance"]:
        await update.message.reply_text(
            f"Invalid amount. Minimum {MIN_WITHDRAW}; your balance is {u['balance']}."
        )
        return AMOUNT
    with closing(connect()) as c:
        cur = c.execute("UPDATE users SET balance=balance-? WHERE id=? AND balance>=?",
                        (amount, uid, amount))
        if cur.rowcount != 1:
            c.rollback(); await update.message.reply_text("Balance changed; try again."); return ConversationHandler.END
        cur = c.execute("""INSERT INTO withdrawals(user_id,amount,method,account,status,created_at)
                          VALUES(?,?,?,?,?,?)""",
                       (uid, amount, context.user_data["method"], context.user_data["account"],
                        "pending", datetime.utcnow().isoformat(timespec="seconds")))
        wid = cur.lastrowid
        c.commit()
    await update.message.reply_text(
        f"✅ Withdrawal #{wid} submitted.\nAmount: {amount} {CURRENCY}\n"
        f"Method: {context.user_data['method']}\n"
        "Admin will review it.")
    if ADMIN_ID:
        await context.bot.send_message(
            ADMIN_ID,
            f"🏧 <b>Withdrawal #{wid}</b>\nUser: <code>{uid}</code>\n"
            f"Amount: <b>{amount}</b> {CURRENCY}\nMethod: {context.user_data['method']}\n"
            f"Account: <code>{context.user_data['account']}</code>\n\n"
            f"/approvewithdraw {wid}\n/rejectwithdraw {wid}",
            parse_mode=ParseMode.HTML)
    context.user_data.clear()
    return ConversationHandler.END


async def cancel(update, context):
    context.user_data.clear()
    await update.message.reply_text("Cancelled.")
    return ConversationHandler.END


def admin(func):
    async def wrap(update, context):
        if update.effective_user.id != ADMIN_ID:
            await update.message.reply_text("⛔ Admin only.")
            return
        return await func(update, context)
    return wrap


@admin
async def addtask(update, context):
    parts = [x.strip() for x in update.message.text.partition(" ")[2].split("|")]
    if len(parts) < 3:
        await update.message.reply_text("/addtask reward | title | description | url(optional)")
        return
    try: reward = int(parts[0])
    except ValueError:
        await update.message.reply_text("Reward must be a number."); return
    with closing(connect()) as c:
        cur = c.execute("INSERT INTO tasks(title,description,reward,url) VALUES(?,?,?,?)",
                        (parts[1], parts[2], reward, parts[3] if len(parts)>3 else ""))
        c.commit()
    await update.message.reply_text(f"✅ Task #{cur.lastrowid} created.")


@admin
async def approve_task(update, context):
    if len(context.args) != 2:
        await update.message.reply_text("/approvetask USER_ID TASK_ID"); return
    uid, tid = map(int, context.args)
    with closing(connect()) as c:
        claim = c.execute("SELECT * FROM claims WHERE user_id=? AND task_id=? AND status='pending'",
                          (uid, tid)).fetchone()
        task = c.execute("SELECT * FROM tasks WHERE id=?", (tid,)).fetchone()
        if not claim or not task:
            await update.message.reply_text("Pending claim not found."); return
        c.execute("UPDATE claims SET status='approved' WHERE id=?", (claim["id"],))
        c.execute("UPDATE users SET balance=balance+? WHERE id=?", (task["reward"], uid))
        c.commit()
    await update.message.reply_text("✅ Task approved and reward credited.")
    try: await context.bot.send_message(uid, f"🎉 Task #{tid} approved: +{task['reward']} {CURRENCY}")
    except: pass


@admin
async def reject_task(update, context):
    if len(context.args) != 2:
        await update.message.reply_text("/rejecttask USER_ID TASK_ID"); return
    uid, tid = map(int, context.args)
    with closing(connect()) as c:
        cur = c.execute("UPDATE claims SET status='rejected' WHERE user_id=? AND task_id=? AND status='pending'",
                        (uid, tid)); c.commit()
    await update.message.reply_text("✅ Rejected." if cur.rowcount else "Claim not found.")


@admin
async def approve_withdraw(update, context):
    if len(context.args) != 1:
        await update.message.reply_text("/approvewithdraw WITHDRAWAL_ID"); return
    wid = int(context.args[0])
    with closing(connect()) as c:
        w = c.execute("SELECT * FROM withdrawals WHERE id=? AND status='pending'", (wid,)).fetchone()
        if not w:
            await update.message.reply_text("Pending withdrawal not found."); return
        c.execute("UPDATE withdrawals SET status='paid',reviewed_at=? WHERE id=?",
                  (datetime.utcnow().isoformat(timespec="seconds"), wid)); c.commit()
    await update.message.reply_text("✅ Marked as paid.")
    try: await context.bot.send_message(w["user_id"], f"✅ Withdrawal #{wid} marked as paid.")
    except: pass


@admin
async def reject_withdraw(update, context):
    if len(context.args) != 1:
        await update.message.reply_text("/rejectwithdraw WITHDRAWAL_ID"); return
    wid = int(context.args[0])
    with closing(connect()) as c:
        w = c.execute("SELECT * FROM withdrawals WHERE id=? AND status='pending'", (wid,)).fetchone()
        if not w:
            await update.message.reply_text("Pending withdrawal not found."); return
        c.execute("UPDATE withdrawals SET status='rejected',reviewed_at=? WHERE id=?",
                  (datetime.utcnow().isoformat(timespec="seconds"), wid))
        c.execute("UPDATE users SET balance=balance+? WHERE id=?", (w["amount"], w["user_id"]))
        c.commit()
    await update.message.reply_text("✅ Rejected; balance refunded.")
    try: await context.bot.send_message(w["user_id"], f"❌ Withdrawal #{wid} rejected; balance refunded.")
    except: pass


@admin
async def stats(update, context):
    with closing(connect()) as c:
        u = c.execute("SELECT COUNT(*) n FROM users").fetchone()["n"]
        p = c.execute("SELECT COUNT(*) n FROM withdrawals WHERE status='pending'").fetchone()["n"]
        b = c.execute("SELECT COALESCE(SUM(balance),0) n FROM users").fetchone()["n"]
    await update.message.reply_text(f"📊 OXYZC Admin Stats\nUsers: {u}\nOutstanding: {b} {CURRENCY}\nPending withdrawals: {p}")


async def buttons(update, context):
    q = update.callback_query
    await q.answer()
    if q.data == "balance": await show_balance(q)
    elif q.data == "profile": await show_profile(q)
    elif q.data == "refer": await show_refer(q, context)
    elif q.data == "daily": await show_daily(q)
    elif q.data == "tasks": await show_tasks(q)
    elif q.data == "withdraw":
        await q.message.reply_text(f"🏧 Use /withdraw to request a withdrawal.\nMinimum: {MIN_WITHDRAW} {CURRENCY}")
    elif q.data == "help": await q.message.reply_text("Use the menu to access Balance, Tasks, Referrals, Daily Bonus and Withdraw.")


def main():
    if not TOKEN:
        raise RuntimeError("BOT_TOKEN is not set.")
    init_db()
    app = Application.builder().token(TOKEN).build()

    conv = ConversationHandler(
        entry_points=[CommandHandler("withdraw", withdraw_start)],
        states={
            METHOD: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_method)],
            ACCOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_account)],
            AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_amount)],
        },
        fallbacks=[CommandHandler("cancel", cancel)]
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(conv)
    app.add_handler(CommandHandler("addtask", addtask))
    app.add_handler(CommandHandler("approvetask", approve_task))
    app.add_handler(CommandHandler("rejecttask", reject_task))
    app.add_handler(CommandHandler("approvewithdraw", approve_withdraw))
    app.add_handler(CommandHandler("rejectwithdraw", reject_withdraw))
    app.add_handler(CommandHandler("stats", stats))
    app.add_handler(CallbackQueryHandler(claim, pattern=r"^claim:"))
    app.add_handler(CallbackQueryHandler(buttons))
    app.run_polling()


if __name__ == "__main__":
    main()
