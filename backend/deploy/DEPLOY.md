# استقرار سرور FastAPI (Skool Explorer)

چک‌لیست کامل برای بردن همین پوشه‌ی `server-fastapi` روی سرور لینوکس.

---

## ۱. فایل‌هایی که می‌بری

کل پوشه‌ی `server-fastapi/` به‌جز `venv/` و `__pycache__/`:

```
server-fastapi/
├── app/            ← کد
├── tests/
├── requirements.txt
├── pytest.ini
├── .env            ← روی سرور از نو می‌سازی (بند ۲)
└── deploy/         ← nginx + systemd (این پوشه)
```

`.gitignore` خودش venv و .env را کنار می‌گذارد؛ اگر با git می‌بری، فقط clone کن.

## ۲. فایل `.env` سرور (مهم‌ترین بخش)

روی سرور در ریشه‌ی `server-fastapi/.env` بساز — **هیچ مقداری را از لوکال کپی نکن**:

```ini
PGHOST=<آی‌پی یا نام سرویس دیتابیس>       # localhost فقط وقتی DB همان سرور است
PGPORT=5432
PGUSER=<user دیتابیس>
PGPASSWORD=<پسورد قوی مخصوص سرور>
PGDATABASE=pouri

PORT=3001                                  # پورت داخلی؛ nginx جلویش می‌نشیند

AUTH_JWT_SECRET=<یک مقدار جدید تصادفی>     # هرگز مقدار لوکال را استفاده نکن
```

تولید secret جدید روی سرور:

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(48))"
```

اگر secret عوض شود، همه‌ی توکن‌های قبلی بی‌اعتبار می‌شوند (لاگین مجدد لازم است) — طبیعی و مطلوب.

## ۳. نص و اجرا

```bash
cd server-fastapi
python3 -m venv venv
./venv/bin/pip install -r requirements.txt
```

اجرای دستی برای تست اولیه:

```bash
./venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 3001 --workers 2
curl http://127.0.0.1:3001/api/health   # → {"status":"ok","db":"up"}
```

نکته: `--workers 2` یعنی دو پروسه؛ کش in-memory meta/analytics در هر پروسه جدا
نگهداری می‌شود (کمی کوئری تکراری، بی‌خطر). با ترافیک بیشتر ۴ تا بگذار.

### ساخت اکانت ادمین سرور

```bash
./venv/bin/python -m app.cli create-admin <ایمیل-تو> <پسورد-قوی> --days 3650
```

این اکانت ادمینِ سرور است و ربطی به اکانت لوکال ندارد. پسورد لوکال (`admin123`)
را هرگز روی سرور تکرار نکن.

## ۴. systemd (اجرای دائمی)

فایل `/etc/systemd/system/skool-api.service`:

```ini
[Unit]
Description=Skool Explorer API
After=network.target postgresql.service

[Service]
User=www-data
WorkingDirectory=/opt/skool/server-fastapi
ExecStart=/opt/skool/server-fastapi/venv/bin/python -m uvicorn app.main:app \
    --host 127.0.0.1 --port 3001 --workers 2
Restart=always
RestartSec=3

# hardening
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ReadWritePaths=/opt/skool/server-fastapi

[Install]
WantedBy=multi-user.target
```

(مسیر `/opt/skool/server-fastapi` را با مسیر واقعی خودت عوض کن.)

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now skool-api
systemctl status skool-api        # باید active باشد
journalctl -u skool-api -f        # لاگ زنده
```

اسکیمای auth (`app.accounts`, `app.usage_log`) خودکار در استارتاپ ساخته می‌شود.
اما کاربر دیتابیس باید اجازه‌ی ساخت اسکیما داشته باشد:

```sql
CREATE SCHEMA IF NOT EXISTS app AUTHORIZATION <pguser>;
-- یا حداقل:
GRANT ALL ON SCHEMA app TO <pguser>;
```

## ۵. nginx + HTTPS (جلوی API)

سرور فقط روی `127.0.0.1:3001` گوش می‌دهد؛ nginx نقشه‌ی HTTPS و دامنه را دارد.

`/etc/nginx/sites-available/skool.conf`:

```nginx
server {
    listen 443 ssl http2;
    server_name api.your-domain.com;          # ← دامنه‌ی خودت

    ssl_certificate     /etc/letsencrypt/live/api.your-domain.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/api.your-domain.com/privkey.pem;

    # gzip خود FastAPI فعال است؛ این را دست نزن
    location / {
        proxy_pass http://127.0.0.1:3001;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_read_timeout 30s;
    }
}

server {
    listen 80;
    server_name api.your-domain.com;
    return 301 https://$host$request_uri;
}
```

گواهی رایگان Let's Encrypt:

```bash
sudo apt install certbot python3-certbot-nginx
sudo certbot --nginx -d api.your-domain.com
```

### CORS — فعلاً دست نزن

الان پیش‌فرض بسته است (همان‌مبدأ از طریق vite proxy). وقتی UI را جدا از API
دیپلوی کردی (دامنه‌ی دیگر)، در `.env` سرور:

```ini
CORS_ORIGINS=https://app.your-domain.com
```

## ۶. دیتابیس

- **دیتای skool را جدا منتقل کن** — dump/restore کامل سه جدول + دو جدول metrics.
  اسکرپر هم باید روی سرور (یا دسترسی‌پذیر) راه بیفتد وگرنه دیتا کهنه می‌شود.
- پسورد و user دیتابیسِ سرور را جدید بساز؛ credential لوکال را نبر.
- اگر pgbouncer یا پراکسی دیگری وسط است، asyncpg با prepared statement مشکل
  ندارد (codec int8 text-mode امن است).

```bash
# نمونه انتقال
pg_dump -h localhost -U pouri -d pouri -n skool -Fc > skool.dump
# روی سرور:
createdb -U <user> pouri && pg_restore -U <user> -d pouri skool.dump
```

اسکیمای `app` (اکانت‌ها) را منتقل نکن — روی سرور خالی ساخته می‌شود و فقط
اکانت ادمینِ جدید (بند ۳) را می‌گیری.

## ۷. چک‌لیست نهایی قبل از اعلام آماده‌باش

| # | مورد | فرمان / محل |
|---|------|-------------|
| 1 | health سبز | `curl https://api.your-domain.com/api/health` |
| 2 | بدون توکن → 401 | `curl https://api.your-domain.com/api/groups?pageSize=1` |
| 3 | لاگین ادمین سرور جواب می‌دهد | POST /api/auth/login |
| 4 | secret جدید در .env | بند ۲ |
| 5 | ادمین سرور ساخته شد | بند ۳ |
| 6 | HTTPS فعال + redirect | certbot |
| 7 | تست‌ها روی سرور | `API_BASE_URL=https://api.your-domain.com ./venv/bin/python -m pytest tests/test_contract.py -q` |

## ۸. بعداً (وقتی مشتری زیاد شد)

- **rate limit per-user** — الان ثبت مصرف هست ولی محدودیت نیست؛ با nginx
  `limit_req_zone` بر اساس `$http_authorization` یا یک middleware ساده قابل افزودن است.
- **پسورد ادمین** حتماً قوی؛ endpoint ریست هم داری (`POST /api/admin/accounts/{id}/password`).
- بک‌آپ روزانه‌ی `app.accounts` + `skool.*_metrics`.
