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

# --- ฟังก์ชันตรวจสอบ TRONSCAN API ---
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
            # ตรวจสอบว่าเป็น USDT (Contract: TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t)
            if tx['tokenInfo']['tokenId'] == 'TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t':
                amount_received = float(tx['quant']) / 1_000_000
                tx_time = tx['block_ts'] / 1000 
                
                # ตรวจยอดโอนตรงกัน (ทศนิยม 3 ตำแหน่ง) และต้องโอนหลังสร้าง Order
                if abs(amount_received - target_amount) < 0.0001 and tx_time >= start_time:
                    return True, tx['transaction_id']
    except Exception as e:
        print(f"TronScan Error: {e}")
    return False, None

# --- ระบบตรวจสอบยอดเงินอัตโนมัติ (Background Job) ---
async def auto_payment_monitor(context: ContextTypes.DEFAULT_TYPE):
    """รันทุก 60 วินาที เพื่อเช็ครายการ Pending ในฐานข้อมูล"""
    pending_list = db.get_all_pending_payments()
    
    for pay in pending_list:
        # หากเกิน 30 นาที ให้ถือว่าหมดอายุ
        if int(time.time()) - pay['start_time'] > 1800:
            db.update_payment_status(pay['id'], 'expired')
            continue
        
        success, txid = check_tronscan(float(pay['amount']), pay['start_time'])
        
        if success:
            db.update_payment_status(pay['id'], 'success', txid)
            new_exp = db.add_subscription(pay['user_id'], days=30)
            
            # แจ้งเตือนผู้ใช้งานทันที
            try:
                msg = (
                    f"🎊 **自动充值成功！**\n\n"
                    f"✅ 检测到转账: `{pay['amount']}` USDT\n"
                    f"📅 有效期至: `{new_exp.strftime('%Y-%m-%d %H:%M:%S')}`\n"
                    f"🚀 您现在可以正常使用所有功能了。"
                )
                await context.bot.send_message(chat_id=pay['user_id'], text=msg, parse_mode='Markdown')
            except Exception as e:
                print(f"Notification Error: {e}")

# --- Middleware ตรวจสอบสิทธิ์สมาชิก ---
async def is_subscribed(update: Update):
    expiry = db.get_user_expiry(update.effective_user.id)
    if not expiry or expiry < datetime.now():
        await update.message.reply_text("❌ **服务已到期**\n请使用 /renew 续费 (150 USDT/30天)")
        return False
    return True

# --- คำสั่งพื้นฐาน ---
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("👋 欢迎使用记账助手！\n\n可用指令:\n/add - 登记数据\n/report - 生成报表\n/renew - 续费会员\n/undo - 撤销记录\n/reset - 清空数据")

async def renew_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    # สุ่มทศนิยมเพื่อให้ยอดโอนไม่ซ้ำกัน
    final_amt = round(150.0 + random.uniform(0.001, 0.999), 3)
    start_ts = int(time.time())
    db.save_payment_intent(user_id, final_amt, start_ts)
    
    msg = (
        f"💳 **会员续费 (30天)**\n\n"
        f"💵 请转账: `{final_amt}` USDT\n"
        f"📍 网络: **TRC20**\n"
        f"🏦 地址: `{os.getenv('MY_WALLET')}`\n\n"
        f"⚠️ **重要提示:**\n"
        f"- 必须转账**精确金额**\n"
        f"- 系统会自动监测，无需发送截图\n"
        f"- 请在 30 分钟内完成转账"
    )
    await update.message.reply_text(msg, parse_mode='Markdown')

async def undo_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_subscribed(update): return
    db.undo_last_record()
    await update.message.reply_text("🗑 已撤销最后一条记录。")
    await send_report_action(update)

async def reset_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_subscribed(update): return
    keyboard = [[
        InlineKeyboardButton("✅ 确定清空", callback_data='confirm_reset'),
        InlineKeyboardButton("❌ 取消", callback_data='cancel_reset')
    ]]
    await update.message.reply_text("⚠️ **警告**: 确定要清空所有数据吗？", reply_markup=InlineKeyboardMarkup(keyboard))

async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data == 'confirm_reset':
        db.reset_all_records()
        await query.message.edit_text("💥 数据已全部清空。")
    else:
        await query.message.edit_text("🚫 操作已取消。")

# --- กระบวนการกรอกข้อมูล /add ---
async def start_add(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_subscribed(update): return ConversationHandler.END
    await update.message.reply_text("🧧 **开始登记**\n请输入 **日期** (例如: 4.12):")
    return DATE

async def get_date(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['date'] = update.message.text
    await update.message.reply_text("1️⃣ 一转二 (数字):")
    return T12

async def get_t12(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['t12'] = float(update.message.text)
    await update.message.reply_text("2️⃣ 二转三 (数字):")
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
    await update.message.reply_text("5️⃣ 客户数 (整数):")
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
    context.user_data['actual'] = float(update.message.text)
    db.save_record(context.user_data)
    await update.message.reply_text("✅ 登记成功！")
    await send_report_action(update)
    return ConversationHandler.END

# --- ฟังก์ชันส่งรายงานภาพ ---
async def send_report_action(update):
    records = db.get_all_records()
    if not records:
        await (update.message or update.callback_query.message).reply_text("📭 暂无记录。")
        return
    path = engine.create_report(records)
    await (update.message or update.callback_query.message).reply_photo(photo=open(path, 'rb'), caption="📊 总结报表")
    if os.path.exists(path): os.remove(path)

async def report_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_subscribed(update): return
    await send_report_action(update)

# --- เริ่มรันบอท ---
if __name__ == '__main__':
    app = ApplicationBuilder().token(os.getenv('BOT_TOKEN')).build()
    
    # รันระบบตรวจสอบเงินอัตโนมัติเบื้องหลัง
    app.job_queue.run_repeating(auto_payment_monitor, interval=60, first=10)
    
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
    app.add_handler(CommandHandler('start', start_command))
    app.add_handler(CommandHandler('renew', renew_command))
    app.add_handler(CommandHandler('report', report_command))
    app.add_handler(CommandHandler('undo', undo_command))
    app.add_handler(CommandHandler('reset', reset_command))
    app.add_handler(CallbackQueryHandler(callback_handler))
    
    print("🚀 Bot is running with Auto-Payment monitor...")
    app.run_polling()
