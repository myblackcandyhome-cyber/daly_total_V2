import psycopg2
from psycopg2.extras import RealDictCursor
from datetime import datetime, timedelta
import os
import time

class Database:
    def __init__(self):
        self.db_url = os.getenv('DATABASE_URL')
        self.connect()

    def connect(self):
        """สร้างการเชื่อมต่อใหม่"""
        try:
            self.conn = psycopg2.connect(self.db_url)
            self.cursor = self.conn.cursor(cursor_factory=RealDictCursor)
            self._create_tables()
            print("✅ Database connected and tables checked")
        except Exception as e:
            print(f"❌ Database connection failed: {e}")

    def ensure_connection(self):
        """ตรวจสอบว่าการเชื่อมต่อยังใช้งานได้ไหม ถ้าไม่ได้ให้ต่อใหม่"""
        try:
            if self.conn.closed:
                self.connect()
        except:
            self.connect()

    def _create_tables(self):
        # ใช้ความสามารถของ PostgreSQL: สร้างตารางและ Index
        with self.conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS subscriptions (
                    user_id BIGINT PRIMARY KEY,
                    expiry_date TIMESTAMP NOT NULL
                );
                CREATE TABLE IF NOT EXISTS records (
                    id SERIAL PRIMARY KEY,
                    record_date VARCHAR(50),
                    t12_val NUMERIC(18,2) DEFAULT 0,
                    t23_val NUMERIC(18,2) DEFAULT 0,
                    p_day NUMERIC(18,2) DEFAULT 0,
                    p_total NUMERIC(18,2) DEFAULT 0,
                    cust_count INT DEFAULT 0,
                    jpy_amt NUMERIC(18,2) DEFAULT 0,
                    u_perf NUMERIC(18,2) DEFAULT 0,
                    fee_u NUMERIC(18,2) DEFAULT 0,
                    actual_u NUMERIC(18,2) DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS payments (
                    id SERIAL PRIMARY KEY,
                    user_id BIGINT NOT NULL,
                    amount NUMERIC(18,4) NOT NULL,
                    start_time INT NOT NULL,
                    status VARCHAR(20) DEFAULT 'pending',
                    txid VARCHAR(255) UNIQUE,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)
        self.conn.commit()

    def get_user_expiry(self, user_id):
        self.ensure_connection()
        try:
            self.cursor.execute("SELECT expiry_date FROM subscriptions WHERE user_id = %s", (user_id,))
            res = self.cursor.fetchone()
            return res['expiry_date'] if res else None
        except Exception as e:
            print(f"Error get_user_expiry: {e}")
            self.conn.rollback()
            return None

    def add_subscription(self, user_id, days=30):
        self.ensure_connection()
        try:
            current_expiry = self.get_user_expiry(user_id)
            start_from = current_expiry if current_expiry and current_expiry > datetime.now() else datetime.now()
            new_expiry = start_from + timedelta(days=days)
            
            self.cursor.execute("""
                INSERT INTO subscriptions (user_id, expiry_date) VALUES (%s, %s)
                ON CONFLICT (user_id) DO UPDATE SET expiry_date = EXCLUDED.expiry_date
            """, (user_id, new_expiry))
            self.conn.commit()
            return new_expiry
        except Exception as e:
            print(f"Error add_subscription: {e}")
            self.conn.rollback()
            return None

    def save_record(self, data):
        self.ensure_connection()
        try:
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
        except Exception as e:
            print(f"Error save_record: {e}")
            self.conn.rollback()

    def get_all_records(self):
        self.ensure_connection()
        self.cursor.execute("SELECT * FROM records ORDER BY id ASC")
        return self.cursor.fetchall()

    def undo_last_record(self):
        self.ensure_connection()
        try:
            self.cursor.execute("DELETE FROM records WHERE id = (SELECT MAX(id) FROM records)")
            self.conn.commit()
        except Exception as e:
            print(f"Error undo: {e}")
            self.conn.rollback()

    def reset_all_records(self):
        self.ensure_connection()
        try:
            self.cursor.execute("TRUNCATE TABLE records RESTART IDENTITY")
            self.conn.commit()
        except Exception as e:
            print(f"Error reset: {e}")
            self.conn.rollback()

    def save_payment_intent(self, user_id, amount, start_time):
        self.ensure_connection()
        try:
            self.cursor.execute("""
                INSERT INTO payments (user_id, amount, start_time, status) 
                VALUES (%s, %s, %s, 'pending')
            """, (user_id, amount, start_time))
            self.conn.commit()
        except Exception as e:
            print(f"Error save_payment_intent: {e}")
            self.conn.rollback()

    def get_all_pending_payments(self):
        self.ensure_connection()
        self.cursor.execute("SELECT * FROM payments WHERE status = 'pending'")
        return self.cursor.fetchall()

    def update_payment_status(self, pay_id, status, txid=None):
        self.ensure_connection()
        try:
            if txid:
                self.cursor.execute("UPDATE payments SET status = %s, txid = %s WHERE id = %s", (status, txid, pay_id))
            else:
                self.cursor.execute("UPDATE payments SET status = %s WHERE id = %s", (status, pay_id))
            self.conn.commit()
        except Exception as e:
            print(f"Error update_payment_status: {e}")
            self.conn.rollback()
