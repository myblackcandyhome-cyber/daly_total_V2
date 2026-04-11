import os, random, time, requests
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (ApplicationBuilder, CommandHandler, MessageHandler, filters, 
                          ConversationHandler, ContextTypes, CallbackQueryHandler)
from database import Database
from report_engine import ReportEngine
from dotenv import load_dotenv

load_dotenv()
db = Database()
engine = ReportEngine()

DATE, T12, T23, PDAY, PTOTAL, CUST, JPY, UPF, FEE, ACTUAL = range(10)

def check_tronscan(target_amount, start_time):
    url = "https://apilist.tronscan.org/api/token_trc20/transfers"
    params = {"limit": 20, "direction": "in", "relatedAddress": os.getenv('MY_WALLET')}
    try:
        res = requests.get(url, params=params).json()
        for tx in res.get('token_transfers', []):
            amount = float(tx['quant']) / 1_000_000
            ts = tx['block_ts'] / 1000
            if abs(amount - target_amount) < 0.0001 and ts >= start_time:
                return True
    except: pass
    return False

async def is_subscribed(update: Update):
    expiry = db.get_user_expiry(update.effective_user.id)
    if not expiry or expiry < datetime.now():
        await update.message.reply_text("❌ 服务已到期。请使用 /renew 续费 (150 USDT/30天)")
        return False
    return True

async def renew_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    final_amt = round(150.0 + random.uniform(0.001, 0.999), 3)
    start_ts = int(time.time())
    db.save_payment_intent(user_id, final_amt, start_ts)
    context.user_data['pay'] = {'amt': final_amt, 'ts': start_ts}
    
    text = (f"💳 **服务续费**\n\n请在30分钟内转账: `{final_amt}` USDT\n"
            f"地址 (TRC20): `{os.getenv('MY_WALLET')}`\n\n"
            f"⚠️ 请务必转账**精确金额**（含小数位）")
    btn = [[InlineKeyboardButton("✅ 我已完成转账", callback_data='verify')]]
    await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(btn), parse_mode='Markdown')

async def verify_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    pay = context.user_data.get('pay')
    if not pay:
        await query.answer("❌ 未找到订单信息", show_alert=True)
        return
    
    if check_tronscan(pay['amt'], pay['ts']):
        new_exp = db.add_subscription(query.from_user.id)
        await query.message.edit_text(f"🎊 支付成功！到期时间: {new_exp.strftime('%Y-%m-%d %H:%M:%S')}")
        context.user_data.pop('pay', None)
    else:
        await query.answer("⌛ 未检测到到账，请稍后再试", show_alert=True)

# --- ส่วนของ Conversation /add ---
async def start_add(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_subscribed(update): return ConversationHandler.END
    await update.message.reply_text("🧧 **开始登记**\n请输入 **日期**:")
    return DATE

async def get_date(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['date'] = update.message.text
    await update.message.reply_text("1️⃣ 一转二:")
    return T12

async def get_t12(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['t12'] = update.message.text
    await update.message.reply_text("2️⃣ 二转三:")
    return T23

async def get_t23(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['t23'] = update.message.text
    await update.message.reply_text("3️⃣ 当日压单:")
    return PDAY

async def get_pday(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['p_day'] = update.message.text
    await update.message.reply_text("4️⃣ 总压单:")
    return PTOTAL

async def get_ptotal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['p_total'] = update.message.text
    await update.message.reply_text("5️⃣ 客户数:")
    return CUST

async def get_cust(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['cust'] = update.message.text
    await update.message.reply_text("6️⃣ 进账业绩 (日元):")
    return JPY

async def get_jpy(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['jpy'] = update.message.text
    await update.message.reply_text("7️⃣ 进账业绩 (U):")
    return UPF

async def get_upf(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['u_perf'] = update.message.text
    await update.message.reply_text("8️⃣ 车商费用 (%):")
    return FEE

async def get_fee(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['fee'] = update.message.text
    await update.message.reply_text("9️⃣ 公司实际到账 (U):")
    return ACTUAL

async def get_actual(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['actual'] = update.message.text
    db.save_record(context.user_data)
    await update.message.reply_text("✅ 登记成功!")
    await send_report(update, context)
    return ConversationHandler.END

async def send_report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_subscribed(update): return
    records = db.get_all_records()
    if not records:
        await update.message.reply_text("📭 没有记录")
        return
    path = engine.create_report(records)
    await (update.message or update.callback_query.message).reply_photo(photo=open(path, 'rb'), caption="总结报表")
    if os.path.exists(path): os.remove(path)

if __name__ == '__main__':
    app = ApplicationBuilder().token(os.getenv('BOT_TOKEN')).build()
    
    add_conv = ConversationHandler(
        entry_points=[CommandHandler('add', start_add)],
        states={
            DATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_date)],
            T12: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_t12)],
            T23: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_t23)],
            PDAY: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_pday)],
            PTOTAL: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_ptotal)],
            CUST: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_cust)],
            JPY: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_jpy)],
            UPF: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_upf)],
            FEE: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_fee)],
            ACTUAL: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_actual)],
        },
        fallbacks=[CommandHandler('cancel', lambda u,c: ConversationHandler.END)]
    )
    
    app.add_handler(add_conv)
    app.add_handler(CommandHandler('renew', renew_command))
    app.add_handler(CommandHandler('report', send_report))
    app.add_handler(CallbackQueryHandler(verify_callback, pattern='verify'))
    
    app.run_polling()
