BEGIN TRANSACTION;
CREATE TABLE mailboxes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                backend TEXT NOT NULL,
                address TEXT NOT NULL UNIQUE,
                login TEXT DEFAULT '',
                domain TEXT DEFAULT '',
                password TEXT DEFAULT '',
                token TEXT DEFAULT '',
                extra TEXT DEFAULT '{}',
                label TEXT DEFAULT '',
                is_active INTEGER DEFAULT 0,
                notify INTEGER DEFAULT 1,
                created_at TEXT DEFAULT '',
                last_check TEXT DEFAULT ''
            );
INSERT INTO "mailboxes" VALUES(7,'mail.tm','tiktokus1@maxxspace.com','tiktokus1','maxxspace.com','Thuan2007','eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzUxMiJ9.eyJpYXQiOjE3OTE0NTQ5MDEsInJvbGVzIjpbIlJPTEVfVVNFUiJdLCJhZGRyZXNzIjoidGlrdG9rdXMxQG1heHhzcGFjZS5jb20iLCJpZCI6IjZhYzc2ZWIzZDVjZDFmNWU3ZDAyNjhkZCIsIm1lcmN1cmUiOnsic3Vic2NyaWJlIjpbIi9hY2NvdW50cy82YWM3NmViM2Q1Y2QxZjVlN2QwMjY4ZGQiXX19.mOZT1UwDICa6WaB92zw2-Q45XygZX2fNWH9ly42iKK-gvGDBSYleHVlQg3BkeBnVI9cxA0qLRCnfeSHcf21vsg','{"account_id": "6ac76eb3d5cd1f5e7d0268dd"}','Bodycam/@bodycam.cops0',0,1,'2026-10-08 17:21:41','2026-10-08 21:40:08');
INSERT INTO "mailboxes" VALUES(8,'mail.tm','tiktokus2@maxxspace.com','tiktokus2','maxxspace.com','Thuan2007','eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzUxMiJ9.eyJpYXQiOjE3OTE0NTU3ODUsInJvbGVzIjpbIlJPTEVfVVNFUiJdLCJhZGRyZXNzIjoidGlrdG9rdXMyQG1heHhzcGFjZS5jb20iLCJpZCI6IjZhYzc3MjI3MmVmMWQwODE4NDBlYTUxOCIsIm1lcmN1cmUiOnsic3Vic2NyaWJlIjpbIi9hY2NvdW50cy82YWM3NzIyNzJlZjFkMDgxODQwZWE1MTgiXX19.GIP4PQRgUrtaAitxG7BSZ5O4LvhLJ2ARYKEq_rxQz0i7gmyaXDodkCUzfPszQM7GnydE17IpJl6u6vwPC7LFtQ','{"account_id": "6ac772272ef1d081840ea518"}','Pikolin show/@pikolin.show',0,1,'2026-10-08 17:36:26','2026-10-08 21:40:06');
INSERT INTO "mailboxes" VALUES(9,'mail.tm','tiktokuk01@maxxspace.com','tiktokuk01','maxxspace.com','Thuan2007','eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzUxMiJ9.eyJpYXQiOjE3OTE0NTU4ODksInJvbGVzIjpbIlJPTEVfVVNFUiJdLCJhZGRyZXNzIjoidGlrdG9rdWswMUBtYXh4c3BhY2UuY29tIiwiaWQiOiI2YWM3NzI4ZmI4YTUxZmM5MzQwZjQwZjgiLCJtZXJjdXJlIjp7InN1YnNjcmliZSI6WyIvYWNjb3VudHMvNmFjNzcyOGZiOGE1MWZjOTM0MGY0MGY4Il19fQ.ROILIuGoooR5pu_eQMVoLkoLzwIRNqETU2-g-3y1WZZzs7dBwAFGSa6AXIl-8PyFU6QPLukitAeIZaOrg9yYIA','{"account_id": "6ac7728fb8a51fc9340f40f8"}','',1,1,'2026-10-08 17:38:09','2026-10-08 21:40:04');
CREATE TABLE otp_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                address TEXT DEFAULT '',
                otp TEXT DEFAULT '',
                sender TEXT DEFAULT '',
                created_at TEXT DEFAULT ''
            );
INSERT INTO "otp_history" VALUES(1,'tiktokus1@maxxspace.com','339972','noreply@account.tiktok.com','2026-10-08 17:25:10');
INSERT INTO "otp_history" VALUES(2,'tiktokus1@maxxspace.com','198373','noreply@account.tiktok.com','2026-10-08 17:31:39');
INSERT INTO "otp_history" VALUES(3,'tiktokus1@maxxspace.com','319084','noreply@account.tiktok.com','2026-10-08 17:34:47');
INSERT INTO "otp_history" VALUES(4,'tiktokuk01@maxxspace.com','479440','noreply@account.tiktok.com','2026-10-08 17:38:40');
INSERT INTO "otp_history" VALUES(5,'tiktokus1@maxxspace.com','633583','noreply@account.tiktok.com','2026-10-08 17:44:16');
INSERT INTO "otp_history" VALUES(6,'tiktokuk01@maxxspace.com','421746','noreply@account.tiktok.com','2026-10-08 17:49:29');
INSERT INTO "otp_history" VALUES(7,'tiktokuk01@maxxspace.com','894535','noreply@account.tiktok.com','2026-10-08 17:58:26');
INSERT INTO "otp_history" VALUES(8,'tiktokus1@maxxspace.com','016399','noreply@account.tiktok.com','2026-10-08 18:06:56');
INSERT INTO "otp_history" VALUES(9,'tiktokus2@maxxspace.com','418097','noreply@account.tiktok.com','2026-10-08 18:08:09');
INSERT INTO "otp_history" VALUES(10,'tiktokuk01@maxxspace.com','755721','noreply@account.tiktok.com','2026-10-08 18:10:24');
INSERT INTO "otp_history" VALUES(11,'tiktokuk01@maxxspace.com','376425','noreply@account.tiktok.com','2026-10-08 18:11:51');
INSERT INTO "otp_history" VALUES(12,'tiktokus1@maxxspace.com','807422','noreply@account.tiktok.com','2026-10-08 18:15:48');
INSERT INTO "otp_history" VALUES(13,'tiktokus1@maxxspace.com','08228','noreply@account.tiktok.com','2026-10-08 18:16:52');
INSERT INTO "otp_history" VALUES(14,'tiktokus2@maxxspace.com','950424','noreply@account.tiktok.com','2026-10-08 18:34:59');
INSERT INTO "otp_history" VALUES(15,'tiktokus2@maxxspace.com','600920','noreply@account.tiktok.com','2026-10-08 18:36:16');
INSERT INTO "otp_history" VALUES(16,'tiktokus2@maxxspace.com','27214','noreply@account.tiktok.com','2026-10-08 18:37:08');
CREATE TABLE seen_messages (
                mailbox_id INTEGER NOT NULL,
                provider_msg_id TEXT NOT NULL,
                PRIMARY KEY (mailbox_id, provider_msg_id)
            );
INSERT INTO "seen_messages" VALUES(7,'6ac76f7f9d2b597bccdc50c2');
INSERT INTO "seen_messages" VALUES(7,'6ac771035b605813d2315b37');
INSERT INTO "seen_messages" VALUES(7,'6ac771c3774b2155be976290');
INSERT INTO "seen_messages" VALUES(9,'6ac772a8ee852a585a8d22c3');
INSERT INTO "seen_messages" VALUES(7,'6ac773fb6b23a7d922d0b69b');
INSERT INTO "seen_messages" VALUES(9,'6ac7753341fb19f3986c5bba');
INSERT INTO "seen_messages" VALUES(9,'6ac777457f6d7f1b9b11840f');
INSERT INTO "seen_messages" VALUES(7,'6ac7794b859cf5bf14f82d56');
INSERT INTO "seen_messages" VALUES(8,'6ac77994bcd459936adb0e98');
INSERT INTO "seen_messages" VALUES(9,'6ac77a1b581666ecbe5e0d96');
INSERT INTO "seen_messages" VALUES(9,'6ac77a74fa532a81ec35602b');
INSERT INTO "seen_messages" VALUES(7,'6ac77b5c00448deac9e72df7');
INSERT INTO "seen_messages" VALUES(7,'6ac77b9a588a9e579b70b11c');
INSERT INTO "seen_messages" VALUES(8,'6ac77fdd859cf5bf14f841d5');
INSERT INTO "seen_messages" VALUES(8,'6ac7802ca2f7875d03ed0d18');
INSERT INTO "seen_messages" VALUES(8,'6ac7805dc0ef7b3a41cd118e');
CREATE TABLE settings (
                key TEXT PRIMARY KEY,
                value TEXT
            );
INSERT INTO "settings" VALUES('poll_interval','5');
INSERT INTO "settings" VALUES('default_provider','mail.tm');
INSERT INTO "settings" VALUES('notify_global','1');
INSERT INTO "settings" VALUES('otp_only','0');
INSERT INTO "settings" VALUES('short_domain','0');
INSERT INTO "settings" VALUES('digest_mode','1');
CREATE TABLE stats (
                key TEXT PRIMARY KEY,
                value INTEGER DEFAULT 0
            );
INSERT INTO "stats" VALUES('mailboxes_created',9);
INSERT INTO "stats" VALUES('messages_received',22);
INSERT INTO "stats" VALUES('backups',1);
INSERT INTO "stats" VALUES('otps_found',16);
DELETE FROM "sqlite_sequence";
INSERT INTO "sqlite_sequence" VALUES('mailboxes',9);
INSERT INTO "sqlite_sequence" VALUES('otp_history',16);
COMMIT;
