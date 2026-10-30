#!/usr/bin/env bash
# Redroid Farm — Inicializador do painel e ambiente Android
set -euo pipefail
cd "$(dirname "$0")"

echo "[*] Verificando modulo binder_linux no kernel..."
if ! lsmod | grep -q binder_linux; then
  echo "[+] Carregando modulo binder_linux..."
  docker run --rm --privileged -v /lib/modules:/lib/modules ubuntu:latest sh -c \
    "apt-get update -qq && apt-get install -y -qq kmod >/dev/null && modprobe binder_linux devices=binder,hwbinder,vndbinder" || true
fi

echo "[*] Verificando ponto de montagem binderfs..."
if [ ! -c /dev/binderfs/binder ]; then
  docker run --rm --privileged -v /dev:/dev:rshared ubuntu:latest sh -c \
    "mkdir -p /dev/binderfs && mount -t binder binder /dev/binderfs 2>/dev/null || true; chmod 777 /dev/binderfs /dev/binderfs/* 2>/dev/null || true" || true
fi

fuser -k 8768/tcp 2>/dev/null || pkill -f 'redroid-farm/server.py' 2>/dev/null || true
sleep 0.5

echo "[*] Iniciando containers redroid..."
for c in $(docker ps -a --filter "name=redroid" --format "{{.Names}}"); do
  docker start "$c" 2>/dev/null || true
done

nohup python3 server.py > /tmp/redroid-farm.log 2>&1 &
echo "[+] Redroid Farm online: http://127.0.0.1:8768"
sleep 1
tail -n 5 /tmp/redroid-farm.log || true

# Conecta ADB nos containers ativos
(
  sleep 3
  for p in 5556 5557 5558; do
    adb connect "127.0.0.1:$p" >/dev/null 2>&1 || true
  done
) &
