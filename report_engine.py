import os
import pandas as pd
from PIL import Image, ImageDraw, ImageFont

class ReportEngine:
    def __init__(self, output_path="reports", font_path="fonts/msyh.ttc"):
        self.output_path = output_path
        self.font_path = font_path
        if not os.path.exists(self.output_path): os.makedirs(self.output_path)

    def create_report(self, records):
        df = pd.DataFrame(records)
        width, row_h, head_h, header_row_h = 1350, 50, 100, 50
        img_h = head_h + header_row_h + (len(df) + 1) * row_h
        img = Image.new('RGB', (width, img_h), color='white')
        draw = ImageDraw.Draw(img)
        
        try:
            font = ImageFont.truetype(self.font_path, 20)
            title_font = ImageFont.truetype(self.font_path, 35)
            bold_font = ImageFont.truetype(self.font_path, 22)
        except:
            font = title_font = bold_font = ImageFont.load_default()

        # ส่วนหัว
        draw.rectangle([0, 0, width, head_h], fill=(255, 255, 0))
        draw.text((width//2 - 100, 25), "总结报表", fill=(255, 0, 0), font=title_font)

        headers = ["日期", "一转二", "二转三", "当日压单", "总压单", "客户数", "日元", "业绩(U)", "车商(%)", "到账(U)"]
        cols_w = [130, 90, 90, 110, 110, 100, 210, 170, 170, 170]
        
        curr_x = 0
        for i, h in enumerate(headers):
            draw.rectangle([curr_x, head_h, curr_x + cols_w[i], head_h + header_row_h], fill=(240, 240, 240), outline="black")
            draw.text((curr_x + 10, head_h + 12), h, fill="black", font=bold_font)
            curr_x += cols_w[i]

        y = head_h + header_row_h
        for _, r in df.iterrows():
            curr_x = 0
            jpy = f"{float(r['jpy_amt']):,.0f} 日元" if r['jpy_amt'] != 0 else "0"
            perf = f"{float(r['u_perf']):,.2f} (U)" if r['u_perf'] != 0 else "0.00"
            fee = f"{float(r['fee_u']):,.2f} (%)" if r['fee_u'] != 0 else "0.00"
            act = f"{float(r['actual_u']):,.2f} (U)" if r['actual_u'] != 0 else "0.00"
            
            vals = [str(r['record_date']), str(int(r['t12_val'])), str(int(r['t23_val'])), 
                    str(int(r['p_day'])), str(int(r['p_total'])), str(int(r['cust_count'])),
                    jpy, perf, fee, act]
            
            for i, v in enumerate(vals):
                draw.rectangle([curr_x, y, curr_x + cols_w[i], y + row_h], outline="black")
                draw.text((curr_x + 10, y + 15), v, fill="black", font=font)
                curr_x += cols_w[i]
            y += row_h

        # แถวผลรวม
        curr_x = 0
        last_p = str(int(df['p_total'].iloc[-1])) if not df.empty else "0"
        sum_jpy = f"{df['jpy_amt'].sum():,.0f} 日元" if df['jpy_amt'].sum() != 0 else "0"
        sum_perf = f"{df['u_perf'].sum():,.2f} (U)" if df['u_perf'].sum() != 0 else "0.00"
        sum_act = f"{df['actual_u'].sum():,.2f} (U)" if df['actual_u'].sum() != 0 else "0.00"
        
        totals = ["总计", str(df['t12_val'].sum()), str(df['t23_val'].sum()), str(df['p_day'].sum()), 
                  last_p, str(df['cust_count'].sum()), sum_jpy, sum_perf, "-", sum_act]
        
        for i, v in enumerate(totals):
            draw.rectangle([curr_x, y, curr_x + cols_w[i], y + row_h], fill=(255, 255, 200), outline="black")
            draw.text((curr_x + 10, y + 10), v, fill="red", font=bold_font)
            curr_x += cols_w[i]

        path = os.path.join(self.output_path, "final_report.png")
        img.save(path)
        return path
