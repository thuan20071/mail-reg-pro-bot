# MAIL REG PRO v5.0 📧 • TM MEDIA

Bot Telegram tạo **mail tạm** xịn nhất: tạo mail nhanh, đuôi đẹp, nhận OTP ổn định,
không spam tin nhắn.

## Điểm mới v5.0

- 💎 **Đuôi đẹp ưu tiên**: domain đẹp hiện đầu danh sách kèm dấu 💎 (laafd.com, vjuum.com, txcct.com...)
- 🛡️ **Nhận mail không lỗi**: tự retry 3 lần khi provider chập chờn; provider nào fail liên tiếp
  sẽ tự nghỉ 5 phút rồi thử lại, không treo bot
- 📦 **Gom thông báo (chống spam)**: nhiều mail mới trong 1 lượt quét → gom thành **1 tin duy nhất**
  (tắt/mở trong ⚙️ Cài Đặt)
- 🖥️ **Web Dashboard**: mở `http://127.0.0.1:8092` trên máy chạy bot → xem tất cả hộp thư,
  bấm đọc từng mail, OTP tự tách sẵn chạm để copy, tự làm mới 20s
- Giữ nguyên toàn bộ tính năng cũ: 3 provider (mail.tm / guerrilla / 1secmail) tự failover,
  tạo nhiều mail, đăng nhập, check OTP, lịch sử OTP, xuất file, sao lưu, thống kê...

## Chạy (Windows)

1. Cài **Python 3.10+** (python.org, tick **Add python.exe to PATH**)
2. `pip install python-telegram-bot httpx beautifulsoup4 flask`
3. Tạo bot qua **@BotFather**, dán token vào `BOT_TOKEN` trong file `mail_reg_pro.py`
   (ADMIN_ID = 5932089197 đã điền sẵn)
4. Nhấp đúp **`chay_bot.bat`**

## Lưu ý

- Token cũ từng lộ trong chat → vào @BotFather → `/revoke` để lấy token mới cho chắc.
- Bot chạy polling: chỉ chạy 1 instance 1 lúc (đã có lock chống chạy trùng).
