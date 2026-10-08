# Hướng dẫn đưa MAIL REG PRO bot lên mạng (chạy 24/7)

## Ý tưởng

- Code up lên **GitHub** (repo **riêng tư**).
- **Render.com** (free) chạy bot 24/7 bằng code đó.
- **UptimeRobot** (free) ping bot mỗi 5 phút để Render không cho bot "ngủ".
- Dữ liệu cũ (hòm thư, lịch sử OTP, cài đặt) được mang theo.

## Bước 1 — Sao lưu dữ liệu hiện tại

1. Mở Telegram, nhắn cho bot lệnh `/backup`.
2. Bot gửi lại file `mailbot_backup_....db` → **tải file này về máy**.
3. Gửi file đó cho mình (upload trong chat) để mình đưa vào bản deploy.

## Bước 2 — Tạo repo GitHub riêng tư

1. Vào https://github.com/new → đặt tên `mail-reg-pro-bot`
   → chọn **Private** → **Create repository**.
2. Cấp quyền cho mình ghi vào repo (như lần trước đã làm với repo checkkey).

## Bước 3 — Deploy lên Render

1. Vào https://render.com → **New +** → **Web Service** → chọn repo
   `mail-reg-pro-bot` → **Connect**.
2. Điền:
   - **Build Command:** `pip install -r requirements.txt`
   - **Start Command:** `python mail_reg_pro.py`
   - **Plan:** Free
3. Mục **Environment Variables** → **Add**:
   - Key `BOT_TOKEN`, Value = token bot của bạn (lấy từ @BotFather)
   - `DASH_KEY` Render tự sinh (trong file render.yaml) — không cần đụng.
4. **Create Web Service** → đợi build xong, hiện **Live** là bot đã chạy.
   ⚠️ **TẮT bot đang chạy trên máy tính đi** (đóng cửa sổ `chay_bot.bat`),
   vì Telegram chỉ cho 1 bot chạy 1 lúc — 2 nơi cùng chạy sẽ báo lỗi Conflict.

## Bước 4 — Giữ bot không ngủ (UptimeRobot, free)

1. Đăng ký https://uptimerobot.com (free).
2. **Add New Monitor** → loại **HTTP(s)** →
   URL: `https://ten-app-cua-ban.onrender.com/health` → **Create**.
   (thay `ten-app-cua-ban` bằng tên app Render của bạn)
3. Xong — cứ 5 phút nó ping 1 lần, bot không bao giờ ngủ.

## Dùng dashboard web từ xa

Mở: `https://ten-app-cua-ban.onrender.com/?key=XXXX`
(trong đó XXXX là giá trị `DASH_KEY` — xem trong Render →
service của bạn → mục Environment). Không có key đúng thì không ai
mở được dashboard của bạn.

## Khi deploy lại mà mất dữ liệu mới

Ổ đĩa của Render free bị reset mỗi lần deploy lại:
- Dữ liệu gốc (lúc up lên) vẫn còn (đã đưa sẵn vào repo).
- Dữ liệu mới tạo sau đó: bot **tự gửi backup về Telegram cho bạn hằng ngày**.
  Muốn khôi phục: tải file backup mới nhất → gửi `/restore` cho bot
  → kéo-thả file `.db` vào chat → bot tự khôi phục.
- Hoặc chủ động: trước khi bấm deploy lại, nhắn `/backup` để giữ bản mới nhất.
