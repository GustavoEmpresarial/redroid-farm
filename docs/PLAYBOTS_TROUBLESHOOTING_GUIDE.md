# Guia de Configuração e Resolução de Problemas (PlayBots + Redroid + A20s)

Este documento reúne o histórico completo de desafios técnicos, causas raízes e soluções de engenharia implementadas para rodar o **PlayBots-Seofast V8.4.0** e o ecossistema Android (dispositivo físico Samsung Galaxy A20s e containers virtuais Redroid no Docker).

---

## Índice

1. [Kernel Linux Host e Suporte ao BinderFS](#1-kernel-linux-host-e-suporte-ao-binderfs)
2. [Tradução de Arquitetura (x86_64 para ARM)](#2-tradução-de-arquitetura-x86_64-para-arm)
3. [Play Protect e Dispositivo Não Certificado (GMS Compliance)](#3-play-protect-e-dispositivo-não-certificado-gms-compliance)
4. [Falha "Não foi possível abrir esse link" (YouTube Intents)](#4-falha-não-foi-possível-abrir-esse-link-youtube-intents)
5. [Requisitos Internos e Regras do Motor PlayBots](#5-requisitos-internos-e-regras-do-motor-playbots)
6. [Prevenção de Pânico de Kernel (Softdog Watchdog no A20s)](#6-prevenção-de-pânico-de-kernel-softdog-watchdog-no-a20s)
7. [Suspensão de Carga da Bateria (Qualcomm PMI632)](#7-suspensão-de-carga-da-bateria-qualcomm-pmi632)
8. [Transmissão de Vídeo Estável e Handover Automático (USB / Wi-Fi)](#8-transmissão-de-vídeo-estável-e-handover-automático-usb--wi-fi)

---

## 1. Kernel Linux Host e Suporte ao BinderFS

### O Problema:
O Android depende do driver de IPC `binder` para comunicação entre processos (`system_server`, `surfaceflinger`, `adbd`). No Ubuntu e distribuições modernas com kernel 6.x / 7.x, o módulo `binder_linux` não vem carregado por padrão ou não possui os nós montados em `/dev/binderfs`.

### A Solução:
1. Carregar o módulo do kernel com os dispositivos necessários:
   ```bash
   modprobe binder_linux devices=binder,hwbinder,vndbinder
   ```
2. Montar o sistema de arquivos IPC com propagação compartilhada (`rshared`):
   ```bash
   mkdir -p /dev/binderfs
   mount -t binder binder /dev/binderfs
   chmod 777 /dev/binderfs /dev/binderfs/*
   ```
3. O script `start-farm.sh` faz essa verificação automaticamente antes de inicializar os containers.

---

## 2. Tradução de Arquitetura (x86_64 para ARM)

### O Problema:
O host roda arquitetura x86_64 (PC Intel/AMD), enquanto o APK do PlayBots possui dependências compiladas para arquiteturas móveis ARM (`arm64-v8a` e `armeabi-v7a`).

### A Solução:
Utilizar a imagem oficial `redroid/redroid:13.0.0-latest`, que já incorpora a camada de tradução dinâmica (`libndk_translation` / `houdini`), permitindo executar binários ARM em processadores x86 com sobrecarga mínima de CPU.
- Verificação:
  ```bash
  adb shell getprop ro.product.cpu.abilist
  # Retorno esperado: x86_64,arm64-v8a,x86,armeabi-v7a,armeabi
  ```

---

## 3. Play Protect e Dispositivo Não Certificado (GMS Compliance)

### O Problema:
Em sistemas Android customizados (GSI no A20s ou containers AOSP Redroid), os serviços do Google barram a execução com a tela:
> *"Este dispositivo não está certificado pelo Play Protect"* (`UncertifiedDeviceActivity`).

Além disso, instalar o framework do Google (`com.google.android.gsf`) como aplicativo de usuário comum em `/data/app` causa falhas fatais no Android Runtime:
```text
SecurityException: Permission denial: reading from settings requires: android.permission.READ_DEVICE_CONFIG
SecurityException: Permission Denial: opening provider GservicesProvider requires READ_GSERVICES
```

### A Solução:
1. **Instalação Privilegiada no Sistema (`/system/priv-app`):**
   - Os pacotes `GoogleServicesFramework.apk`, `PrebuiltGmsCore.apk` e `Phonesky.apk` (Google Play Store) devem residir em `/system/priv-app/`.
2. **Definição de Permissões Privilegiadas:**
   - Inserir o arquivo de permissões em `/system/etc/permissions/privapp-permissions-google.xml` concedendo explicitamente `READ_DEVICE_CONFIG`, `WRITE_DEVICE_CONFIG`, `MANAGE_USERS` e `READ_GSERVICES`.
3. **Desativação do Verificador Play Protect:**
   ```bash
   pm disable-user --user 0 com.google.android.verifier
   settings put global package_verifier_enable 0
   settings put global package_verifier_user_consent -1
   settings put global upload_apk_enable 0
   ```
4. **Desativação da Activity de Bloqueio:**
   ```bash
   pm disable com.google.android.youtube/com.google.android.gms.gmscompliance.ui.UncertifiedDeviceActivity
   ```

---

## 4. Falha "Não foi possível abrir esse link" (YouTube Intents)

### O Problema:
Quando o PlayBots localiza uma tarefa de vídeo no Seo-Fast, ele dispara uma intent para abrir a URL no aplicativo oficial do YouTube. O Android bloqueava a ação ou a exibia como link morto.

### Causas Raízes e Correções:
1. **Navegador Padrão Ausente:**
   - O Android precisa de um manipulador de URLs base ativo para fallback.
   - Solução: Ativar o navegador nativo (`pm enable org.lineageos.jelly`).
2. **Aprovação de Domínio (App Links):**
   - No Android 12 e 13, o sistema exige que domínios com verificação de links sejam aprovados pelo usuário para abrir diretamente no aplicativo sem diálogo:
   ```bash
   pm set-app-links-allowed --user 0 --package com.google.android.youtube true all
   pm set-app-links-user-selection --user 0 --package com.google.android.youtube true youtu.be m.youtube.com youtube.com www.youtube.com
   pm set-app-links --package com.google.android.youtube 2 youtu.be m.youtube.com youtube.com www.youtube.com
   ```

---

## 5. Requisitos Internos e Regras do Motor PlayBots

O PlayBots possui validações rígidas de integridade antes de ligar o motor:

| Requisito | Sintoma de Erro | Solução Via ADB |
|---|---|---|
| **Som de Mídia** | `[ERRO] Som zerado. Ligue o som (qualquer nível)` | `cmd media_session volume --stream 3 --set 3` |
| **Sincronia de Hora** | `timestamp inválido` na tela de login | Sincronizar relógio com UTC: `settings put global auto_time 1` e `date -u MMDDhhmmYYYY.ss` |
| **Acessibilidade** | `BOT · não ligou: Acessibilidade desativada` | `settings put secure enabled_accessibility_services com.playzero.playbotsseofast/.YouTubeWatchdogService` e `settings put secure accessibility_enabled 1` |
| **Sobreposição** | `BOT · não ligou: Sobreposição (overlay) desativada` | `appops set com.playzero.playbotsseofast SYSTEM_ALERT_WINDOW allow` |
| **Segundo Plano** | O app é congelado pelo sistema ao trocar de tela | `dumpsys deviceidle whitelist +com.playzero.playbotsseofast` e `appops set com.playzero.playbotsseofast RUN_IN_BACKGROUND allow` |
| **Contatos e Notif** | Alerta nas configurações | `pm grant com.playzero.playbotsseofast android.permission.READ_CONTACTS` e `cmd notification allow_listener com.playzero.playbotsseofast/.ProtonNotifListener` |

### Armazenamento de Credenciais Seo-Fast:
O PlayBots salva as credenciais da conta do Seo-Fast em `/data/data/com.playzero.playbotsseofast/shared_prefs/BotPrefs.xml`:
- `auto_login`: boolean (`true`)
- `ultimo_email`: string com o e-mail cadastrado
- `ultima_senha`: string com a senha codificada em **Base64**

---

## 6. Prevenção de Pânico de Kernel (Softdog Watchdog no A20s)

### O Problema:
Ao aplicar regras agressivas de mascaramento via `resetprop` alterando propriedades sensíveis em tempo de execução (`ro.build.type=user`, `ro.debuggable=0`, `ro.boot.veritymode=enforcing`) em conjunto com a ROM Lineage GSI, o kernel Qualcomm acionou threads de proteção que causaram estouro do watchdog de software:
```text
softdog: Initiating panic
Kernel panic - not syncing: Software Watchdog Timer expired
```
O celular reiniciava sozinho em loop a cada ~115 segundos.

### A Solução:
- Remover scripts em `service.d` e `post-fs-data.d` que forcem `ro.build.type=user` e `enforcing` dinamicamente em ROM GSI.
- Manter o aparelho com SELinux estável e apenas mascarar a certificação do Play Protect sem violar as rotinas do kernel Qualcomm.

---

## 7. Suspensão de Carga da Bateria (Qualcomm PMI632)

### O Problema:
Ao alternar o cabo USB ou utilizar conexões com oscilação de corrente, o PMIC Qualcomm Snapdragon (`pmi632`) ativava a trava de hardware `input_suspend=1`, cessando o carregamento da bateria mesmo com o carregador conectado.

### A Solução:
Script persistente configurado em `/data/adb/service.d/a20s-charger-fix.sh` garantindo que o chip mantenha a entrada de energia liberada:
```bash
echo 0 > /sys/class/power_supply/battery/input_suspend
echo 1 > /sys/class/power_supply/battery/battery_charging_enabled
```

---

## 8. Transmissão de Vídeo Estável e Handover Automático (USB / Wi-Fi)

### O Problema:
A rede Wi-Fi 2.4 GHz possui oscilações de jitter (ping variando de 7ms a 200ms). Ao tentar transmitir scrcpy a 8 Mbps (`-b 8M`), o buffer de rede estourava e a tela congelava. Ao desconectar o cabo, a transmissão caía completamente.

### A Solução Implementada em `video-adb-watchdog.sh`:
1. **Perfis Otimizados de Vídeo:**
   - **No Cabo USB:** `1024p`, `6 Mbps`, `30 fps`, buffer `0ms` (latência zero).
   - **Na Rede Wi-Fi:** `720p`, `3 Mbps`, `30 fps`, buffer anti-jitter de `40ms`, encoder por hardware Qualcomm (`OMX.qcom.video.encoder.avc`), áudio desativado (`--no-audio`).
2. **Handover Automático com Warm Standby:**
   - Mantém a porta ADB TCP `:5555` emparelhada em segundo plano enquanto o cabo está conectado.
   - Ao retirar o cabo, o watchdog detecta em <2s e sobe o stream via Wi-Fi sem intervenção manual.
   - Ao reconectar o cabo, o watchdog desliga a sessão de rede e chaveia de volta para o cabo de imediato.
   - Mantém a tela física do aparelho 100% desligada (`-S`, backlight em `0`).
