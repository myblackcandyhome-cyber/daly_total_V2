import os
import pandas as pd
from PIL import Image, ImageDraw, ImageFont

class ReportEngine:
    def __init__(self, output_path="reports", font_path="fonts/msyh.ttc"):
        self.output_path = output_path
        self.font_path = font_path
        if not os.path.exists(self.output_path): 
            os.makedirs(self.output_path)

    def create_report(self, records):
        # 1. ตรวจสอบว่ามีข้อมูลหรือไม่
        if not records:
            return None
            
        df = pd.DataFrame(records)
        
        # ตั้งค่าขนาด
        width, row_h, head_h, header_row_h = 1350, 50, 100, 50
        img_h = head_h + header_row_h + (len(df) + 1) * row_h
        
        img = Image.new('RGB', (width, img_h), color='white')
        draw = ImageDraw.Draw(img)
        
        # 2. โหลดฟอนต์พร้อมระบบสำรอง
        try:
            font = ImageFont.truetype(self.font_path, 20)
            title_font = ImageFont.truetype(self.font_path, 35)
            bold_font = ImageFont.truetype(self.font_path, 22)
        except:
            print("⚠️ Font not found, using default.")
            font = title_font = bold_font = ImageFont.load_default()

        # --- ส่วนหัว (Title) ---
        draw.rectangle([0, 0, width, head_h], fill=(255, 255, 0))
        # คำนวณให้ Title อยู่กึ่งกลางเสมอ
        title_text = "总结报表"
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

        # --- ข้อมูลในตาราง (Rows) ---
        y = head_h + header_row_h
        for _, r in df.iterrows():
            curr_x = 0
            # จัดฟอร์แมตตัวเลขให้สวยงาม
            jpy = f"{float(r.get('jpy_amt', 0)):,.0f} 日元"
            perf = f"{float(r.get('u_perf', 0)):,.2f} (U)"
            fee = f"{float(r.get('fee_u', 0)):,.2f} (%)"
            act = f"{float(r.get('actual_u', 0)):,.2f} (U)"
            
            vals = [
                str(r.get('record_date', '-')), 
                str(int(r.get('t12_val', 0))), 
                str(int(r.get('t23_val', 0))), 
                str(int(r.get('p_day', 0))), 
                str(int(r.get('p_total', 0))), 
                str(int(r.get('cust_count', 0))),
                jpy, perf, fee, act
            ]
            
            for i, v in enumerate(vals):
                draw.rectangle([curr_x, y, curr_x + cols_w[i], y + row_h], outline="black")
                draw.text((curr_x + 10, y + 15), v, fill="black", font=font)
                curr_x += cols_w[i]
            y += row_h

        # --- แถวผลรวม (Summary Row) ---
        curr_x = 0
        # ป้องกัน error กรณีไม่มีข้อมูลแถวสุดท้าย
        last_p = str(int(df['p_total'].iloc[-1])) if not df.empty else "0"
        
        totals = [
            "总计", 
            f"{df['t12_val'].sum():.0f}", 
            f"{df['t23_val'].sum():.0f}", 
            f"{df['p_day'].sum():.0f}", 
            last_p, 
            f"{df['cust_count'].sum():.0f}", 
            f"{df['jpy_amt'].sum():,.0f} 日元", 
            f"{df['u_perf'].sum():,.2f} (U)", 
            "-", 
            f"{df['actual_u'].sum():,.2f} (U)"
        ]
        
        for i, v in enumerate(totals):
            draw.rectangle([curr_x, y, curr_x + cols_w[i], y + row_h], fill=(255, 255, 200), outline="black")
            draw.text((curr_x + 10, y + 10), v, fill="red", font=bold_font)
            curr_x += cols_w[i]

        path = os.path.join(self.output_path, "final_report.png")
        img.save(path)
        img.close() # ปิดไฟล์เพื่อคืนคืน Memory
        return path
