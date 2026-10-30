#!/usr/bin/env bash
# Otimização extrema dos containers Redroid (Debloat + Desempenho + PlayBots)
set -euo pipefail

PORTS="${@:-5556 5557 5558}"

BLOAT_PACKAGES=(
  com.android.camera2
  com.android.cameraextensions
  com.android.gallery3d
  com.android.music
  com.android.musicfx
  com.android.calendar
  com.android.deskclock
  com.android.contacts
  com.android.bluetooth
  com.android.bluetoothmidiservice
  com.android.nfc
  com.android.se
  com.android.printspooler
  com.android.printservice.recommendation
  com.android.bips
  com.android.dreams.basic
  com.android.dreams.phototable
  com.android.wallpaper.livepicker
  com.android.wallpapercropper
  com.android.wallpaperbackup
  com.android.egg
  com.android.quicksearchbox
  org.chromium.webview_shell
  com.android.traceur
  com.android.smspush
  com.android.mms.service
)

for port in $PORTS; do
  ser="127.0.0.1:$port"
  echo "=========================================================="
  echo "[*] Otimizando container na porta $port ($ser)..."
  echo "=========================================================="

  # 1. Debloat: desativa apps desnecessários
  echo "[+] Desativando bloatware (Câmera, Galeria, Contatos, Música, Bluetooth)..."
  for pkg in "${BLOAT_PACKAGES[@]}"; do
    adb -s "$ser" shell "pm disable-user --user 0 $pkg 2>/dev/null" || true
  done

  # 2. Desempenho do sistema e animações zero
  echo "[+] Ajustando animações para 0x e otimizando render..."
  adb -s "$ser" shell "
    settings put global window_animation_scale 0
    settings put global transition_animation_scale 0
    settings put global animator_duration_scale 0
    settings put system sound_effects_enabled 0
    settings put system lockscreen_sounds_enabled 0
    settings put system haptic_feedback_enabled 0
    settings put system screen_off_timeout 2147483647
    settings put global stay_on_while_plugged_in 7
    svc power stayon true
  "

  # 3. Permissões completas e prioridade máxima para PlayBots e YouTube
  echo "[+] Configurando permissões de alta prioridade para PlayBots e YouTube..."
  adb -s "$ser" shell "
    appops set com.playzero.playbotsseofast SYSTEM_ALERT_WINDOW allow
    appops set com.playzero.playbotsseofast WRITE_SETTINGS allow
    appops set com.playzero.playbotsseofast REQUEST_INSTALL_PACKAGES allow
    appops set com.playzero.playbotsseofast ACCESS_RESTRICTED_SETTINGS allow
    appops set com.playzero.playbotsseofast GET_USAGE_STATS allow
    appops set com.playzero.playbotsseofast RUN_IN_BACKGROUND allow
    appops set com.playzero.playbotsseofast RUN_ANY_IN_BACKGROUND allow
    appops set com.playzero.playbotsseofast START_FOREGROUND allow
    appops set com.playzero.playbotsseofast WAKE_LOCK allow
    appops set com.playzero.playbotsseofast PROJECT_MEDIA allow
    appops set com.playzero.playbotsseofast AUTO_REVOKE_PERMISSIONS_IF_UNUSED ignore

    dumpsys deviceidle whitelist +com.playzero.playbotsseofast
    dumpsys deviceidle whitelist +com.google.android.youtube
    dumpsys deviceidle whitelist +com.google.android.gms

    pm grant com.playzero.playbotsseofast android.permission.POST_NOTIFICATIONS 2>/dev/null || true
    pm grant com.playzero.playbotsseofast android.permission.GET_ACCOUNTS 2>/dev/null || true
    pm grant com.playzero.playbotsseofast android.permission.READ_CONTACTS 2>/dev/null || true
    cmd notification allow_listener com.playzero.playbotsseofast/.ProtonNotifListener 2>/dev/null || true

    settings put secure enabled_accessibility_services com.playzero.playbotsseofast/.YouTubeWatchdogService
    settings put secure accessibility_enabled 1
    cmd media_session volume --stream 3 --set 3 2>/dev/null || true
    settings put global auto_time 1 2>/dev/null || true
    settings put global auto_time_zone 1 2>/dev/null || true

    pm set-app-links-allowed --user 0 --package com.google.android.youtube true all 2>/dev/null || true
    pm set-app-links-user-selection --user 0 --package com.google.android.youtube true youtu.be m.youtube.com youtube.com www.youtube.com 2>/dev/null || true

    # Limpeza de memória
    su 0 sh -c 'echo 3 > /proc/sys/vm/drop_caches' 2>/dev/null || true
  "

  echo "[✓] Container na porta $port otimizado com sucesso!"
done

echo ""
echo "[+] Concluído! Todos os containers estão com bloatware desativado e PlayBots liso."
