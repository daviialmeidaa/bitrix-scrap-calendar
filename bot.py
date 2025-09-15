import os, json, time, traceback, re
from datetime import datetime, timedelta
from dotenv import load_dotenv
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.firefox.options import Options as FFOptions

load_dotenv()

BITRIX_URL  = os.getenv("BITRIX_URL", "").strip().strip('"')
BITRIX_USER = os.getenv("BITRIX_USER", "").strip().strip('"')
BITRIX_PASS = os.getenv("BITRIX_PASS", "").strip().strip('"')
HEADLESS    = os.getenv("HEADLESS", "true").lower() == "true"
ENV_TZ      = os.getenv("TZ", "America/Sao_Paulo")

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

def load_selectors(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)
selectors = load_selectors(SEL_PATH)

def sget(*keys, default=""):
    cur = selectors
    for k in keys:
        cur = cur.get(k, {})
    return cur if isinstance(cur, str) else default

def log(msg):     print(f"[BOT] {msg}", flush=True)
def log_ok(msg):  print(f"[OK]  {msg}", flush=True)
def log_warn(msg):print(f"[!]  {msg}", flush=True)
def log_err(msg): print(f"[ERR] {msg}", flush=True)

def make_driver():
    opts = FFOptions()

    # HEADLESS robusto (duplo gatilho)
    if HEADLESS:
        os.environ["MOZ_HEADLESS"] = "1"   # fallback robusto
        opts.add_argument("-headless")     # força headless também via flag
        # opcional: reduz ruído/recursos
        opts.set_preference("permissions.default.image", 2)  # sem imagens
        opts.set_preference("dom.ipc.reportProcessHangs", False)

    # Perfil persistente p/ manter sessão/cookies
    opts.add_argument("-profile")
    opts.add_argument(PROFILE_DIR)

    # (opcional) apontar binário do Firefox se não estiver no PATH:
    # bin_path = os.getenv("FIREFOX_BINARY")
    # if bin_path: opts.binary_location = bin_path

    return webdriver.Firefox(options=opts)


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
        log("Localizando campo de e-mail...")
        email_in = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, sget("login","user","#login"))))
        email_in.clear(); email_in.send_keys(BITRIX_USER)
        wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, sget("login","continue_btn",".b24net-login-enter-form__continue-btn")))).click()
        log_ok("E-mail preenchido e 'Continuar' clicado.")
    except Exception:
        log_warn("Etapa de e-mail ignorada (sessão existente ou layout diferente).")
    try:
        log("Localizando campo de senha...")
        pwd_in = WebDriverWait(driver, 20).until(EC.presence_of_element_located((By.CSS_SELECTOR, sget("login","pass","input[type='password']"))))
        pwd_in.clear(); pwd_in.send_keys(os.getenv("BITRIX_PASS", "").strip().strip('"'))
        WebDriverWait(driver, 10).until(EC.element_to_be_clickable((By.CSS_SELECTOR, sget("login","pass_continue_btn",".b24net-password-enter-form__continue-btn")))).click()
        log_ok("Senha preenchida e 'Continuar' clicado.")
    except Exception:
        log_warn("Etapa de senha ignorada (provável sessão existente).")

# -------- Notificações --------
EVENT_ID_RE = re.compile(r"[?&]EVENT_ID=(\d+)\b", re.I)
PT_MONTHS = {"janeiro":1,"fevereiro":2,"março":3,"marco":3,"abril":4,"maio":5,"junho":6,"julho":7,"agosto":8,"setembro":9,"outubro":10,"novembro":11,"dezembro":12}

def open_notifications(driver, wait):
    icon_sel = sget("notifications", "icon", default='[class*="--o-notification"]')
    log(f"Abrindo painel de notificações… ({icon_sel})")
    icon = wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, icon_sel)))
    icon.click()
    root_sel = sget("notifications", "root", default=".bx-im-content-notification__elements")
    wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, root_sel)))
    # scroll para carregar tudo
    try:
        root = driver.find_element(By.CSS_SELECTOR, root_sel)
        for _ in range(4):
            driver.execute_script("arguments[0].scrollTop = arguments[0].scrollHeight;", root)
            time.sleep(0.4)
    except: pass
    driver.save_screenshot(os.path.join(OUT_DIR, "notifications.png"))
    log_ok("Painel de notificações aberto.")

def collect_calendar_notifications(driver, include_we=True):
    root_sel = sget("notifications", "root", default=".bx-im-content-notification__elements")
    link_sel = sget("notifications", "link_selector", default='a[href*="/calendar/?EVENT_ID="]')
    links = []
    try:
        root = driver.find_element(By.CSS_SELECTOR, root_sel)
        links = root.find_elements(By.CSS_SELECTOR, link_sel)
    except Exception:
        log_warn("Contêiner de notificações não encontrado; procurando no DOM inteiro…")
    if not links:
        links = driver.find_elements(By.CSS_SELECTOR, link_sel)

    results = []
    for a in links:
        href = a.get_attribute("href") or ""
        title = a.get_attribute("textContent") or a.text or ""
        m = EVENT_ID_RE.search(href)
        if m:
            item = {"title": title.strip(), "id": m.group(1), "url": href}
            if include_we: item["_we"] = a
            results.append(item)
    return results

def parse_time_text(text: str):
    t = " ".join(text.split()).lower()
    hhmm = re.findall(r"\b(\d{1,2}:\d{2})\b", t)
    inicio = hhmm[0] if len(hhmm) >= 1 else ""
    termino = hhmm[1] if len(hhmm) >= 2 else ""
    m = re.search(r"\b(\d{1,2})\s+de\s+([a-zçãéêáíóúôû]+)\s+de\s+(20\d{2})\b", t)
    if m:
        d = int(m.group(1)); mes_nome = m.group(2); a = int(m.group(3))
        mes = PT_MONTHS.get(mes_nome, 0)
        if mes: return f"{d:02d}/{mes:02d}/{a}", inicio, termino
    from datetime import date, timedelta
    base = NOW.date()
    if "depois de amanhã" in t: base = base + timedelta(days=2)
    elif "amanhã" in t:        base = base + timedelta(days=1)
    elif "hoje" in t:          base = base
    else:                      return "", inicio, termino
    return base.strftime("%d/%m/%Y"), inicio, termino

def click_and_extract_details(driver, wait, link_element):
    link_element.click()
    slider_sel = sget("event_view", "slider_root", default=".calendar-slider-workarea")
    wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, slider_sel)))
    time_sel = sget("event_view", "time_text", default=".calendar-slider-sidebar-head-title")
    time_el = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, time_sel)))
    time_text = time_el.text.strip()
    log(f"Detalhe do evento (texto horário): {time_text}")
    data, inicio, termino = parse_time_text(time_text)
    return {"data": data, "inicio": inicio, "termino": termino}

# -------- Persistência (merge e no-overwrite-quando-vazio) --------
EVENTS_JSON = os.path.join(OUT_DIR, "events.json")
EVENTS_PY   = os.path.join(OUT_DIR, "events.py")

def load_existing_events():
    if not os.path.exists(EVENTS_JSON): return []
    try:
        with open(EVENTS_JSON, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except Exception:
        return []

def merge_events(existing, new_items):
    """Mescla por id. Se o novo tiver data/inicio/termino vazios, preserva os antigos."""
    by_id = {str(e.get("id")): e for e in existing}
    for n in new_items:
        k = str(n.get("id"))
        if k in by_id:
            cur = by_id[k]
            # atualiza campos não vazios
            for key in ["titulo","link","data","inicio","termino"]:
                val = n.get(key)
                if val: cur[key] = val
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

# -------- Main --------
def main():
    log(f"Headless={HEADLESS} | URL base={BITRIX_URL}")
    driver = make_driver()
    try:
        wait = WebDriverWait(driver, 35)
        target_url = selectors.get("login", {}).get("url") or BITRIX_URL
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

        open_notifications(driver, wait)
        notif = collect_calendar_notifications(driver, include_we=True)

        log_ok(f"Notificações de agenda encontradas: {len(notif)}")
        for i, n in enumerate(notif, 1):
            print(f"[EVENTO {i}] ID={n['id']} | TÍTULO={n['title']}")

        # Base extraída agora
        scraped = [{"titulo": n["title"], "id": n["id"], "link": n["url"]} for n in notif]

        # Se não achou nada, NÃO sobrescreve: mantém o que já tinha
        existing = load_existing_events()
        if not scraped:
            log_warn("Nenhuma notificação encontrada. Mantendo events.json atual.")
            write_events_files(existing)
            print("STATUS=NO_NEW_NOTIFICATIONS_KEEPING_PREVIOUS")
            return

        # Enriquecer cada item com data/horário
        enriched = []
        for idx, n in enumerate(notif, 1):
            log(f"Extraindo detalhes do evento {idx}/{len(notif)} (ID={n['id']})…")
            details = {}
            try:
                details = click_and_extract_details(driver, wait, n["_we"])
            except Exception as e:
                log_warn(f"Não foi possível ler detalhes do evento ID={n['id']}: {e}")
            enriched.append({
                "titulo": n["title"], "id": n["id"], "link": n["url"],
                "data": details.get("data",""), "inicio": details.get("inicio",""), "termino": details.get("termino","")
            })

        # Mescla com o que já tinha e salva
        merged = merge_events(existing, enriched)
        write_events_files(merged)
        print("STATUS=OK_NOTIFICATIONS_AND_DETAILS")
    except Exception as e:
        log_err(f"Falha no fluxo: {e}")
        traceback.print_exc()
        print("STATUS=FAIL")
    finally:
        driver.quit()

if __name__ == "__main__":
    main()
