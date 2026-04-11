import os
import random
import time
import requests
import asyncio
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

# โหลดค่า Config
load_dotenv()
db = Database()
engine = ReportEngine()

# กำหนดสถานะสำหรับ ConversationHandler
DATE, T12, T23, PDAY, PTOTAL, CUST, JPY, UPF, FEE, ACTUAL = range(10)

# --- ฟังก์ชันตรวจสอบ TRONSCAN API ---
def check_tronscan(target_amount, start_time):
    """
    ตรวจสอบธุรกรรม USDT-TRC20 ขาเข้าที่มียอดและเวลาตรงตามกำหนด
    """
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
            # ตรวจสอบว่าเป็น USDT (Contract ID ของ USDT)
            if tx['tokenInfo']['tokenId'] == 'TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t':
                amount_received = float(tx['quant']) / 1_000_000
                tx_time = tx['block_ts'] / 1000 # แปลง ms เป็นวินาที
                
                # ตรวจสอบยอดเงิน (เผื่อความคลาดเคลื่อน float นิดหน่อย) และเวลาโอนต้องหลังสร้าง Order
                if abs(amount_received - target_amount) < 0.0001 and tx_time >= start_time:
                    return True, tx['transaction_id']
    except Exception as e:
        print(f"TronScan API Error: {e}")
    return False, None

# --- Background Task: ตรวจสอบยอดเงินอัตโนมัติ ---
async def auto_payment_monitor(context: ContextTypes.DEFAULT_TYPE):
    """
    ฟังก์ชันที่ทำงานเบื้องหลังเพื่อตรวจเช็คยอดเงินที่ค้างชำระ (Pending) ทุกๆ 60 วินาที
    """
    # ดึงรายการที่ยัง pending จากฐานข้อมูล
    # หมายเหตุ: คุณต้องเพิ่ม method get_all_pending_payments ใน database.py
    pending_list = db.get_all_pending_payments()
    
    for pay in pending_list:
        # 1. เช็คว่าหมดเวลา 30 นาทีหรือยัง (1800 วินาที)
        if int(time.time()) - pay['start_time'] > 1800:
            db.update_payment_status(pay['id'], 'expired')
            continue
        
        # 2. ตรวจสอบกับ Blockchain
        success, txid = check_tronscan(float(pay['amount']), pay['start_time'])
        
        if success:
            # อัปเดตสถานะในฐานข้อมูล
            db.update_payment_status(pay['id'], 'success', txid)
            # เพิ่มวันใช้งาน 30 วัน
            new_exp = db.add_subscription(pay['user_id'], days=30)
            
            # 3. แจ้งเตือนผู้ใช้งานอัตโนมัติ
            try:
                msg = (
                    f"🎊 **自动充值成功！ (เติมเงินสำเร็จ)**\n\n"
                    f"✅ 系统已检测到转账: `{pay['amount']}` USDT\n"
                    f"📅 到期时间: `{new_exp.strftime('%Y-%m-%d %H:%M:%S')}`\n"
                    f"🚀 您现在可以继续使用บอทได้แล้วครับ"
                )
                await context.bot.send_message(chat_id=pay['user_id'], text=msg, parse_mode='Markdown')
            except Exception as e:
                print(f"แจ้งเตือนผู้ใช้ {pay['user_id']} ล้มเหลว: {e}")

# --- Middleware & Helper ---
async def is_subscribed(update: Update):
    expiry = db.get_user_expiry(update.effective_user.id)
    if not expiry or expiry < datetime.now():
        await update.message.reply_text("❌ 服务已到期。请使用 /renew 续费 (150 USDT/30天)")
        return False
    return True

# --- Commands ---
async def renew_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    # สุ่มทศนิยม 3 ตำแหน่งเพื่อให้ยอดเงินเป็นเอกลักษณ์
    final_amt = round(150.0 + random.uniform(0.001, 0.999), 3)
    start_ts = int(time.time())
    
    db.save_payment_intent(user_id, final_amt, start_ts)
    
    text = (
        f"💳 **服务续费 (150 USDT / 30天)**\n\n"
        f"👤 用户 ID: `{user_id}`\n"
        f"💵 请转账金额: `{final_amt}` USDT\n"
        f"📍 地址 (TRC20): `{os.getenv('MY_WALLET')}`\n\n"
        f"⏳ **有效期 30 分钟**\n"
        f"⚠️ **无需操作：** 转账完成后，系统将自动检测并为您开通，通常需要 1-2 分钟。"
    )
    await update.message.reply_text(text, parse_mode='Markdown')

async def undo_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_subscribed(update): return
    db.undo_last_record()
    await update.message.reply_text("🗑 已撤销最后一条记录 (Undo Success)")
    await send_report(update, context)

async def reset_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_subscribed(update): return
    keyboard = [[
        InlineKeyboardButton("✅ 确定 (Confirm)", callback_data='confirm_reset'),
        InlineKeyboardButton("❌ 取消 (Cancel)", callback_data='cancel_reset')
    ]]
    await update.message.reply_text("⚠️ 确定要清空所有记录吗？", reply_markup=InlineKeyboardMarkup(keyboard))

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query.data == 'confirm_reset':
        db.reset_all_records()
        await query.message.edit_text("💥 所有记录已清空")
    elif query.data == 'cancel_reset':
        await query.message.edit_text("🚫 已取消")

# --- Conversation: /add ---
async def start_add(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_subscribed(update): return ConversationHandler.END
    await update.message.reply_text("🧧 **开始登记**\n请输入 **日期** (例如: 4月12日):")
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
    context.user_data['actual'] = float(update.message.text)
    db.save_record(context.user_data)
    await update.message.reply_text("✅ 登记成功!")
    await send_report(update, context)
    return ConversationHandler.END

async def send_report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_subscribed(update): return
    records = db.get_all_records()
    if not records:
        msg = update.message if update.message else update.callback_query.message
        await msg.reply_text("📭 没有记录")
        return
    path = engine.create_report(records)
    msg = update.message if update.message else update.callback_query.message
    await msg.reply_photo(photo=open(path, 'rb'), caption="总结报表")
    if os.path.exists(path): os.remove(path)

# --- บูตระบบ ---
if __name__ == '__main__':
    app = ApplicationBuilder().token(os.getenv('BOT_TOKEN')).build()
    
    # ตั้งค่า Background Job ตรวจสอบเงินทุก 60 วินาที
    job_queue = app.job_queue
    job_queue.run_repeating(auto_payment_monitor, interval=60, first=10)
    
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
    app.add_handler(CommandHandler('undo', undo_command))
    app.add_handler(CommandHandler('reset', reset_command))
    app.add_handler(CommandHandler('renew', renew_command))
    app.add_handler(CommandHandler('report', send_report))
    app.add_handler(CallbackQueryHandler(handle_callback))
    
    print("🚀 บอทกำลังทำงานและเฝ้าดูยอดเงินโอน...")
    app.run_polling()
