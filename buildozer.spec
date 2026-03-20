[app]

# 应用基本信息
title = PLC时间锁授权工具
package.name = plctimelockv1
package.domain = com.industrial.plclock

source.dir = .
source.include_exts = py,ttf,json,db
source.include_patterns = calculator.py,simhei.ttf

# 版本
version = 1.0

# 依赖库
requirements = python3==3.11.0,kivy==2.3.0,kivymd==1.2.0

# 入口文件
entrypoint = android_app.py

# 图标（如有 icon.png 放在同目录）
# icon.filename = %(source.dir)s/icon.png
# presplash.filename = %(source.dir)s/presplash.png

# 屏幕方向（竖屏优先）
orientation = portrait

# 全屏
fullscreen = 0

# Android 配置
android.permissions = android.permission.WRITE_EXTERNAL_STORAGE,android.permission.READ_EXTERNAL_STORAGE
android.api = 34
android.minapi = 26
android.ndk = 25b
android.archs = arm64-v8a,armeabi-v7a

# 不需要网络权限（纯离线）
# android.permissions 中不包含 INTERNET

# 支持 64 位（Google Play 要求）
android.add_aars =

# 允许备份
android.allow_backup = True

# 最低 SDK
android.gradle_dependencies =

[buildozer]
log_level = 2
warn_on_root = 1
