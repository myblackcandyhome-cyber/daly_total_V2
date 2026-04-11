import psycopg2
from psycopg2.extras import RealDictCursor
from datetime import datetime, timedelta
import os

class Database:
    def __init__(self):
        self.conn = psycopg2.connect(os.getenv('DATABASE_URL'))
        self.cursor = self.conn.cursor(cursor_factory=RealDictCursor)
        self._create_tables()

    def _create_tables(self):
        # ตารางสมาชิก (แยกตาม user_id)
        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS subscriptions (
                user_id BIGINT PRIMARY KEY,
                expiry_date TIMESTAMP
            )
        """)
        # ตารางรายงานยอด
        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS records (
                id SERIAL PRIMARY KEY,
                record_date VARCHAR(50),
                t12_val FLOAT, t23_val FLOAT, p_day FLOAT, p_total FLOAT,
                cust_count INT, jpy_amt FLOAT, u_perf FLOAT, fee_u FLOAT, actual_u FLOAT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        # ตารางชำระเงิน (เก็บประวัติแยกคน)
        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS payments (
                id SERIAL PRIMARY KEY,
                user_id BIGINT,
                amount DECIMAL(18,4),
                start_time INT,
                status VARCHAR(20) DEFAULT 'pending',
                txid VARCHAR(255) UNIQUE
            )
        """)
        self.conn.commit()

    def get_user_expiry(self, user_id):
        self.cursor.execute("SELECT expiry_date FROM subscriptions WHERE user_id = %s", (user_id,))
        res = self.cursor.fetchone()
        return res['expiry_date'] if res else None

    def add_subscription(self, user_id, days=30):
        current_expiry = self.get_user_expiry(user_id)
        start_from = current_expiry if current_expiry and current_expiry > datetime.now() else datetime.now()
        new_expiry = start_from + timedelta(days=days)
        self.cursor.execute("""
            INSERT INTO subscriptions (user_id, expiry_date) VALUES (%s, %s)
            ON CONFLICT (user_id) DO UPDATE SET expiry_date = EXCLUDED.expiry_date
        """, (user_id, new_expiry))
        self.conn.commit()
        return new_expiry

    def save_payment_intent(self, user_id, amount, start_time):
        self.cursor.execute("INSERT INTO payments (user_id, amount, start_time) VALUES (%s, %s, %s)", 
                            (user_id, amount, start_time))
        self.conn.commit()

    def save_record(self, data):
        sql = """INSERT INTO records (record_date, t12_val, t23_val, p_day, p_total, cust_count, jpy_amt, u_perf, fee_u, actual_u) 
                 VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)"""
        self.cursor.execute(sql, (data['date'], data['t12'], data['t23'], data['p_day'], data['p_total'], 
                                  data['cust'], data['jpy'], data['u_perf'], data['fee'], data['actual']))
        self.conn.commit()

    def get_all_records(self):
        self.cursor.execute("SELECT * FROM records ORDER BY id ASC")
        return self.cursor.fetchall()
