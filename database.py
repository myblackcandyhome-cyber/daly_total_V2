import psycopg2
from psycopg2.extras import RealDictCursor
from datetime import datetime, timedelta
import os

class Database:
    def __init__(self):
        """
        เชื่อมต่อกับ PostgreSQL โดยใช้ DATABASE_URL จาก environment variable
        """
        try:
            self.conn = psycopg2.connect(os.getenv('DATABASE_URL'))
            self.cursor = self.conn.cursor(cursor_factory=RealDictCursor)
            self._create_tables()
            print("✅ Database connected successfully")
        except Exception as e:
            print(f"❌ Database connection failed: {e}")

    def _create_tables(self):
        """
        สร้างตารางที่จำเป็นหากยังไม่มีในระบบ
        """
        # 1. ตารางสมาชิก (Subscriptions)
        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS subscriptions (
                user_id BIGINT PRIMARY KEY,
                expiry_date TIMESTAMP NOT NULL
            )
        """)
        
        # 2. ตารางบันทึกรายงาน (Records)
        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS records (
                id SERIAL PRIMARY KEY,
                record_date VARCHAR(50),
                t12_val FLOAT DEFAULT 0,
                t23_val FLOAT DEFAULT 0,
                p_day FLOAT DEFAULT 0,
                p_total FLOAT DEFAULT 0,
                cust_count INT DEFAULT 0,
                jpy_amt FLOAT DEFAULT 0,
                u_perf FLOAT DEFAULT 0,
                fee_u FLOAT DEFAULT 0,
                actual_u FLOAT DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # 3. ตารางรายการชำระเงิน (Payments)
        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS payments (
                id SERIAL PRIMARY KEY,
                user_id BIGINT NOT NULL,
                amount DECIMAL(18,4) NOT NULL,
                start_time INT NOT NULL,
                status VARCHAR(20) DEFAULT 'pending', -- pending, success, expired
                txid VARCHAR(255) UNIQUE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        self.conn.commit()

    # --- ส่วนของ Subscription (สมาชิก) ---
    def get_user_expiry(self, user_id):
        """ดึงวันหมดอายุของสมาชิก"""
        self.cursor.execute("SELECT expiry_date FROM subscriptions WHERE user_id = %s", (user_id,))
        res = self.cursor.fetchone()
        return res['expiry_date'] if res else None

    def add_subscription(self, user_id, days=30):
        """เพิ่มจำนวนวันใช้งาน (บวกเพิ่มจากวันหมดอายุเดิมหรือเริ่มใหม่วันนี้)"""
        current_expiry = self.get_user_expiry(user_id)
        # ถ้ายังไม่หมดอายุให้เริ่มนับต่อจากของเดิม ถ้าหมดแล้วให้เริ่มนับจากตอนนี้
        start_from = current_expiry if current_expiry and current_expiry > datetime.now() else datetime.now()
        new_expiry = start_from + timedelta(days=days)
        
        self.cursor.execute("""
            INSERT INTO subscriptions (user_id, expiry_date) VALUES (%s, %s)
            ON CONFLICT (user_id) DO UPDATE SET expiry_date = EXCLUDED.expiry_date
        """, (user_id, new_expiry))
        self.conn.commit()
        return new_expiry

    # --- ส่วนของ Records (จัดการข้อมูลรายงาน) ---
    def save_record(self, data):
        """บันทึกข้อมูลรายงานลงฐานข้อมูล"""
        sql = """
            INSERT INTO records (record_date, t12_val, t23_val, p_day, p_total, cust_count, jpy_amt, u_perf, fee_u, actual_u) 
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """
        self.cursor.execute(sql, (
            data.get('date'), data.get('t12'), data.get('t23'), 
            data.get('p_day'), data.get('p_total'), data.get('cust'), 
            data.get('jpy'), data.get('u_perf'), data.get('fee'), data.get('actual')
        ))
        self.conn.commit()

    def get_all_records(self):
        """ดึงข้อมูลรายงานทั้งหมดเพื่อส่งให้ Report Engine"""
        self.cursor.execute("SELECT * FROM records ORDER BY id ASC")
        return self.cursor.fetchall()

    def undo_last_record(self):
        """ลบรายการรายงานล่าสุด (Undo)"""
        self.cursor.execute("DELETE FROM records WHERE id = (SELECT MAX(id) FROM records)")
        self.conn.commit()

    def reset_all_records(self):
        """ล้างข้อมูลในตารางรายงานทั้งหมด (Reset)"""
        self.cursor.execute("TRUNCATE TABLE records RESTART IDENTITY")
        self.conn.commit()

    # --- ส่วนของ Payments (ตรวจสอบยอดโอน) ---
    def save_payment_intent(self, user_id, amount, start_time):
        """บันทึกความจำนงในการโอนเงิน (Order)"""
        self.cursor.execute("""
            INSERT INTO payments (user_id, amount, start_time, status) 
            VALUES (%s, %s, %s, 'pending')
        """, (user_id, amount, start_time))
        self.conn.commit()

    def get_all_pending_payments(self):
        """ดึงรายการที่รอยืนยันทั้งหมดสำหรับ Job Queue"""
        self.cursor.execute("SELECT * FROM payments WHERE status = 'pending'")
        return self.cursor.fetchall()

    def update_payment_status(self, pay_id, status, txid=None):
        """อัปเดตสถานะการชำระเงิน (Success / Expired)"""
        if txid:
            self.cursor.execute("UPDATE payments SET status = %s, txid = %s WHERE id = %s", (status, txid, pay_id))
        else:
            self.cursor.execute("UPDATE payments SET status = %s WHERE id = %s", (status, pay_id))
        self.conn.commit()

    def __del__(self):
        """ปิดการเชื่อมต่อเมื่อ Object ถูกทำลาย"""
        try:
            self.cursor.close()
            self.conn.close()
        except:
            pass
