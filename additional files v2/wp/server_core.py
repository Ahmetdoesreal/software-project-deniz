# server_core.py
import asyncio
import websockets
import json
import time
import os     
from datetime import datetime
import school_service # Yeni Mock Servisimiz

from security_layer import open_secure_packet, verify_signature, hash_password, get_expected_server_token
from instructor_auth import verify_instructor_role
import sys
from pathlib import Path
from runtime_logging import setup_runtime_logging, install_asyncio_exception_logging

# Ahmet'in protokol modülleri
import protocol
import events

# Mert'in Veritabanı Modülü
import db_manager
db_manager.init_db()

# Örnek Oturma Düzeni (ŞUANLIK KULLANILMIYOR)
SEATING_PLAN = {
    "std_01": "127.0.0.1", # Lab bilgisayarı IP'si
    "std_02": "192.168.1.11"
}



# ---------------------------------------------------------
# EKLENDİ (ÖZELLİK 3): JSONL FORMATINDA DOSYAYA LOGLAMA
# ---------------------------------------------------------
def log_event(event_type, details):
    """
    Ahmet'in runtime_logging modülü her şeyi yakaladığı için 
    burada sadece anlamlı bir print yapmamız yeterli.
    """
    print(f"[{event_type.upper()}] {json.dumps(details, ensure_ascii=False)}")
    # Mert'in veritabanına kritik olayları yazmaya devam ediyoruz
    db_manager.log_audit(event_type, "system", "", details, "OK")


async def broadcast_to_exam(exam_id, action, payload):
    """Küresel Komut Koordinasyonu: Belirli bir sınavdaki tüm aktif öğrencilere mesaj gönderir."""
    for sid, info in active_students.items():
        if info.get("exam_id") == exam_id and info.get("ws"):
            try:
                # Ahmet'in checksum'lı protokolüyle sarmalıyoruz
                event_name = getattr(events, action.upper(), action)
                msg = protocol.encode(event_name, payload)
                if isinstance(msg, dict): msg = json.dumps(msg)
                await info["ws"].send(msg)
            except Exception as e:
                print(f"⚠️ [SİSTEM] {sid} kullanıcısına mesaj gönderilemedi: {e}")
# 1) HAFIZA VE DURUM YÖNETİMİ
active_students = {}
exam_registry = {}
dashboard_counter = 0

# IP bazlı login rate-limit (request_start_exam brute-force koruması)
_recent_login_attempts = {}  # ip -> last_attempt_unix_ts
LOGIN_RATE_LIMIT_SEC = 1.0

# 2) ZAMANLAYICI (Global Timer)
# Jupyter hücreleri yeniden çalıştırıldığında eski global_timer task'leri kaybolmaz
# ve birden fazla timer aynı anda time_left'i azaltır → süre 2-3 kat hızlı bitiyor görünür.
# "Generation" sayacı ile sadece en son çağrılan timer çalışır, eskiler natural exit yapar.
_timer_generation = 0

async def global_timer():
    global _timer_generation
    _timer_generation += 1
    my_gen = _timer_generation
    print(f"⏱️ [TIMER] Global timer başladı (generation={my_gen})")

    timer_tick = 0
    while True:
        await asyncio.sleep(1)
        # Eğer daha yeni bir timer başlatıldıysa bu eski timer kendini kapatsın
        if my_gen != _timer_generation:
            print(f"⏱️ [TIMER] Eski timer (gen={my_gen}) kapatıldı, yenisi (gen={_timer_generation}) çalışıyor.")
            return
        timer_tick += 1
        
        if timer_tick % 5 == 0:
            db_manager.save_server_state(active_students, exam_registry)

        for sid, info in active_students.items():
            # DÜZELTME: Süre SADECE öğrenci sınavdaysa ve bağlantısı varsa akar.
            # Bağlantı koparsa veya ihlal yaparsa süre otomatik donar.
            if info["state"] == "in_progress" and info.get("ws") is not None:
                info["time_left"] -= 1

                # Her 60 saniyede bir BİREYSEL senkronizasyon (Sadece aktif/canlı bağlantı olanlara)
                if info["state"] == "in_progress" and info["time_left"] > 0 and info["time_left"] % 60 == 0:
                    if info.get("ws"):
                        try:
                            event_name = getattr(events, "SYNC_TIME", "sync_time")
                            sync_msg = protocol.encode(event_name, {"time_left_seconds": info["time_left"]})
                            if isinstance(sync_msg, dict): sync_msg = json.dumps(sync_msg)
                            await info["ws"].send(sync_msg)
                        except: pass

                if info["time_left"] <= 0:
                    info["state"] = "completed"
                    print(f"\n✅ [BİTTİ] {sid} numaralı öğrencinin SÜRESİ DOLDU!")
                    log_event("exam_completed", {"student_id": sid})
                    
                    if info.get("ws"):
                        try:
                            event_name = getattr(events, "EXAM_END", "exam_end")
                            end_msg = protocol.encode(event_name, {})
                            if isinstance(end_msg, dict): end_msg = json.dumps(end_msg)
                            await info["ws"].send(end_msg)
                        except: pass

def _map_ahmet_to_internal(payload):
    """Ahmet'in PROCESS_CATCH formatını senin risk skorlama sistemine bağlar."""
    flags = payload.get("matches", payload.get("flags", []))
    return {
        "action": "status_update",
        "student_id": payload.get("student_id", ""),
        "session_token": payload.get("session_token"),
        "security": {
            "violation_alert": len(flags) > 0,
            "violation_type": flags[0] if flags else None,
            "details": {
                "active_window": payload.get("active_window", "Bilinmiyor"),
                "open_apps": payload.get("open_apps", []),
                "idle_seconds": payload.get("idle_seconds", -1)
            }
        }
    }

# 3) ANA İLETİŞİM FONKSİYONU
async def handle_client(websocket):
    global dashboard_counter, active_students, exam_registry
    try:
        async for message in websocket:
            raw_msg = json.loads(message)
            data = {}

            # --- KATMAN 1: NAZ'IN ŞİFRELİ PAKETİ GELDİYSE ÖNCE AÇ! ---
            if "encrypted" in raw_msg and "signature" in raw_msg:
                try:
                    data = open_secure_packet(message) 
                except Exception as e:
                    print(f"🚫 [SİBER GÜVENLİK] Geçersiz paket reddedildi! Sebep: {e}")
                    continue 
            else:
                data = raw_msg

            # --- KATMAN 2: AHMET'İN PROTOKOLÜ ---
            if "event" in data and "checksum" in data:
                event_name, payload = protocol.decode(json.dumps(data))
                
                if event_name == protocol.DECODE_ERROR:
                    print("⚠️ [PROTOKOL] Ahmet'in katmanı checksum hatası verdi!")
                    continue

                if event_name == getattr(events, "START_EXAM", "start_exam"):
                    action = "request_start_exam"
                    data = {**payload, "action": action}
                elif event_name == getattr(events, "PROCESS_CATCH", "process_catch"):
                    action = "status_update"
                    data = _map_ahmet_to_internal(payload)
                else:
                    action = data.get("action")
            else:
                # --- KATMAN 3: GERİYE UYUMLULUK ---
                action = data.get("action")

            student_id = data.get("student_id")

            # RATE LIMITING
            if student_id and student_id in active_students:
                now = time.time()
                
                # Paketin buffer'dan gelip gelmediğini kontrol et
                is_buffered = data.get("buffered", False)
                
                # Eğer paket buffered DEĞİLSE ve 0.5 saniyeden hızlı geldiyse reddet
                if not is_buffered and (now - active_students[student_id].get("last_msg_time", 0) < 0.5):
                    continue 
                    
                active_students[student_id]["last_msg_time"] = now

            if action == "register_exam": # EĞİTMENİN YENİ SINAV KAYIT KOMUTU
                #  FIX: Eğitmen Token Kontrolü (Doğru Kullanım)
                ok, err = verify_instructor_role(data, "register_exam")
                if not ok: 
                    print(f"🚫 [GÜVENLİK İHLALİ] Yetkisiz sınav oluşturma girişimi REDDEDİLDİ! Sebep: {err}")
                    await websocket.send(json.dumps({"status": "error", "message": f"Yetkisiz işlem! {err}"}))
                    continue

                exam_id = data["payload"]["exam_id"]
                exam_registry[exam_id] = data["payload"]
                db_manager.create_exam_session(exam_id, data["payload"])
                print(f"\n✅ [EĞİTMEN] Yeni Sınav Aktif Edildi: {exam_id}")
                log_event("exam_registered", {"exam_id": exam_id})
                await websocket.send(json.dumps({"status": "exam_registered"}))
            # --- OTURUM YÖNETİMİ AKSİYONLARI ---

            elif action in ("start_all_students", "start_exam"):
                # EĞİTMEN KOMUT KOORDİNASYONU
                # NOT: instructor_demo "start_exam" gönderir, eski client'lar "start_all_students".
                # Naz'ın ROLE_PERMISSIONS'ında "start_exam" tanımlı olduğu için yetki kontrolü o isimle.
                ok, err = verify_instructor_role(data, "start_exam")
                if not ok:
                    await websocket.send(json.dumps({"status": "error", "message": f"Yetkisiz işlem! {err}"}))
                    continue

                payload_data = data.get("payload") or {}
                exam_id = payload_data.get("exam_id")
                if not exam_id:
                    await websocket.send(json.dumps({"status": "error", "message": "exam_id eksik."}))
                    continue
                
                # Sınavın başladığını mühürle (Sonradan gelenler için)
                if exam_id in exam_registry:
                    exam_registry[exam_id]["is_started"] = True
                # Sınava kayıtlı herkesi WAITING'den IN_PROGRESS'e çek
                started_count = 0
                for sid, info in active_students.items():
                    if info.get("exam_id") == exam_id and info.get("state") == "waiting_for_start":
                        info["state"] = "in_progress"
                        started_count += 1

                await broadcast_to_exam(exam_id, "exam_started_ack", {"status": "success"})
                print(f"🚀 [SİSTEM] {exam_id} sınavı başlatıldı! ({started_count} öğrenci aktif edildi)")
                log_event("exam_started_all", {"exam_id": exam_id, "count": started_count})
                await websocket.send(json.dumps({
                    "status": "success",
                    "message": f"{exam_id} başlatıldı, {started_count} öğrenci aktif."
                }))
            elif action == "resume_student":
                ok, err = verify_instructor_role(data, "resume_student")
                if not ok:
                    await websocket.send(json.dumps({"status": "error", "message": f"Yetkisiz işlem! {err}"}))
                    continue
                    
                hedef_id = data.get("student_id")
                if hedef_id in active_students:
                    active_students[hedef_id]["state"] = "in_progress"

                    # DÜZELTME: Öğrencinin kilitli ekranını açması için sinyal gönder
                    target_ws = active_students[hedef_id].get("ws")
                    if target_ws:
                        try:
                            await target_ws.send(json.dumps({"action": "exam_resumed", "status": "success"}))
                        except: pass

                    print(f"\n🟢 [EĞİTMEN KOMUTU] {hedef_id} affedildi ve kilit açma sinyali gönderildi.")
                    log_event("student_resumed", {"student_id": hedef_id})
                    await websocket.send(json.dumps({"status": "success", "message": f"{hedef_id} affedildi."}))
                else:
                    # DÜZELTME: Hedef öğrenci bulunamazsa eğitmen sessizce başarısız zannetmesin
                    print(f"⚠️ [EĞİTMEN] '{hedef_id}' affedilmek istendi ama aktif öğrenciler arasında değil.")
                    log_event("resume_student_failed", {"student_id": hedef_id, "reason": "not_active"})
                    await websocket.send(json.dumps({
                        "status": "error",
                        "message": f"Öğrenci '{hedef_id}' aktif değil veya sistemde yok."
                    }))

            elif action == "request_start_exam": # ÖĞRENCİNİN SINAVA GİRİŞ VE DOĞRULAMA TALEBİ
                student_id = data.get("student_id")
                password = data.get("password", "")
                exam_id = data.get("exam_id")
                client_ip = websocket.remote_address[0] # Bağlanan cihazın IP'si

                # ------------------------------------------------------------------
                # 🛡️ IP BAZLI RATE LIMIT (brute-force credential denemelerini yavaşlat)
                # ------------------------------------------------------------------
                now_ts = time.time()
                last_attempt = _recent_login_attempts.get(client_ip, 0.0)
                if now_ts - last_attempt < LOGIN_RATE_LIMIT_SEC:
                    await websocket.send(json.dumps({
                        "status": "error",
                        "message": "Çok hızlı deneme yapıyorsunuz. Lütfen bir saniye bekleyin."
                    }))
                    continue
                _recent_login_attempts[client_ip] = now_ts

                # ------------------------------------------------------------------
                # 🛡️ SINAV KAYIT KONTROLÜ (eğitmen henüz kaydetmediyse reddet)
                # ------------------------------------------------------------------
                if exam_id and exam_id not in exam_registry:
                    await websocket.send(json.dumps({
                        "status": "error",
                        "message": f"Sınav '{exam_id}' henüz aktif değil. Eğitmenin sınavı kaydetmesini bekleyiniz."
                    }))
                    continue

                # ------------------------------------------------------------------
                # 🚨 ANTI-CHEAT: AYNI BİLGİSAYARDAN ÇİFT GİRİŞİ ENGELLEME
                # ------------------------------------------------------------------
                already_connected_from_ip = False
                for sid, info in active_students.items():
                    # Eğer başka bir öğrenci ID'si ile bu IP'den zaten aktif bir bağlantı varsa
                    if sid != student_id and info.get("ws") and info["ws"].remote_address[0] == client_ip:
                        already_connected_from_ip = True
                        break
                
                if already_connected_from_ip:
                    print(f"🚨 [GÜVENLİK İHLALİ] {client_ip} IP adresinden 2. bir giriş denemesi reddedildi!")
                    await websocket.send(json.dumps({
                        "status": "error", 
                        "message": "Güvenlik İhlali: Bu bilgisayardan zaten aktif bir sınav oturumu bulunuyor! Uygulamayı birden fazla kez açamazsınız."
                    }))
                    continue # İşlemi reddet ve döngüye devam et

                # 1. ADIM: HOCANIN İSTEDİĞİ CATS/ORION DOĞRULAMASI
                success, name_or_err = school_service.verify_user(student_id, password)
                if not success:
                    await websocket.send(json.dumps({"status": "error", "message": f"CATS Hatası: {name_or_err}"}))
                    continue

                # 2. ADIM: GÜVENLİK VE İMZA KONTROLÜ (Engin & Naz)
                client_sig = data.pop("auth_signature", None)
                eski_surum_mu = False
                if client_sig:
                    msg_str = json.dumps(data, sort_keys=True)
                    if not verify_signature(msg_str, client_sig):
                        await websocket.send(json.dumps({"status": "error", "message": "Güvenlik İhlali: İmzalı Paket Hatası!"}))
                        continue
                else:
                    eski_surum_mu = True

                # 3. ADIM: OTURUM YÖNETİMİ VE CRASH RECOVERY
                session_token = get_expected_server_token(student_id)
                
                if student_id in active_students:
                    # Sunucu çöktüyse veya koptuysa geri bağla (CRASH RECOVERY)
                    if active_students[student_id].get("ws") is None:
                        active_students[student_id]["ws"] = websocket
                        yeni_state = active_students[student_id]["state"]
                        print(f"🔄 [RECOVERY] {student_id} oturumu kurtarıldı. Durum: {yeni_state}")

                        # DÜZELTME: State'e göre doğru response gönder
                        # waiting_for_start → auth_success (öğrenci bekleme odasında)
                        # in_progress / disconnected_paused / İhlal → exam_started_ack (sınav devam)
                        if yeni_state == "waiting_for_start":
                            # Bekleme odasında reconnect — eğitmen henüz başlatmadı
                            await websocket.send(json.dumps({
                                "action": "auth_success",
                                "status": "success",
                                "login_name": active_students[student_id].get("login_name", student_id),
                                "message": "Bekleme odasında yeniden bağlandınız. Eğitmen sınavı başlatana kadar lütfen bekleyiniz.",
                                "session_token": session_token,
                                "reconnected": True
                            }))
                        else:
                            # Sınav devam ediyordu → otomatik başlat ve kalan süreyi gönder
                            await websocket.send(json.dumps({
                                "action": "exam_started_ack",
                                "status": "success",
                                "session_token": session_token,
                                "reconnected": True,
                                "time_left_seconds": active_students[student_id]["time_left"]
                            }))
                            # State düzeltmesi: koptuğu için disconnected_paused'taydı, geri in_progress'e al
                            if yeni_state == "disconnected_paused":
                                active_students[student_id]["state"] = "in_progress"
                        continue

                # 4. ADIM: YENİ OTURUM OLUŞTURMA (Bekleme Odası)
                # Süreyi exam_registry'den oku (yoksa default 40 dk = 2400 sn)
                # 4. ADIM: YENİ OTURUM OLUŞTURMA
                exam_meta = exam_registry.get(exam_id, {})
                is_already_started = exam_meta.get("is_started", False)
                initial_state = "in_progress" if is_already_started else "waiting_for_start"

                active_students[student_id] = {
                    "ws": websocket, "state": initial_state, "exam_id": exam_id,
                    "time_left": int(exam_meta.get("duration_minutes", 40)) * 60, 
                    "session_token": session_token, "last_seq": 0,
                    "total_risk_score": 0, "login_name": name_or_err
                }
                
                print(f"🎓 [OTURUM] {name_or_err} ({student_id}) CATS üzerinden doğrulandı. BEKLEME ODASINA ALINDI.")
                log_event("student_authenticated", {"student_id": student_id, "name": name_or_err})
                
                await websocket.send(json.dumps({
                    "action": "auth_success", 
                    "status": "success", 
                    "login_name": name_or_err,  # İsim dinamikleşsin diye eklendi
                    "message": f"Hoş geldin {name_or_err}. Eğitmen sınavı başlatana kadar lütfen bekleyiniz.",
                    "session_token": session_token,
                    "warning": "⚠️ DİKKAT: Eski sürüm istemci!" if eski_surum_mu else None  # Geri eklendi!
                }))

            elif action == "change_duration": # EĞİTMENİN SÜREYİ UZATMA KOMUTU
                ok, err = verify_instructor_role(data, "change_duration")
                if not ok:
                    await websocket.send(json.dumps({"status": "error", "message": f"Yetkisiz işlem! {err}"}))
                    continue

                payload_data = data.get("payload") or {}
                extra_mins = payload_data.get("extra_minutes", 5)
                target_exam = payload_data.get("exam_id")
                if not target_exam:
                    await websocket.send(json.dumps({"status": "error", "message": "exam_id eksik."}))
                    continue

                affected = 0
                for sid, info in active_students.items():
                    if info.get("exam_id") == target_exam:
                        info["time_left"] += (int(extra_mins) * 60)
                        affected += 1
                print(f"⏰ [EĞİTMEN] {target_exam} sınav süresi {extra_mins} dk uzatıldı. ({affected} öğrenci)")
                log_event("duration_changed", {"exam_id": target_exam, "extra_minutes": extra_mins, "count": affected})
                await broadcast_to_exam(target_exam, "duration_updated", {"added_minutes": extra_mins})
                await websocket.send(json.dumps({
                    "status": "success",
                    "message": f"{target_exam} süresi {extra_mins} dk uzatıldı."
                }))

            elif action == "force_stop_exam":
                ok, err = verify_instructor_role(data, "force_stop_exam")
                if not ok:
                    await websocket.send(json.dumps({"status": "error", "message": f"Yetkisiz işlem! {err}"}))
                    continue

                target_exam = (data.get("payload") or {}).get("exam_id")
                if not target_exam:
                    await websocket.send(json.dumps({"status": "error", "message": "exam_id eksik."}))
                    continue

                stopped = 0
                for sid, info in active_students.items():
                    if info.get("exam_id") == target_exam:
                        info["state"] = "completed"
                        info["time_left"] = 0
                        stopped += 1
                        # Öğrenciye sınavın bittiğini bildir
                        target_ws = info.get("ws")
                        if target_ws:
                            try:
                                event_name = getattr(events, "EXAM_END", "exam_end")
                                end_msg = protocol.encode(event_name, {})
                                if isinstance(end_msg, dict): end_msg = json.dumps(end_msg)
                                await target_ws.send(end_msg)
                            except: pass

                print(f"🛑 [EĞİTMEN] {target_exam} zorla durduruldu. ({stopped} öğrenci)")
                log_event("exam_force_stopped", {"exam_id": target_exam, "count": stopped})
                await websocket.send(json.dumps({
                    "status": "success",
                    "message": f"{target_exam} durduruldu, {stopped} öğrenci etkilendi."
                }))

            # 2. Mevcut Sınavları Listeleme (Öğrencinin ComboBox'ı için)
            elif action == "get_active_exams":
    #            Sadece kayıtlı ve henüz bitmemiş sınavları dön
                available = [{"id": k, "name": v["name"]} for k, v in exam_registry.items()]
                await websocket.send(json.dumps({"action": "active_exams_list", "exams": available}))    

            elif action == "status_update":
                student_id = data.get("student_id")
                token = data.get("session_token")

                if student_id in active_students and active_students[student_id]["session_token"] == token:
                    security_data = data.get("security", {})
                    details = security_data.get("details", {}) or {}

                    # --- ENGİN: Integrity Fields ---
                    seq_no = data.get("seq", 0)
                    session_id = data.get("session_id", "unknown")
                    is_buffered = data.get("buffered", False)
                    queued_at = data.get("queued_at", datetime.now().isoformat())

                    active_students[student_id]["last_seq"] = seq_no
                    active_students[student_id]["client_session_id"] = session_id
                    active_students[student_id]["last_msg_received"] = datetime.now().isoformat()

                    # --- AHMET: Aktif pencere & uygulama listesi (HER ZAMAN izle) ---
                    aktif_pencere = details.get("active_window") or "(boş)"
                    acik_uygulamalar = details.get("open_apps", []) or []
                    idle_seconds = details.get("idle_seconds", -1)
                    flags = details.get("flags", []) or []

                    # Dashboard için mevcut pencereyi her zaman güncelle (ihlal olmasa bile)
                    active_students[student_id]["current_window"] = aktif_pencere
                    active_students[student_id]["current_apps"] = acik_uygulamalar[:10]
                    active_students[student_id]["idle_seconds"] = idle_seconds
                    active_students[student_id]["last_flags"] = flags

                    # --- RİSK SKORU: Her status_update'ta canlı hesapla (sadece ihlalde değil) ---
                    high_risk_words = ["chatgpt", "discord", "whatsapp", "telegram", "gemini",
                                       "claude", "chegg", "stackoverflow", "openai", "copilot"]
                    medium_risk_words = ["google", "bing", "brave", "search", "yandex",
                                         "chrome", "firefox", "edge", "opera", "youtube"]

                    tum_uygulamalar_str = (aktif_pencere + " " + " ".join(acik_uygulamalar)).lower()
                    ek_skor = 0
                    matched_words = []
                    for word in high_risk_words:
                        if word in tum_uygulamalar_str:
                            ek_skor += 40
                            matched_words.append(word)
                    for word in medium_risk_words:
                        if word in tum_uygulamalar_str:
                            ek_skor += 15
                            matched_words.append(word)

                    mevcut_skor = active_students[student_id].get("total_risk_score", 0)
                    has_violation = security_data.get("violation_alert") == True

                    # Skor sadece ihlal varken artar (aksi takdirde yanlış pozitiflerle dolup taşar)
                    if has_violation or ek_skor > 0:
                        yeni_skor = min(mevcut_skor + ek_skor, 100)
                    else:
                        yeni_skor = mevcut_skor

                    risk_level = ("KRİTİK" if yeni_skor >= 80 else
                                  "YÜKSEK" if yeni_skor >= 40 else
                                  "ORTA"   if yeni_skor > 0  else
                                  "TEMİZ")

                    active_students[student_id]["total_risk_score"] = yeni_skor
                    active_students[student_id]["risk_level"] = risk_level

                    # --- DURUM: Sadece YÜKSEK risk durumunda dondur (FOCUS_LOST gibi minörler artık dondurmaz) ---
                    # --- DURUM: Sadece YÜKSEK risk durumunda dondur ---
                    if has_violation and yeni_skor >= 40:
                        active_students[student_id]["state"] = "İhlal Yaptı - Donduruldu"
                        
                        # 🚨 YENİ: ÖĞRENCİYE AĞ ÜZERİNDEN "DUR" SİNYALİ GÖNDER!
                        try:
                            # Engin'in _async_listen_for_server_push dinleyicisini tetikler
                            msg = json.dumps({"action": "exam_end", "message": "Güvenlik ihlali nedeniyle sınavınız donduruldu!"})
                            await websocket.send(msg)
                        except Exception:
                            pass

                    # --- İhlal varsa loglama + DB'ye kayıt ---
                    if has_violation:
                        v_type = security_data.get("violation_type", "Bilinmeyen İhlal")
                        zaman = queued_at if is_buffered else datetime.now().isoformat()

                        active_students[student_id]["last_violation"] = {
                            "type": v_type, "window": aktif_pencere, "time": zaman,
                            "risk_score": yeni_skor, "risk_level": risk_level,
                            "matched_keywords": matched_words,
                            "buffered": is_buffered
                        }

                        log_event("violation_alert", {
                            "student_id": student_id, "score": yeni_skor,
                            "level": risk_level, "type": v_type, "window": aktif_pencere,
                            "matched": matched_words,
                            "seq": seq_no, "buffered": is_buffered, "queued_at": queued_at
                        })

                        buffer_str = "[GECİKMELİ] " if is_buffered else ""
                        frozen_str = " 🧊 DONDURULDU" if yeni_skor >= 40 else ""
                        print(f"\n🚨 [ALARM] {buffer_str}{student_id} → {v_type}{frozen_str}")
                        print(f"   ↳ Skor: %{yeni_skor} ({risk_level}) | Pencere: {aktif_pencere}")
                        if matched_words:
                            print(f"   ↳ Eşleşen anahtar kelimeler: {', '.join(matched_words)}")

                        db_manager.save_violation_to_db(student_id, v_type, aktif_pencere, yeni_skor)
                        db_manager.record_monitoring_event(student_id, "VIOLATION", {
                            "type": v_type, "window": aktif_pencere,
                            "apps": acik_uygulamalar, "score": yeni_skor,
                            "matched": matched_words,
                            "seq": seq_no, "buffered": is_buffered, "session_id": session_id
                        }, "CRITICAL")
                    else:
                        # İhlal yok ama her HB'de izleme verisini düşük seviye logla
                        db_manager.record_monitoring_event(student_id, "HEARTBEAT", {
                            "window": aktif_pencere,
                            "apps": acik_uygulamalar[:5],
                            "idle": idle_seconds,
                            "seq": seq_no
                        }, "INFO")
 
            elif action == "get_dashboard_data":
                dashboard_counter += 1
                formatted_students = {}
                for sid, info in active_students.items():
                    if info["state"] == "completed": continue
                    time_str = f"{info.get('time_left', 0)//60:02d}:{info.get('time_left', 0)%60:02d}"
                    
                    # YENİ EKLENDİ: Son ihlal penceresini eğitmen uygulamasına gönder
                    last_violation = info.get("last_violation", {})
                    last_window = last_violation.get("window", "-")

                    formatted_students[sid] = {
                        "state": info["state"], "exam_id": info.get("exam_id"), 
                        "time_left_formatted": time_str, "risk_score": info.get("total_risk_score", 0),
                        "risk_level": info.get("risk_level", "TEMİZ"),
                        "last_window": last_window  # <- Bu satır olmadan panelde pencere görünmez
                    }

                await websocket.send(json.dumps({
                    "action": "dashboard_update", "active_students_count": len(active_students), "students": formatted_students
                }))
                print(f"\r📊 [SİSTEM] Dashboard güncellendi. (İstek: {dashboard_counter})", end="", flush=True)

            
                
    except Exception as e:
        # Bağlantı zorla kesildiğinde çıkan gereksiz ağ hatalarını filtrele
        hata_str = str(e).lower()
        if "no close frame" not in hata_str and "connection is closed" not in hata_str:
            print(f"❌ [SİSTEM HATASI] Beklenmedik bir sorun oluştu: {e}")
    finally:
        for sid, info in active_students.items():
            if info["ws"] == websocket:
                info["ws"] = None
                if info["state"] == "in_progress":
                    info["state"] = "completed" if info.get("time_left", 1) <= 0 else "disconnected_paused"
                    log_event("student_disconnected", {"student_id": sid})
                    print(f"\n🔌 [KOPTU] Öğrenci {sid} hattan düştü. Durumu donduruldu.")
                db_manager.record_student_disconnect(sid)
                break