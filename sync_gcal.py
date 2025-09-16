# sync_gcal.py
import os, json
from datetime import datetime
from dateutil import tz
from dotenv import load_dotenv

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request

# ========= Config =========
load_dotenv()
EVENTS_PATH = os.path.join("out", "events.json")
SCOPES = ["https://www.googleapis.com/auth/calendar"]
CAL_ID = os.getenv("GOOGLE_CALENDAR_ID", "primary")
TZ_NAME = os.getenv("TZ", "America/Sao_Paulo")

def log(m): print(f"[SYNC] {m}", flush=True)
def ok(m):  print(f"[OK]  {m}", flush=True)
def warn(m):print(f"[!]  {m}", flush=True)
def err(m): print(f"[ERR] {m}", flush=True)

# ========= Auth =========
def get_service():
    creds = None
    if os.path.exists("token.json"):
        creds = Credentials.from_authorized_user_file("token.json", SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not os.path.exists("credentials.json"):
                raise RuntimeError("credentials.json não encontrado.")
            flow = InstalledAppFlow.from_client_secrets_file("credentials.json", SCOPES)
            creds = flow.run_local_server(port=0)
        with open("token.json", "w") as f:
            f.write(creds.to_json())
    return build("calendar", "v3", credentials=creds)

# ========= Helpers =========
def to_rfc3339(date_br: str, time_hm: str, tz_name: str) -> str:
    if not date_br or not time_hm:
        return ""
    d, m, y = map(int, date_br.split("/"))
    hh, mm = map(int, time_hm.split(":"))
    return datetime(y, m, d, hh, mm, tzinfo=tz.gettz(tz_name)).isoformat()

def build_body(ev):
    titulo  = ev["titulo"].strip()
    bitrix  = str(ev["id"]).strip()
    data    = ev["data"].strip()
    inicio  = ev["inicio"].strip()
    termino = ev["termino"].strip()
    link    = ev.get("link", "").strip()

    body = {
        "summary": titulo,
        "start": {"dateTime": to_rfc3339(data, inicio, TZ_NAME), "timeZone": TZ_NAME},
        "end":   {"dateTime": to_rfc3339(data, termino, TZ_NAME), "timeZone": TZ_NAME},
        "extendedProperties": {"private": {"bitrix_id": bitrix}}
    }
    desc = [f"Fonte: Bitrix", f"ID: {bitrix}"]
    if link:
        desc.append(link)
        body["source"] = {"title": "Bitrix", "url": link}
    body["description"] = "\n".join(desc)
    return body

def find_existing_by_bitrix_id(svc, cal_id, bitrix_id: str):
    resp = svc.events().list(
        calendarId=cal_id,
        privateExtendedProperty=f"bitrix_id={bitrix_id}",
        singleEvents=True,
        timeMin="1970-01-01T00:00:00Z",
        timeMax="2100-01-01T00:00:00Z",
        maxResults=2500
    ).execute()
    items = resp.get("items", [])
    return items[0] if items else None

# ========= Main =========
def main():
    log(f"Calendar ID: {CAL_ID} | TZ={TZ_NAME}")
    if not os.path.exists(EVENTS_PATH):
        err(f"{EVENTS_PATH} não encontrado.")
        return
    with open(EVENTS_PATH, "r", encoding="utf-8") as f:
        events = json.load(f)
    if not isinstance(events, list) or not events:
        warn("events.json vazio ou inválido; nada para sincronizar.")
        return

    svc = get_service()
    created = skipped = 0

    for ev in events:
        if not all(ev.get(k) for k in ("titulo","id","data","inicio","termino")):
            warn(f"Incompleto, pulando: {ev}")
            continue

        bitrix_id = str(ev["id"]).strip()
        try:
            existing = find_existing_by_bitrix_id(svc, CAL_ID, bitrix_id)
            if existing:
                log(f"Já existe (skip): {ev['titulo']} (bitrix_id={bitrix_id})")
                skipped += 1
                continue

            body = build_body(ev)
            svc.events().insert(calendarId=CAL_ID, body=body, supportsAttachments=False).execute()
            ok(f"Criado: {ev['titulo']} ({ev['data']} {ev['inicio']}-{ev['termino']})")
            created += 1
        except HttpError as e:
            err(f"Falha ao sincronizar '{ev.get('titulo','')}' (bitrix_id={bitrix_id}): {e}")

    log(f"Resumo → criados={created}, pulados={skipped}")

if __name__ == "__main__":
    main()
