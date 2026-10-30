# Redroid Farm

Painel de controle, orquestração e acesso remoto interativo para múltiplos containers Android 13 (**ReDroid**) com aceleração no Linux.

Visual e telemetria inspirados no padrão **MiningHash**.

---

## Recursos

- **Visualização e Controle Web:**
  - Telinha interativa em tempo real com proporção nativa **9:16** (`720 × 1280`).
  - Toque com feedback visual (`tap`) e suporte a gestos de arrastar (`swipe`).
  - Botões do sistema integrados: Voltar, Home, Recentes, Power e Volume.
- **Teclado e Área de Transferência Direta:**
  - Digite no teclado do PC e os caracteres aparecem imediatamente no Android.
  - Suporte nativo a `Ctrl+V` para colar senhas e textos do clipboard do host.
- **Isolamento de Rede e Proxy Individual:**
  - Cada container pode receber seu próprio proxy HTTP/SOCKS via interface web ou API.
- **Orquestração e Gestão da Frota:**
  - Criação de novos celulares virtuais com 1 clique (gerenciamento automático de portas ADB e volumes persistentes).
  - Iniciar, parar, reiniciar e excluir instâncias individualmente ou em massa.
  - Instalação centralizada de APKs para todos os aparelhos a partir da pasta `apks/`.
  - Inicializador rápido para `scrcpy` de desktop quando necessário.
- **Script de Otimização e Debloat (`optimize-devices.sh`):**
  - Desativa 26 pacotes nativos inúteis (câmeras, galeria, relógio, sons, bloatware).
  - Trava animações em `0x` e ajusta permissões em segundo plano para máxima fluidez.

---

## Arquitetura e Portas Padrão

| Componente | Porta / Rota | Descrição |
|---|---|---|
| Dashboard Web | `:8768` | Painel de controle e streaming |
| Celular #1 | `:5556` | Porta ADB do container `redroid-phone-1` |
| Celular #2 | `:5557` | Porta ADB do container `redroid-phone-2` |
| Celular #3 | `:5558` | Porta ADB do container `redroid-phone-3` |
| Próximos Celulares | `:5559+` | Portas alocadas dinamicamente |

---

## Pré-requisitos

1. **Sistema Operacional:** Linux x86_64 (Ubuntu/Debian recomendado).
2. **Docker:** Docker Engine instalado e usuário no grupo `docker`.
3. **Módulo Binder do Kernel:** módulo `binder_linux` com suporte a `binderfs`.
4. **Dependências do Host:**
   - Python 3.10+
   - Pillow (`python3 -m pip install pillow` ou `apt install python3-pil`)
   - ADB (`apt install android-tools-adb` ou `adb`)
   - `scrcpy` (opcional, para janela desktop)

---

## Instalação e Inicialização

1. **Clone o repositório:**
   ```bash
   git clone https://github.com/GustavoEmpresarial/redroid-farm.git
   cd redroid-farm
   ```

2. **Dê permissão de execução aos scripts:**
   ```bash
   chmod +x start-farm.sh optimize-devices.sh
   ```

3. **Inicie o painel:**
   ```bash
   ./start-farm.sh
   ```

   O script verifica o módulo `binder_linux`, configura o `/dev/binderfs` se necessário, sobe os containers e inicia o servidor HTTP em:
   ```text
   http://127.0.0.1:8768
   ```

---

## Gerenciamento de APKs

Coloque os arquivos `.apk` dentro da pasta `apks/`:
```bash
cp /caminho/do/app.apk apks/
```
No painel web, clique em **"Instalar APK"**, selecione o aplicativo e o container de destino (ou marque todos).

---

## Documentação Técnica e Resolução de Problemas

Consulte o guia completo com todas as causas raízes e soluções de arquitetura enfrentadas no projeto:
- **[Guia Completo de Resolução e Configuração (PlayBots, GApps, Redroid e A20s)](docs/PLAYBOTS_TROUBLESHOOTING_GUIDE.md)**
  - Suporte a BinderFS no host.
  - Tradução de arquitetura x86_64 para ARM.
  - Correção de Play Protect e GMS Compliance (`READ_DEVICE_CONFIG`, `READ_GSERVICES`).
  - Resolução de intents do YouTube.
  - Requisitos rígidos do PlayBots (som, relógio UTC, acessibilidade, background).
  - Prevenção de pânico de kernel no hardware físico (Qualcomm Softdog).
- **Templates de Configuração:**
  - `templates/BotPrefs.template.xml`: modelo sanitizado para login automático no Seo-Fast.
  - `templates/privapp-permissions-google.xml`: permissões privilegiadas para pacotes Google em `/system/priv-app`.

---

## API REST

- `GET /api/devices`: Retorna status de todos os containers, portas ADB e uso de CPU/RAM.
- `GET /api/device/<nome>/screen.jpg`: Frame em tempo real do dispositivo em JPEG otimizado.
- `POST /api/device/<nome>/input`: Envia toques, gestos, texto ou comandos de teclado:
  - `{"action": "tap", "x": 360, "y": 640}`
  - `{"action": "swipe", "x1": 360, "y1": 900, "x2": 360, "y2": 300, "duration": 200}`
  - `{"action": "text", "text": "meu_texto"}`
  - `{"action": "paste", "text": "texto_da_area_de_transferencia"}`
  - `{"action": "key", "keycode": 4}` (4 = Back, 3 = Home, 187 = Recents, 26 = Power)
- `POST /api/device/<nome>/proxy`: Define ou remove o proxy (`{"proxy": "192.168.1.100:8080"}`).
- `POST /api/device/<nome>/action`: Controla o container (`start`, `stop`, `restart`, `delete`).
- `POST /api/devices/create`: Instancia um novo celular virtual com resolução e DPI customizados.

---

## Licença

MIT License.
