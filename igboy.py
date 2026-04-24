import logging
import instaloader
import pyotp
import time
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
logger = logging.getLogger(__name__)

# States
GET_DATA, GET_2FA_KEYS = range(2)

def get_keyboard():
    return ReplyKeyboardMarkup([['Start', 'Stop']], resize_keyboard=True)

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear() 
    await update.message.reply_text(
        "হাই! আপনার ডাটাগুলো নিচের ফরমেটে দিন:\n\n"
        "First name: 민경\n"
        "Login: user123\n"
        "Password: pass123\n\n"
        "(একাধিক আইডি একবারে দিতে পারেন)",
        reply_markup=get_keyboard()
    )
    return GET_DATA

async def receive_data(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if text == "Start": return GET_DATA

    # Regex দিয়ে Login এবং Password খুঁজে বের করা
    usernames = re.findall(r"Login:\s*(\S+)", text)
    passwords = re.findall(r"Password:\s*(\S+)", text)

    if not usernames or not passwords:
        await update.message.reply_text("❌ ফরমেট মেলেনি! দয়া করে 'Login:' এবং 'Password:' ব্যবহার করুন।")
        return GET_DATA
    
    context.user_data['list_usernames'] = usernames
    context.user_data['list_passwords'] = passwords
    
    await update.message.reply_text(f"✅ {len(usernames)}টি আইডি পাওয়া গেছে।\nএবার **2FA Secret Keys** দিন (এক লাইনে একটি):")
    return GET_2FA_KEYS

async def process_accounts(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keys = [k.strip().replace(" ", "") for k in update.message.text.strip().split('\n') if k.strip()]
    usernames = context.user_data.get('list_usernames', [])
    passwords = context.user_data.get('list_passwords', [])
    
    if len(usernames) != len(keys):
        await update.message.reply_text(f"⚠️ মেলেনি! আইডি আছে {len(usernames)}টি কিন্তু কী দিয়েছেন {len(keys)}টি। আবার দিন:")
        return GET_2FA_KEYS

    await update.message.reply_text("⚡ লগইন শুরু হচ্ছে... কপি করার জন্য কুকি নিচে পাঠানো হবে।")

    for i in range(len(usernames)):
        user = usernames[i]
        pwd = passwords[i]
        secret = keys[i]
        
        try:
            totp = pyotp.TOTP(secret)
            two_f_code = totp.now()
            
            L = instaloader.Instaloader()
            try:
                L.login(user, pwd)
            except instaloader.TwoFactorAuthRequiredException:
                L.two_factor_login(two_f_code)
            
            cookies = L.context._session.cookies.get_dict()
            cookie_str = "; ".join([f"{k}={v}" for k, v in cookies.items()])
            
            msg = f"👤 **User:** `{user}`\n🔑 **Cookie:**\n`{cookie_str}`"
            await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)
            
        except Exception as e:
            await update.message.reply_text(f"❌ **Failed:** {user}\nError: {str(e)}")
        
        time.sleep(3) 

    await update.message.reply_text("✅ টাস্ক কমপ্লিট!", reply_markup=get_keyboard())
    context.user_data.clear()
    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text("🛑 বন্ধ করা হয়েছে।")
    return ConversationHandler.END

def main():
    # সরাসরি আপনার টোকেনটি এখানে বসিয়ে দেওয়া হলো
    TOKEN = "7152089923:AAHzwFQKwKj-KRCQ6EYAch_npetUr57pClM"
    
    app = Application.builder().token(TOKEN).build()

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start_command), MessageHandler(filters.Regex('^Start$'), start_command)],
        states={
            GET_DATA: [MessageHandler(filters.TEXT & ~filters.Regex('^Stop$') & ~filters.COMMAND, receive_data)],
            GET_2FA_KEYS: [MessageHandler(filters.TEXT & ~filters.Regex('^Stop$') & ~filters.COMMAND, process_accounts)],
        },
        fallbacks=[CommandHandler("cancel", cancel), MessageHandler(filters.Regex('^Stop$'), cancel)],
    )

    app.add_handler(conv_handler)
    print("বট চালু হচ্ছে...")
    app.run_polling()

if __name__ == '__main__':
    main()
    
