@echo off
chcp 65001 >nul
title MAIL REG PRO v5.0 - TM MEDIA
cd /d "%~dp0"
echo ============================================================
echo  MAIL REG PRO v5.0 - Bot tao mail tam (TM MEDIA)
echo ============================================================
echo [1/2] Dang tim Python...
set PY=
where python >nul 2>nul && set PY=python
if not defined PY (
  echo Khong tim thay Python! Cai Python 3.10+ tu python.org roi chay lai.
  pause
  exit /b 1
)
echo [2/2] Dang khoi dong bot...
%PY% -u mail_reg_pro.py
pause
