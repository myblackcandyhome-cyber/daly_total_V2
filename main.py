import os
import random
import time
import requests
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    filters,
    ConversationHandler,
    ContextTypes,
    CallbackQueryHandler
)
from database import Database
from report_engine import ReportEngine
from dotenv import load_dotenv

# โหลดค่าคอนฟิก
load_dotenv()
db = Database()
engine = ReportEngine()

# สถานะสำหรับ ConversationHandler (/add)
DATE, T12, T23, PDAY, PTOTAL, CUST, JPY, UPF, FEE, ACTUAL = range(10)

# --- 1. ระบบตรวจสอบยอดโอน (TronScan API) ---
def check_tronscan(target_amount, start_time):
    url = "https://apilist.tronscan.org/api/token_trc20/transfers"
    params = {
        "limit": 20,
        "direction": "in",
        "relatedAddress": os.getenv('MY_WALLET')
    }
    try:
        response = requests.get(url, params=params, timeout=10)
        data = response.json()
        for tx in data.get('token_transfers', []):
            if tx['tokenInfo']['tokenId'] == 'TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t': # USDT
                amount_received = float(tx['quant']) / 1_000_000
                tx_time = tx['block_ts'] / 1000 
                if abs(amount_received - target_amount) < 0.0001 and tx_time >= start_time:
                    return True, tx['transaction_id']
    except Exception as e:
        print(f"⚠️ TronScan Error: {e}")
    return False, None

# --- 2. ฟังก์ชัน JobQueue (แจ้งเตือนกลับไปยัง Chat ID เดิม) ---
async def auto_payment_monitor(context: ContextTypes.DEFAULT_TYPE):
    try:
        pending_list = db.get_all_pending_payments()
        for pay in pending_list:
            if int(time.time()) - pay['start_time'] > 1800:
                db.update_payment_status(pay['id'], 'expired')
                continue
            
            success, txid = check_tronscan(float(pay['amount']), pay['start_time'])
            if success:
                db.update_payment_status(pay['id'], 'success', txid)
                new_exp = db.add_subscription(pay['user_id'], days=30)
                
                # ส่งกลับไปยัง chat_id ที่บันทึกไว้ (รองรับทั้งกลุ่มและส่วนตัว)
                target_id = pay.get('chat_id') or pay['user_id']
                
                await context.bot.send_message(
                    chat_id=target_id,
                    text=f"🎊 **自动充值成功！**\n\n✅ 收到: `{pay['amount']}` USDT\n📅 有效期至: `{new_exp.strftime('%Y-%m-%d %H:%M:%S')}`\n🚀 权限已开通！",
                    parse_mode='Markdown'
                )
    except Exception as e:
        print(f"❌ Monitor Job Error: {e}")

# --- 3. Helper Functions ---
async def is_subscribed(update: Update):
    user_id = update.effective_user.id
    expiry = db.get_user_expiry(user_id)
    if not expiry or expiry < datetime.now():
        await update.message.reply_text("❌ **服务已到期**\n请使用 /renew 续费 (150 USDT/30天)")
        return False
    return True

async def send_report_action(update):
    chat_id = update.effective_chat.id
    records = db.get_records_by_chat(chat_id) # แยกตามกลุ่ม
    
    target = update.message or update.callback_query.message
    if not records:
        await target.reply_text("📭 暂无记录 (当前聊天)。")
        return
    
    path = engine.create_report(records)
    await target.reply_photo(photo=open(path, 'rb'), caption="📊 总结报表")
    if os.path.exists(path): os.remove(path)

# --- 4. คำสั่งหลัก (Commands) ---
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("👋 **欢迎使用记账助手！**\n\n/add - 登记\n/report - 报表\n/renew - 续费\n/undo - 撤销\n/reset - 清空", parse_mode='Markdown')

async def renew_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    final_amt = round(150.0 + random.uniform(0.001, 0.999), 3)
    start_ts = int(time.time())
    
    db.save_payment_intent(user_id, chat_id, final_amt, start_ts)
    
    msg = (f"💳 **会员续费 (30天)**\n\n💵 请转账: `{final_amt}` USDT\n📍 网络: **TRC20**\n🏦 地址: `{os.getenv('MY_WALLET')}`\n\n⚠️ 请确保金额精确，系统将自动激活。")
    await update.message.reply_text(msg, parse_mode='Markdown')

async def undo_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_subscribed(update): return
    db.undo_last_record(update.effective_chat.id)
    await update.message.reply_text("🗑 已撤销当前聊天的最后一条记录。")
    await send_report_action(update)

async def reset_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_subscribed(update): return
    keyboard = [[InlineKeyboardButton("✅ 确定清空", callback_data='confirm_reset'), InlineKeyboardButton("❌ 取消", callback_data='cancel_reset')]]
    await update.message.reply_text("⚠️ **警告**: 确定要清空 **当前聊天** 的所有数据吗？", reply_markup=InlineKeyboardMarkup(keyboard))

async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data == 'confirm_reset':
        db.reset_all_records(query.message.chat_id)
        await query.message.edit_text("💥 数据已全部清空。")
    else:
        await query.message.edit_text("🚫 操作已取消。")

async def report_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_subscribed(update): return
    await send_report_action(update)

# --- 5. กระบวนการ /add (รองรับ Re-entry & Isolation) ---
async def start_add(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_subscribed(update): return ConversationHandler.END
    await update.message.reply_text("🧧 **开始登记**\n请回复 **日期** (例如: 4.12):")
    return DATE

async def get_date(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['date'] = update.message.text
    await update.message.reply_text("1️⃣ 一转二:")
    return T12

async def get_t12(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['t12'] = float(update.message.text)
    await update.message.reply_text("2️⃣ 二转三:")
    return T23

async def get_t23(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['t23'] = float(update.message.text)
    await update.message.reply_text("3️⃣ 当日压单:")
    return PDAY

async def get_pday(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['p_day'] = float(update.message.text)
    await update.message.reply_text("4️⃣ 总压单:")
    return PTOTAL

async def get_ptotal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['p_total'] = float(update.message.text)
    await update.message.reply_text("5️⃣ 客户数:")
    return CUST

async def get_cust(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['cust'] = int(update.message.text)
    await update.message.reply_text("6️⃣ 进账业绩 (日元):")
    return JPY

async def get_jpy(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['jpy'] = float(update.message.text)
    await update.message.reply_text("7️⃣ 进账业绩 (U):")
    return UPF

async def get_upf(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['u_perf'] = float(update.message.text)
    await update.message.reply_text("8️⃣ 车商费用 (%):")
    return FEE

async def get_fee(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['fee'] = float(update.message.text)
    await update.message.reply_text("9️⃣ 公司实际到账 (U):")
    return ACTUAL

async def get_actual(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        context.user_data['actual'] = float(update.message.text)
        db.save_record(context.user_data, update.effective_chat.id) # บันทึกแยก chat_id
        await update.message.reply_text("✅ 登记成功！")
        await send_report_action(update)
    except Exception as e:
        await update.message.reply_text(f"❌ 错误: {e}")
    return ConversationHandler.END

# --- 6. จบการทำงาน (Exit Conversation) ---
async def stop_nested(update: Update, context: ContextTypes.DEFAULT_TYPE):
    return ConversationHandler.END

# --- 7. Main Entry Point ---
if __name__ == '__main__':
    app = ApplicationBuilder().token(os.getenv('BOT_TOKEN')).build()
    
    if app.job_queue:
        app.job_queue.run_repeating(auto_payment_monitor, interval=60, first=10)
        print("✅ JobQueue is active")

    # ตั้งค่า Handlers ที่ข้ามไปมาได้ (allow_reentry=True)
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
        fallbacks=[CommandHandler('cancel', lambda u,c: ConversationHandler.END)],
        allow_reentry=True # กด /add ซ้ำเพื่อเริ่มใหม่ได้ทันที
    )
    
    # จัดลำดับ Handler: คำสั่งทั่วไปต้องอยู่ก่อน Conversation ถ้าจะให้มันข้ามได้
    app.add_handler(CommandHandler('report', report_command))
    app.add_handler(CommandHandler('renew', renew_command))
    app.add_handler(CommandHandler('undo', undo_command))
    app.add_handler(CommandHandler('reset', reset_command))
    app.add_handler(add_conv)
    app.add_handler(CommandHandler('start', start_command))
    app.add_handler(CallbackQueryHandler(callback_handler))
    
    print("🚀 Bot is running...")
    app.run_polling()
