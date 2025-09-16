# bot.py
# -*- coding: utf-8 -*-
"""
Raspa notificações do Bitrix e salva apenas eventos cujo card contém:
"Você concordou em participar do evento".

Para cada notificação filtrada:
- Tenta abrir o slider do evento e extrair data/início/término.
- Se o slider estiver bloqueando o clique ou falhar,
  faz fallback: lê data e início direto do texto do card
  (ex.: "Sexta-feira, 19 de setembro de 2025 10:30")
  e define término = início + 60min.

Saídas:
- out/events.json (lista de dicts)
- out/events.py   (módulo Python com EVENTS = [...])
"""

import os, json, time, traceback, re, unicodedata
from datetime import datetime, timedelta

from dotenv import load_dotenv
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.firefox.options import Options as FFOptions

# =========================
# Config / env
# =========================
load_dotenv()

BITRIX_URL  = os.getenv("BITRIX_URL", "").strip().strip('"')
BITRIX_USER = os.getenv("BITRIX_USER", "").strip().strip('"')
BITRIX_PASS = os.getenv("BITRIX_PASS", "").strip().strip('"')
HEADLESS    = os.getenv("HEADLESS", "true").lower() == "true"
ENV_TZ      = os.getenv("TZ", "America/Sao_Paulo")

# FRASE-ALVO: só salvar notificações que contenham isso (case/acento-insensitive)
TARGET_PHRASE = "você concordou em participar do evento"

try:
    from zoneinfo import ZoneInfo
    NOW = datetime.now(ZoneInfo(ENV_TZ))
except Exception:
    NOW = datetime.now()

ROOT_DIR    = os.getcwd()
OUT_DIR     = os.path.join(ROOT_DIR, "out")
PROFILE_DIR = os.path.join(OUT_DIR, "ff-profile")
SEL_PATH    = os.path.join(ROOT_DIR, "selectors.json")

os.makedirs(OUT_DIR, exist_ok=True)
os.makedirs(PROFILE_DIR, exist_ok=True)

# =========================
# Selectors.json
# =========================
def load_selectors(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)
selectors = load_selectors(SEL_PATH)

def sget(*keys, default=""):
    cur = selectors
    for k in keys:
        cur = cur.get(k, {})
    return cur if isinstance(cur, str) else default

# =========================
# Utils
# =========================
def log(msg):      print(f"[BOT] {msg}", flush=True)
def log_ok(msg):   print(f"[OK]  {msg}", flush=True)
def log_warn(msg): print(f"[!]  {msg}", flush=True)
def log_err(msg):  print(f"[ERR] {msg}", flush=True)

def _norm(s: str) -> str:
    if not s: return ""
    s = unicodedata.normalize("NFKD", s).encode("ascii","ignore").decode("ascii")
    return " ".join(s.lower().strip().split())

def _add_minutes(hhmm: str, delta: int) -> str:
    h, m = map(int, hhmm.split(":"))
    t = datetime(2000,1,1,h,m) + timedelta(minutes=delta)
    return t.strftime("%H:%M")

# nomes de mês em pt-BR (para "16 de setembro de 2025")
PT_MONTHS = {
    "janeiro":1, "fevereiro":2, "março":3, "marco":3, "abril":4, "maio":5, "junho":6,
    "julho":7, "agosto":8, "setembro":9, "outubro":10, "novembro":11, "dezembro":12
}

# =========================
# Selenium / Firefox
# =========================
def make_driver():
    opts = FFOptions()
    if HEADLESS:
        os.environ["MOZ_HEADLESS"] = "1"
        opts.add_argument("-headless")
        # reduzir consumo/ruído
        opts.set_preference("permissions.default.image", 2)
        opts.set_preference("dom.ipc.reportProcessHangs", False)

    # Perfil persistente (cookies/sessão)
    opts.add_argument("-profile")
    opts.add_argument(PROFILE_DIR)

    return webdriver.Firefox(options=opts)

# =========================
# Login helpers
# =========================
def on_login_page(d):
    try:
        d.find_element(By.CSS_SELECTOR, "#login, .b24net-login-enter-form__continue-btn")
        return True
    except:
        return False

def is_logged(d):
    probe = sget("login", "logged_probe", default="")
    if probe:
        try:
            d.find_element(By.CSS_SELECTOR, probe); return True
        except: pass
    return (not on_login_page(d)) and (".bitrix24.com" in d.current_url or ".bitrix24.com.br" in d.current_url)

def login_flow(driver, wait):
    try:
        log("Localizando campo de e-mail…")
        email_in = wait.until(EC.presence_of_element_located(
            (By.CSS_SELECTOR, sget("login","user","#login"))
        ))
        email_in.clear(); email_in.send_keys(BITRIX_USER)
        wait.until(EC.element_to_be_clickable(
            (By.CSS_SELECTOR, sget("login","continue_btn",".b24net-login-enter-form__continue-btn"))
        )).click()
        log_ok("E-mail preenchido e 'Continuar' clicado.")
    except Exception:
        log_warn("Etapa de e-mail ignorada (sessão existente ou layout diferente).")

    try:
        log("Localizando campo de senha…")
        pwd_in = WebDriverWait(driver, 20).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, sget("login","pass","input[type='password']")))
        )
        pwd_in.clear(); pwd_in.send_keys(BITRIX_PASS)
        WebDriverWait(driver, 10).until(
            EC.element_to_be_clickable((By.CSS_SELECTOR, sget("login","pass_continue_btn",".b24net-password-enter-form__continue-btn")))
        ).click()
        log_ok("Senha preenchida e 'Continuar' clicado.")
    except Exception:
        log_warn("Etapa de senha ignorada (provável sessão existente).")

# =========================
# Notificações -> eventos
# =========================
EVENT_ID_RE = re.compile(r"[?&]EVENT_ID=(\d+)\b", re.I)

def open_notifications(driver, wait):
    icon_sel = sget("notifications", "icon", default='[class*="--o-notification"]')
    log(f"Abrindo painel de notificações… ({icon_sel})")
    icon = wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, icon_sel)))
    icon.click()

    root_sel = sget("notifications", "root", default=".bx-im-content-notification__elements")
    wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, root_sel)))

    # scroll para tentar carregar tudo
    try:
        root = driver.find_element(By.CSS_SELECTOR, root_sel)
        for _ in range(4):
            driver.execute_script("arguments[0].scrollTop = arguments[0].scrollHeight;", root)
            time.sleep(0.4)
    except:
        pass

    driver.save_screenshot(os.path.join(OUT_DIR, "notifications.png"))
    log_ok("Painel de notificações aberto.")

def parse_from_notification_text(txt: str):
    """
    Fallback: lê do texto do card algo como:
    '... a ser realizado em Sexta-feira, 19 de setembro de 2025 10:30'
    Retorna (data_dd/mm/aaaa, inicio_HH:MM) ou ("","")
    """
    t = _norm(txt)  # lower + sem acentos
    # captura "dd de <mes> de 20xx HH:MM"
    m = re.search(r"\b(\d{1,2})\s+de\s+([a-z]+)\s+de\s+(20\d{2})\s+(\d{1,2}:\d{2})\b", t)
    if not m:
        return "", ""
    d = int(m.group(1)); mes_nome = m.group(2); a = int(m.group(3)); hhmm = m.group(4)
    mes = PT_MONTHS.get(mes_nome, 0)
    if not mes:
        return "", ""
    return f"{d:02d}/{mes:02d}/{a}", hhmm

def collect_calendar_notifications(driver, include_we=True):
    """
    Coleta <a> que contenham /calendar/?EVENT_ID=… e
    FILTRA apenas as que contém a frase-alvo no texto do card.
    Além de título/ID/URL, retorna 'full_text' (texto bruto do card).
    """
    root_sel = sget("notifications", "root",  default=".bx-im-content-notification__elements")
    link_sel = sget("notifications", "link_selector", default='a[href*="/calendar/?EVENT_ID="]')
    item_sel = sget("notifications", "item", default=".bx-im-content-notification-item__container")
    item_cls = item_sel.strip(".")

    try:
        root = driver.find_element(By.CSS_SELECTOR, root_sel)
        anchors = root.find_elements(By.CSS_SELECTOR, link_sel)
    except Exception:
        log_warn("Contêiner de notificações não encontrado; procurando no DOM inteiro…")
        anchors = driver.find_elements(By.CSS_SELECTOR, link_sel)

    results = []
    target_norm = _norm(TARGET_PHRASE)
    for a in anchors:
        href  = a.get_attribute("href") or ""
        title = a.get_attribute("textContent") or a.text or ""
        m = EVENT_ID_RE.search(href)
        if not m:
            continue

        # texto completo do card
        try:
            card = a.find_element(By.XPATH, f'ancestor::*[contains(@class,"{item_cls}")]')
            full_text = card.text or ""
        except Exception:
            full_text = title

        # aplica filtro pela frase-alvo
        if target_norm not in _norm(full_text):
            continue

        rec = {"title": title.strip(), "id": m.group(1), "url": href, "full_text": full_text}
        if include_we:
            rec["_we"] = a
        results.append(rec)
    return results

def parse_time_text(text: str):
    """
    Recebe, por ex: "amanhã, de 09:30 até 10:30" OU "Terça-feira, 16 de setembro de 2025 9:30"
    Retorna: (data_dd/mm/aaaa, inicio_HH:MM, termino_HH:MM)
    """
    t = " ".join(text.split()).lower()

    # pega horas/minutos
    hhmm = re.findall(r"\b(\d{1,2}:\d{2})\b", t)
    inicio  = hhmm[0] if len(hhmm) >= 1 else ""
    termino = hhmm[1] if len(hhmm) >= 2 else ""

    # explícito: "16 de setembro de 2025"
    m = re.search(r"\b(\d{1,2})\s+de\s+([a-zçãéêáíóúôû]+)\s+de\s+(20\d{2})\b", t)
    if m:
        d = int(m.group(1)); mes_nome = m.group(2); a = int(m.group(3))
        mes = PT_MONTHS.get(mes_nome, 0)
        if mes:
            return f"{d:02d}/{mes:02d}/{a}", inicio, termino

    # relativo: hoje/amanhã/depois de amanhã
    base = NOW.date()
    if "depois de amanhã" in t:
        base = base + timedelta(days=2)
    elif "amanhã" in t:
        base = base + timedelta(days=1)
    elif "hoje" in t:
        base = base
    else:
        return "", inicio, termino

    return base.strftime("%d/%m/%Y"), inicio, termino

def close_slider_if_open(driver):
    """Fecha o side-panel/slider do Bitrix se estiver aberto."""
    try:
        for sel in [".side-panel-close",
                    ".calendar-slider-header .ui-btn-close",
                    ".side-panel-pin-close"]:
            btns = driver.find_elements(By.CSS_SELECTOR, sel)
            if btns:
                try:
                    btns[0].click()
                    WebDriverWait(driver, 5).until_not(
                        EC.presence_of_element_located((By.CSS_SELECTOR, ".calendar-slider-workarea"))
                    )
                    return
                except Exception:
                    pass
    except Exception:
        pass

def click_and_extract_details(driver, wait, link_element):
    """
    Abre o slider do evento, lê data/horário e fecha o slider ao final.
    Usa JS click como fallback e fecha sliders pendurados antes de clicar.
    """
    close_slider_if_open(driver)

    try:
        driver.execute_script("arguments[0].scrollIntoView({block:'center'});", link_element)
        WebDriverWait(driver, 5).until(EC.element_to_be_clickable(link_element)).click()
    except Exception:
        driver.execute_script("arguments[0].click();", link_element)

    slider_sel = sget("event_view", "slider_root", default=".calendar-slider-workarea")
    wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, slider_sel)))

    time_sel  = sget("event_view", "time_text", default=".calendar-slider-sidebar-head-title")
    time_el   = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, time_sel)))
    time_text = time_el.text.strip()
    log(f"Detalhe do evento (texto horário): {time_text}")

    data, inicio, termino = parse_time_text(time_text)
    close_slider_if_open(driver)
    return {"data": data, "inicio": inicio, "termino": termino}

# =========================
# Persistência
# =========================
EVENTS_JSON = os.path.join(OUT_DIR, "events.json")
EVENTS_PY   = os.path.join(OUT_DIR, "events.py")

def load_existing_events():
    if not os.path.exists(EVENTS_JSON):
        return []
    try:
        with open(EVENTS_JSON, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except Exception:
        return []

def merge_events(existing, new_items):
    """Mescla por 'id'. Mantém valores antigos quando o novo vier vazio."""
    by_id = {str(e.get("id")): e for e in existing}
    for n in new_items:
        k = str(n.get("id"))
        if k in by_id:
            cur = by_id[k]
            for key in ["titulo","link","data","inicio","termino"]:
                val = n.get(key)
                if val:
                    cur[key] = val
        else:
            by_id[k] = n
    return list(by_id.values())

def write_events_files(events_list):
    with open(EVENTS_JSON, "w", encoding="utf-8") as f:
        json.dump(events_list, f, ensure_ascii=False, indent=2)
    py_content = "EVENTS = " + json.dumps(events_list, ensure_ascii=False, indent=2) + "\n"
    with open(EVENTS_PY, "w", encoding="utf-8") as f:
        f.write(py_content)
    log_ok(f"events.json / events.py salvos ({len(events_list)} itens).")

# =========================
# Main
# =========================
def main():
    log(f"Headless={HEADLESS} | URL base={BITRIX_URL}")
    driver = make_driver()
    try:
        wait = WebDriverWait(driver, 35)

        target_url = selectors.get("login", {}).get("url") or BITRIX_URL
        if not target_url:
            raise RuntimeError("URL do Bitrix não definida (ver .env e selectors.json).")

        log(f"Abrindo: {target_url}")
        driver.get(target_url)

        if on_login_page(driver):
            log("Tela de login detectada.")
            login_flow(driver, wait)
        else:
            log("Login possivelmente já válido (sessão/cookies).")

        log("Aguardando área interna…")
        WebDriverWait(driver, 40).until(lambda d: is_logged(d))
        time.sleep(0.5)

        # -------- Notificações (filtradas pela frase-alvo) --------
        open_notifications(driver, wait)
        notif = collect_calendar_notifications(driver, include_we=True)

        log_ok(f"Notificações (COM a frase-alvo) encontradas: {len(notif)}")
        for i, n in enumerate(notif, 1):
            print(f"[EVENTO {i}] ID={n['id']} | TÍTULO={n['title']}")

        existing = load_existing_events()
        if not notif:
            log_warn("Nenhuma notificação com a frase-alvo. Mantendo events.json atual.")
            write_events_files(existing)
            print("STATUS=NO_MATCHED_NOTIFICATIONS_KEEPING_PREVIOUS")
            return

        # Enriquecimento com slider + fallback do texto do card
        enriched = []
        for idx, n in enumerate(notif, 1):
            log(f"Extraindo detalhes do evento {idx}/{len(notif)} (ID={n['id']})…")

            # Fallback inicial pelo texto do card
            fb_data, fb_inicio = parse_from_notification_text(n.get("full_text",""))
            fb_termino = _add_minutes(fb_inicio, 60) if fb_inicio else ""

            details = {}
            try:
                details = click_and_extract_details(driver, wait, n["_we"])
            except Exception as e:
                log_warn(f"Não foi possível ler slider do evento ID={n['id']}: {e}")

            data    = details.get("data")    or fb_data    or ""
            inicio  = details.get("inicio")  or fb_inicio  or ""
            termino = details.get("termino") or (fb_termino if fb_inicio and not details.get("termino") else "")

            enriched.append({
                "titulo": n["title"],
                "id": n["id"],
                "link": n["url"],
                "data": data,
                "inicio": inicio,
                "termino": termino,
            })

        merged = merge_events(existing, enriched)
        write_events_files(merged)
        print("STATUS=OK_NOTIFICATIONS_AND_DETAILS")

    except Exception as e:
        log_err(f"Falha no fluxo: {e}")
        traceback.print_exc()
        print("STATUS=FAIL")
    finally:
        try:
            driver.quit()
        except Exception:
            pass

if __name__ == "__main__":
    main()
