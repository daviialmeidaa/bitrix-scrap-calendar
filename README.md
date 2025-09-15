Bitrix ➜ Google Calendar (via Selenium + Google API)

Sincroniza eventos do Bitrix24 com o Google Calendar lendo notificações de agenda no Bitrix, extraindo os dados e criando/atualizando no GCal sem duplicar.

bot.py (Selenium/Firefox)

Faz login no Bitrix (perfil persistente do Firefox para evitar captcha).

Abre o painel de notificações e coleta apenas as que apontam para agenda (/calendar/?EVENT_ID=).

Clica em cada notificação, abre o slider do evento e extrai data, início, término.

Salva/atualiza out/events.json e out/events.py.

sync_gcal.py (Google Calendar API)

Lê out/events.json.

Cria/atualiza eventos no calendário alvo.

Não duplica: usa extendedProperties.private.bitrix_id=<EVENT_ID> para localizar eventos já sincronizados.

main.py

CLI que orquestra os passos: --scrape, --sync, --all.

Pré-requisitos

Python 3.10+

Firefox instalado (Selenium Manager resolve o geckodriver automaticamente).

Acesso ao Bitrix24 (usuário/senha).

Conta Google Workspace (ou Gmail) com permissão de escrita no Calendar.

Instalação
# clone o repositório
git clone <repo> && cd <repo>

# crie e ative o venv
python -m venv .venv
# Windows
.venv\Scripts\activate
# Linux/Mac
source .venv/bin/activate

# dependências
pip install -r requirements.txt


requirements.txt mínimo:

selenium
python-dotenv
google-api-python-client
google-auth-httplib2
google-auth-oauthlib
python-dateutil

Configuração (.env)

Crie um arquivo .env na raiz:

TZ=America/Sao_Paulo

# Bitrix
BITRIX_URL=https://teste.com.br/
BITRIX_USER="seu.email@empresa.com"
BITRIX_PASS="sua_senha"
HEADLESS=true

# Google Calendar
GOOGLE_CALENDAR_ID=primary
# ou o ID do calendário (ex.: zedascouves@gmail.com)

HEADLESS=false se quiser visualizar o navegador.

Credenciais Google (OAuth)

Google Cloud Console → ative Google Calendar API.

OAuth consent screen

Em contas Workspace, escolha Internal (dispensa verificação pública).

Preencha os campos obrigatórios e salve.

Credentials → Create Credentials → OAuth client ID

Tipo: Desktop app → Create → Download JSON.

Salve o arquivo como credentials.json na raiz do projeto.

Na primeira execução do sync_gcal.py será aberto um navegador para você autorizar. O token ficará em token.json.

Se a organização bloquear apps, o admin precisa marcar seu Client ID como Trusted em Admin Console → Security → API Controls → App access control.

Estrutura de arquivos
.
├─ bot.py
├─ sync_gcal.py
├─ main.py
├─ selectors.json
├─ .env
├─ credentials.json           # (não versionar)
├─ token.json                 # gerado na 1ª autenticação (não versionar)
└─ out/
   ├─ events.json             # dados extraídos para sincronizar
   ├─ events.py               # mesmo conteúdo como módulo Python (EVENTS = [...])
   ├─ ff-profile/             # perfil Firefox persistente (cookies/sessão)
   ├─ after_login.png         # prints auxiliares
   └─ notifications.png


Schema de out/events.json:

[
  {
    "titulo": "Teste",
    "id": "1608604",
    "data": "16/09/2025",
    "inicio": "09:30",
    "termino": "10:30",
    "link": "https://steste.com.br/.../calendar/?EVENT_ID=1608604"
  }
]

# # # Execução
Scrapear do Bitrix
python main.py --scrape

Sincronizar com Google Calendar
python main.py --sync

Pipeline completo (scrape + sync)
python main.py --all