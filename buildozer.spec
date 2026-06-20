[app]
title           = FileRenameTool
package.name    = filerenametool
package.domain  = org.personal
source.dir      = .
source.include_exts = py,png,jpg,kv,atlas
version         = 1.0.0
requirements    = python3,kivy==2.3.0

orientation     = portrait

android.api          = 33
android.minapi       = 26
android.ndk          = 25b
android.archs        = arm64-v8a
android.permissions  = READ_EXTERNAL_STORAGE,WRITE_EXTERNAL_STORAGE,MANAGE_EXTERNAL_STORAGE

[buildozer]
log_level = 2
warn_on_root = 1
