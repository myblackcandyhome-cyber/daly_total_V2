import os
import pandas as pd
from PIL import Image, ImageDraw, ImageFont
import time  # ✅ เพิ่มบรรทัดนี้เพื่อแก้ไข Error: name 'time' is not defined

class ReportEngine:
    def __init__(self, output_path="reports", font_path="fonts/msyh.ttc"):
        self.output_path = output_path
        self.font_path = font_path
        # สร้างโฟลเดอร์สำหรับเก็บรูปภาพหากยังไม่มี
        if not os.path.exists(self.output_path): 
            os.makedirs(self.output_path)

    def create_report(self, records):
        # 1. ตรวจสอบว่ามีข้อมูลหรือไม่
        if not records:
            return None
            
        # สร้าง DataFrame
        df = pd.DataFrame(records)
        
        # ตั้งค่าขนาดกว้างและสูงของภาพ
        width, row_h, head_h, header_row_h = 1350, 50, 100, 50
        img_h = head_h + header_row_h + (len(df) + 1) * row_h
        
        img = Image.new('RGB', (width, img_h), color='white')
        draw = ImageDraw.Draw(img)
        
        # 2. โหลดฟอนต์พร้อมระบบสำรอง
        try:
            font = ImageFont.truetype(self.font_path, 18)
            title_font = ImageFont.truetype(self.font_path, 35)
            bold_font = ImageFont.truetype(self.font_path, 20)
        except:
            print("⚠️ Font not found, using default.")
            font = title_font = bold_font = ImageFont.load_default()

        # --- ส่วนหัว (Title) ---
        draw.rectangle([0, 0, width, head_h], fill=(255, 255, 0))
        title_text = "每日报表"
        t_w = draw.textlength(title_text, font=title_font)
        draw.text(((width - t_w) // 2, 25), title_text, fill=(255, 0, 0), font=title_font)

        # --- หัวตาราง (Headers) ---
        headers = ["日期", "一转二", "二转三", "当日压单", "总压单", "客户数", "日元", "业绩(U)", "车商(%)", "到账(U)"]
        cols_w = [130, 90, 90, 110, 110, 100, 210, 170, 170, 170]
        
        curr_x = 0
        for i, h in enumerate(headers):
            draw.rectangle([curr_x, head_h, curr_x + cols_w[i], head_h + header_row_h], fill=(240, 240, 240), outline="black")
            draw.text((curr_x + 10, head_h + 12), h, fill="black", font=bold_font)
            curr_x += cols_w[i]

        # --- ฟังก์ชันช่วยจัดการตัวเลข (Helper) ---
        def safe_float(val):
            try: return float(val) if val is not None else 0.0
            except: return 0.0

        # --- ข้อมูลในตาราง (Rows) ---
        y = head_h + header_row_h
        for _, r in df.iterrows():
            curr_x = 0
            
            jpy = f"{safe_float(r.get('jpy_amt')):,.0f} 日元"
            perf = f"{safe_float(r.get('u_perf')):,.2f} (U)"
            fee = f"{safe_float(r.get('fee_u')):,.2f} (%)"
            act = f"{safe_float(r.get('actual_u')):,.2f} (U)"
            
            vals = [
                str(r.get('record_date', '-')), 
                str(int(safe_float(r.get('t12_val')))), 
                str(int(safe_float(r.get('t23_val')))), 
                str(int(safe_float(r.get('p_day')))), 
                str(int(safe_float(r.get('p_total')))), 
                str(int(safe_float(r.get('cust_count')))),
                jpy, perf, fee, act
            ]
            
            for i, v in enumerate(vals):
                draw.rectangle([curr_x, y, curr_x + cols_w[i], y + row_h], outline="black")
                draw.text((curr_x + 10, y + 15), v, fill="black", font=font)
                curr_x += cols_w[i]
            y += row_h

        # --- แถวผลรวม (Summary Row) ---
        curr_x = 0
        last_p = str(int(safe_float(df['p_total'].iloc[-1]))) if not df.empty else "0"
        
        totals = [
            "总计", 
            f"{df['t12_val'].apply(safe_float).sum():.0f}", 
            f"{df['t23_val'].apply(safe_float).sum():.0f}", 
            f"{df['p_day'].apply(safe_float).sum():.0f}", 
            last_p, 
            f"{df['cust_count'].apply(safe_float).sum():.0f}", 
            f"{df['jpy_amt'].apply(safe_float).sum():,.0f} 日元", 
            f"{df['u_perf'].apply(safe_float).sum():,.2f} (U)", 
            "-", 
            f"{df['actual_u'].apply(safe_float).sum():,.2f} (U)"
        ]
        
        for i, v in enumerate(totals):
            draw.rectangle([curr_x, y, curr_x + cols_w[i], y + row_h], fill=(255, 255, 200), outline="black")
            draw.text((curr_x + 10, y + 10), v, fill="red", font=bold_font)
            curr_x += cols_w[i]

        # --- บันทึกไฟล์ ---
        # ใช้ timestamp เพื่อป้องกันชื่อไฟล์ซ้ำกันในกรณี gen พร้อมกันหลายกลุ่ม
        filename = f"report_{int(time.time())}.png"
        path = os.path.join(self.output_path, filename)
        
        img.save(path)
        img.close() # คืนทรัพยากร Memory
        return path
