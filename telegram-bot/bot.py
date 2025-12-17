# bot.py -- simple Telegram stock-management bot (sqlite + python-telegram-bot async)
import asyncio
import sqlite3
from sqlite3 import Connection
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
)


BOT_TOKEN = os.getenv("BOT_TOKEN")


DB_PATH = "stock.db"



def init_db(path: str = DB_PATH):
    conn: Connection = sqlite3.connect(path, check_same_thread=False)
    cur = conn.cursor()
    cur.execute("""
    CREATE TABLE IF NOT EXISTS stock (
        sku TEXT PRIMARY KEY,
        name TEXT,
        qty INTEGER NOT NULL DEFAULT 0
    );
    """)
    conn.commit()
    return conn


# DB connection (module-level)
db = init_db()


# Helper DB functions
def add_or_update_sku(sku: str, name: str, qty: int):
    cur = db.cursor()
    cur.execute("SELECT qty FROM stock WHERE sku = ?", (sku,))
    row = cur.fetchone()
    if row:
        new_qty = row[0] + qty
        cur.execute("UPDATE stock SET qty = ? WHERE sku = ?", (new_qty, sku))
    else:
        cur.execute("INSERT INTO stock (sku, name, qty) VALUES (?, ?, ?)", (sku, name, qty))
    db.commit()
    return True


def get_stock(sku: str):
    cur = db.cursor()
    cur.execute("SELECT sku, name, qty FROM stock WHERE sku = ?", (sku,))
    return cur.fetchone()


def list_all():
    cur = db.cursor()
    cur.execute("SELECT sku, name, qty FROM stock ORDER BY sku")
    return cur.fetchall()


def reduce_stock(sku: str, amount: int):
    cur = db.cursor()
    cur.execute("SELECT qty FROM stock WHERE sku = ?", (sku,))
    row = cur.fetchone()
    if not row:
        return False, "SKU not found"
    current = row[0]
    if amount > current:
        return False, f"Not enough stock (have {current})"
    new_q = current - amount
    cur.execute("UPDATE stock SET qty = ? WHERE sku = ?", (new_q, sku))
    db.commit()
    return True, new_q

def delete_sku(sku: str):
    cur = db.cursor()
    cur.execute("SELECT sku FROM stock WHERE sku = ?", (sku,))
    row = cur.fetchone()
    if not row:
        return False
    cur.execute("DELETE FROM stock WHERE sku = ?", (sku,))
    db.commit()
    return True


# Bot command handlers (async)
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Welcome to ShopStockBot!\n"
        "Use /help to see commands."
    )


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "Commands:\n"
        "/addsku <SKU> <name> <qty> - add new SKU or increase qty\n"
        "/stock <SKU> - show qty for SKU\n"
        "/sell <SKU> <qty> - reduce qty (record sale)\n"
        "/list - show all SKUs\n"
        "/help - show this message\n\n"
        "Examples:\n"
        "/addsku ABC123 \"Blue Saree\" 10\n"
        "/sell ABC123 2\n"
    )
    await update.message.reply_text(text)


async def addsku(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    if len(args) < 3:
        await update.message.reply_text("Usage: /addsku <SKU> <name> <qty>")
        return
    sku = args[0]
    # name may include spaces — join all middle parts except last if length>3
    qty_str = args[-1]
    name = " ".join(args[1:-1])
    try:
        qty = int(qty_str)
    except ValueError:
        await update.message.reply_text("Quantity must be a number.")
        return
    add_or_update_sku(sku, name, qty)
    await update.message.reply_text(f"SKU {sku} ({name}) updated by +{qty}.")


async def stock_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    if len(args) != 1:
        await update.message.reply_text("Usage: /stock <SKU>")
        return
    sku = args[0]
    row = get_stock(sku)
    if not row:
        await update.message.reply_text("SKU not found.")
        return
    await update.message.reply_text(f"SKU: {row[0]}\nName: {row[1]}\nQty: {row[2]}")


async def sell_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    if len(args) != 2:
        await update.message.reply_text("Usage: /sell <SKU> <qty>")
        return
    sku = args[0]
    try:
        qty = int(args[1])
    except ValueError:
        await update.message.reply_text("Quantity must be a number.")
        return
    ok, result = reduce_stock(sku, qty)
    if not ok:
        await update.message.reply_text(f"Error: {result}")
    else:
        await update.message.reply_text(f"Sold {qty} of {sku}. New qty: {result}")


async def list_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    rows = list_all()
    if not rows:
        await update.message.reply_text("No items in stock.")
        return
    text = "Current stock:\n"
    for sku, name, qty in rows:
        text += f"{sku} — {name} — {qty}\n"
    await update.message.reply_text(text)

async def addbulk_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Usage: /addbulk SKU|Name|qty; SKU2|Name2|qty2; ...
    Example: /addbulk ABC123|Blue Saree|10; DEF456|Red Saree|5
    """
    text = update.message.text.partition(" ")[2].strip()
    if not text:
        await update.message.reply_text("Usage: /addbulk SKU|Name|qty; SKU2|Name2|qty2; ...")
        return

    parts = [p.strip() for p in text.split(";") if p.strip()]
    if not parts:
        await update.message.reply_text("No valid entries found.")
        return

    results = []
    for entry in parts:
        # expect SKU|Name|qty
        bits = [b.strip() for b in entry.split("|")]
        if len(bits) != 3:
            results.append(f"✖ Invalid format: `{entry}` (expected SKU|Name|qty)")
            continue
        sku, name, qty_str = bits
        try:
            qty = int(qty_str)
        except ValueError:
            results.append(f"✖ `{sku}`: qty must be a number ({qty_str})")
            continue
        add_or_update_sku(sku, name, qty)
        results.append(f"✔ `{sku}` +{qty} ({name})")

    await update.message.reply_text("\n".join(results))


async def sellbulk_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Usage: /sellbulk SKU|qty; SKU2|qty2; ...
    Example: /sellbulk ABC123|2; DEF456|3
    """
    text = update.message.text.partition(" ")[2].strip()
    if not text:
        await update.message.reply_text("Usage: /sellbulk SKU|qty; SKU2|qty2; ...")
        return

    parts = [p.strip() for p in text.split(";") if p.strip()]
    if not parts:
        await update.message.reply_text("No valid entries found.")
        return

    results = []
    for entry in parts:
        bits = [b.strip() for b in entry.split("|")]
        if len(bits) != 2:
            results.append(f"✖ Invalid format: `{entry}` (expected SKU|qty)")
            continue
        sku, qty_str = bits
        try:
            qty = int(qty_str)
        except ValueError:
            results.append(f"✖ `{sku}`: qty must be a number ({qty_str})")
            continue
        ok, res = reduce_stock(sku, qty)
        if not ok:
            results.append(f"✖ `{sku}`: {res}")
        else:
            results.append(f"✔ `{sku}` - sold {qty}. New qty: {res}")

    await update.message.reply_text("\n".join(results))


async def delete_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    if len(args) != 1:
        await update.message.reply_text("Usage: /delete <SKU>")
        return

    sku = args[0]
    success = delete_sku(sku)

    if not success:
        await update.message.reply_text("SKU not found.")
    else:
        await update.message.reply_text(f"SKU {sku} has been deleted.")



def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    # register handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("addsku", addsku))
    app.add_handler(CommandHandler("stock", stock_cmd))
    app.add_handler(CommandHandler("sell", sell_cmd))
    app.add_handler(CommandHandler("list", list_cmd))
    app.add_handler(CommandHandler("addbulk", addbulk_cmd))
    app.add_handler(CommandHandler("sellbulk", sellbulk_cmd))
    app.add_handler(CommandHandler("delete", delete_cmd))


    print("Bot starting (long polling). Press Ctrl+C to stop.")
    app.run_polling()


if __name__ == "__main__":
    main()
