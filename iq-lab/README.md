# IQ Lab: AI Trading Research Lab (IQ Option Practice)

ระบบวิจัยการเทรดบน IQ Option **บัญชี Practice เท่านั้น**: AI สแกนตลาด → ยิงสัญญาณ → Claude วางไม้ใน Chrome →
บันทึก Trading Journal ลง Google Sheets → Live Dashboard → ทบทวนรายวันเพื่อเพิ่ม win rate
ใช้เงินจริง**เฉพาะเมื่อผ่าน gate ทางสถิติ** (≥500 ไม้, win rate ≥58%, 95% lower bound > breakeven 54.1%)

```
Yahoo price feed ─► Signal engine (S1/S2/S3) ─► SQLite journal ─┬─► Live dashboard  http://localhost:8765
                                                                 ├─► Google Sheets (Apps Script webhook)
                                                                 └─► MCP server iq-lab ◄─► Claude + Claude in Chrome ─► IQ Option PRACTICE
```

## ⚡ Quick start (เร็วที่สุด)
1. Google Sheet: วาง `apps_script/Code.gs` ใน Extensions → Apps Script → Run `setup` → Deploy เป็น Web app แล้ว copy URL `/exec`
2. Mac/Linux: `./start.sh "<URL /exec>"` · Windows: `start.bat "<URL /exec>"`
   (ติดตั้ง → test → backtest → เปิด engine + dashboard ให้ในคำสั่งเดียว)
3. เปิด Claude ในโฟลเดอร์ `iq-lab/` แล้วพิมพ์ **"start trading session"** (IQ ต้องอยู่ที่ Practice)

## ติดตั้ง (ครั้งเดียว ~20 นาที)

**1. Python 3.11+** บนเครื่องที่เปิด Chrome ไว้
```bash
git clone -b claude/tender-maxwell-tjgmrq https://github.com/indyholdings/legal.git && cd legal/iq-lab
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python -m pytest -q tests                            # ต้องผ่านทั้งหมด
```

**2. Google Sheets journal**: ไฟล์ "IQ Lab Journal" สร้างไว้ใน Drive แล้ว
1. เปิดไฟล์ → Extensions → Apps Script → วางโค้ดจาก `apps_script/Code.gs` → Save
2. เลือกฟังก์ชัน `setup` → Run → อนุญาตสิทธิ์ (สร้าง tabs: Trades, Watchlist, Daily_Review, Rules, Stats)
3. Deploy → New deployment → Web app → Execute as **Me**, Access **Anyone with the link** → Deploy
4. คัดลอก URL `.../exec` แล้วตั้งค่า:
```bash
export IQLAB_SHEETS_WEBHOOK="https://script.google.com/macros/s/XXXX/exec"   # Windows: setx IQLAB_SHEETS_WEBHOOK "..."
```

**3. Claude + Chrome**
- ติดตั้ง extension **Claude in Chrome** แล้ว login IQ Option → สลับเป็น **Practice account**
- เปิด Claude Code (หรือ Claude desktop) ในโฟลเดอร์ `iq-lab/`: `.mcp.json` จะโหลด MCP server `iq-lab` ให้อัตโนมัติ

## ใช้งานรายวัน

| ขั้น | คำสั่ง | ทำอะไร |
|---|---|---|
| 0 (ครั้งแรก) | `python -m iqlab backtest --session-only` | ทดสอบ S1–S3 กับข้อมูลย้อนหลัง 7–60 วัน → รู้ใน 2 นาทีว่า setup ไหนน่าสนใจ |
| 1 | `python -m iqlab run` | Engine สแกนทุก 60 วิ + บันทึก paper trade + sync Sheets + เปิด dashboard ที่ http://localhost:8765 |
| 2 | ใน Claude: **"start trading session"** | Skill `iq-trader` วางไม้ตามสัญญาณบน IQ Practice ผ่าน Chrome และบันทึกผลจริงจาก IQ |
| 3 | ใน Claude: **"daily review"** | วิเคราะห์ไม้ที่แพ้ เขียน lesson เสนอปรับกฎได้ ≤1 ค่า |
| 4 | `python -m iqlab rules approve <v>` | **คุณ**อนุมัติการปรับกฎ (AI แก้กฎเองไม่ได้) |
| | `python -m iqlab stats --scope iq` | ดูสถิติ + ความคืบหน้า gate |

ข่าวแรง (NFP, CPI, FOMC): บอก Claude ว่า "add blackout 2026-10-10 19:30 NFP" → ระบบหยุดยิงสัญญาณ ±30 นาที

## Setups (rules v1 แก้ได้ผ่าน proposal เท่านั้น)

| Setup | TF | Expiry | Logic |
|---|---|---|---|
| S1 Trend Pullback | 5m | 15m | EMA50 ชี้ทิศ, แท่งก่อน pullback แตะ EMA20, แท่งปัจจุบันทะลุ high/low และ RSI ตัด 50 |
| S2 Mean Reversion | 1m | 5m | ราคาหลุด Bollinger 2.5σ + RSI(2) <5/>95 ในตลาด sideway (ADX<20) |
| S3 S/R Rejection | 5m | 10m | ไส้เทียนยาว ≥2× body ที่แนวรับ/ต้าน 8 ชม. |

Assets: EUR/USD, GBP/USD, USD/JPY, EUR/JPY, Gold (ไม่เทรด OTC) · Session 19:00–23:00 น. (ปรับด้วย `IQLAB_SESSION=19,23`)

## Risk rules (ใช้ใน demo ด้วย เพื่อให้ผลวิจัยตรงกับการเทรดจริง)
- ไม้ละ 1% ของทุน (`IQLAB_BALANCE`, `IQLAB_STAKE_PCT`) · สูงสุด 25 ไม้/วัน · ถือได้ 1 ไม้ต่อ asset
- หยุดทั้งวันเมื่อ: แพ้ติดกัน 3 ไม้ / ขาดทุน −3% / กำไรถึง +5%
- Payout < 80% → ข้าม · สัญญาณเก่ากว่า 90 วินาที → ข้าม

## Paper vs IQ
ทุกสัญญาณถูกบันทึกเป็น **paper trade** (ตัดสินผลจากราคา feed) แม้ Claude ไม่ได้วางไม้จริง ทำให้เก็บสถิติได้เร็ว
ไม้ที่วางบน IQ จะมี `iq_result` แยก → ถ้า win rate ของ IQ ต่ำกว่า paper แสดงว่าเสียจาก latency หรือราคาที่ต่างกัน ต้องแก้ก่อนผ่าน gate

## ข้อจำกัดที่ต้องรู้
- Yahoo feed เป็น endpoint สาธารณะไม่เป็นทางการ ราคาอาจต่างจาก IQ หลาย pip และอาจหน่วง
- การคลิกผ่าน Claude in Chrome ใช้เวลา 10–30 วินาทีต่อไม้ จึงใช้ expiry ≥5 นาทีเท่านั้น
- ผล backtest ≠ อนาคต gate 500 ไม้คือเกณฑ์จริง
- การ automate บน IQ Option อาจขัด ToS ของแพลตฟอร์ม ระบบนี้ออกแบบให้ใช้กับบัญชี Practice เท่านั้น
