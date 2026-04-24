import logging
import instaloader
import pyotp
import asyncio
import os
import re
from telegram import Update, ReplyKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
    ConversationHandler,
)

# --- Logging ---
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

# States
SINGLE_ID_DATA, SINGLE_2FA, BULK_USERS, BULK_PASS, BULK_KEYS = range(5)

def main_keyboard():
    return ReplyKeyboardMarkup([
        ['/start', 'Cancel'],
        ['Single ID', 'Bulk IDs']
    ], resize_keyboard=True)

# টেক্সট থেকে স্মার্টলি ইউজার/পাস বের করার ফাংশন
def extract_credentials(text):
    user_match = re.search(r'(?:Login|Username):\s*(\S+)', text, re.IGNORECASE)
    pass_match = re.search(r'Password:\s*(\S+)', text, re.IGNORECASE)
    if user_match and pass_match:
        return user_match.group(1), pass_match.group(1)
    lines = [line.strip() for line in text.split('\n') if line.strip()]
    if len(lines) >= 2:
        return lines[0], lines[1]
    return None, None

# কুকি সংগ্রহের কোর ফাংশন
async def get_insta_cookie(update_msg, user, pwd, secret, update):
    try:
        await update_msg.edit_text(f"👤 `{user}`\n⚙️ Status: Generating TOTP...")
        totp = pyotp.TOTP(secret.replace(" ", ""))
        two_f_code = totp.now()

        L = instaloader.Instaloader(quiet=True)
        loop = asyncio.get_event_loop()
        try:
            await update_msg.edit_text(f"👤 `{user}`\n⚙️ Status: Logging in...")
            await loop.run_in_executor(None, L.login, user, pwd)
        except instaloader.TwoFactorAuthRequiredException:
            await update_msg.edit_text(f"👤 `{user}`\n⚙️ Status: Submitting 2FA...")
            await loop.run_in_executor(None, L.two_factor_login, two_f_code)
        
        cookies = L.context._session.cookies.get_dict()
        cookie_str = "; ".join([f"{k}={v}" for k, v in cookies.items()])
        return cookie_str
    except Exception as e:
        return f"Error: {str(e)}"

# --- Handlers ---

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 স্বাগতম! বটটি এখন সিঙ্গেল আইডি মোডে আছে।\nআইডি ডিটেইলস দিন অথবা বাটন ব্যবহার করুন।",
        reply_markup=main_keyboard()
    )
    return SINGLE_ID_DATA

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text("🛑 সব প্রসেস বাতিল করা হয়েছে।", reply_markup=main_keyboard())
    return ConversationHandler.END

# --- Single ID Logic ---
async def single_id_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("👤 সিঙ্গেল আইডির ডিটেইলস (User/Pass) দিন:")
    return SINGLE_ID_DATA

async def handle_single_data(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if text == "Bulk IDs": return await bulk_id_start(update, context)
    user, pwd = extract_credentials(text)
    if user and pwd:
        context.user_data['u'], context.user_data['p'] = user, pwd
        await update.message.reply_text(f"✅ User: `{user}`\nএখন **2FA Key** দিন:")
        return SINGLE_2FA
    await update.message.reply_text("❌ ইউজার/পাসওয়ার্ড বুঝা যায়নি। আবার দিন।")
    return SINGLE_ID_DATA

async def handle_single_2fa(update: Update, context: ContextTypes.DEFAULT_TYPE):
    status_msg = await update.message.reply_text("🚀 প্রসেসিং...")
    cookie = await get_insta_cookie(status_msg, context.user_data['u'], context.user_data['p'], update.message.text, update)
    
    if "Error" in cookie:
        await status_msg.edit_text(f"❌ ব্যর্থ!\n{cookie}")
    else:
        await update.message.reply_text(f"👤 **{context.user_data['u']}**\n🔑 **Cookie:**\n`{cookie}`", parse_mode=ParseMode.MARKDOWN)
        await status_msg.edit_text("✅ কাজ সম্পন্ন!")
    return SINGLE_ID_DATA

# --- Bulk ID Logic ---
async def bulk_id_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("📂 অনেকগুলো ইউজারনেম একসাথে দিন (এক লাইনে একটি):")
    return BULK_USERS

async def handle_bulk_users(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['bulk_u'] = [u.strip() for u in update.message.text.split('\n') if u.strip()]
    await update.message.reply_text(f"✅ {len(context.user_data['bulk_u'])}টি ইউজার পাওয়া গেছে।\nএখন একটি **Common Password** দিন যা সব আইডিতে কাজ করবে:")
    return BULK_PASS

async def handle_bulk_pass(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['bulk_p'] = update.message.text.strip()
    await update.message.reply_text("🔑 পাসওয়ার্ড সেভ হয়েছে। এখন সিরিয়াল অনুযায়ী সব আইডির **2FA Keys** দিন:")
    return BULK_KEYS

async def handle_bulk_keys(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keys = [k.strip() for k in update.message.text.split('\n') if k.strip()]
    users = context.user_data['bulk_u']
    pwd = context.user_data['bulk_p']
    
    if len(keys) != len(users):
        await update.message.reply_text(f"⚠️ মেলেনি! ইউজার {len(users)}টি কিন্তু কী {len(keys)}টি। আবার দিন:")
        return BULK_KEYS

    status_msg = await update.message.reply_text("⚡ বাল্ক প্রসেসিং শুরু হচ্ছে...")
    results = []

    for i in range(len(users)):
        await status_msg.edit_text(f"⏳ প্রসেসিং: {i+1}/{len(users)}")
        cookie = await get_insta_cookie(status_msg, users[i], pwd, keys[i], update)
        results.append(f"{users[i]} | `{cookie}`")
    
    final_report = "\n\n".join(results)
    # যদি রিপোর্ট খুব বড় হয় তবে টেক্সট ফাইলে পাঠানো
    if len(final_report) > 4000:
        with open("bulk_cookies.txt", "w") as f: f.write(final_report.replace("`", ""))
        await update.message.reply_document(document=open("bulk_cookies.txt", "rb"), caption="🎯 বাল্ক কুকি রিপোর্ট।")
    else:
        await update.message.reply_text(f"📋 **Bulk Report:**\n\n{final_report}", parse_mode=ParseMode.MARKDOWN)

    await status_msg.edit_text("✅ টাস্ক সম্পন্ন!")
    return SINGLE_ID_DATA

def main():
    TOKEN = "8659290244:AAHK2SHRva4yYlnuOSM44CDNsRKgKy2NbJU"
    app = Application.builder().token(TOKEN).build()

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start_command)],
        states={
            SINGLE_ID_DATA: [
                MessageHandler(filters.Regex('^Bulk IDs$'), bulk_id_start),
                MessageHandler(filters.TEXT & ~filters.Regex('^Cancel$|/start'), handle_single_data)
            ],
            SINGLE_2FA: [MessageHandler(filters.TEXT & ~filters.Regex('^Cancel$'), handle_single_2fa)],
            BULK_USERS: [MessageHandler(filters.TEXT & ~filters.Regex('^Cancel$'), handle_bulk_users)],
            BULK_PASS: [MessageHandler(filters.TEXT & ~filters.Regex('^Cancel$'), handle_bulk_pass)],
            BULK_KEYS: [MessageHandler(filters.TEXT & ~filters.Regex('^Cancel$'), handle_bulk_keys)],
        },
        fallbacks=[MessageHandler(filters.Regex('^Cancel$'), cancel), CommandHandler("start", start_command)],
    )

    app.add_handler(conv_handler)
    print("Bot Stsrted")
    app.run_polling()

if __name__ == '__main__':
    main()
