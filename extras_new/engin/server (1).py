from pathlib import Path
import discovery
import runtime_logging
import db_manager
import server_core
from server_core import handle_client, global_timer
# MERT'İN MODÜLÜNÜ İÇERİ AKTARIYORUZ
import db_manager

import asyncio
import websockets

print("🌐 [SUNUCU] Merkezi Sınav Sunucusu Başlatılıyor...")

# 1. Ahmet'in Sistem Hata Kaydedicisini Başlat
# capture_stdout=False ekleyerek Ahmet'in sistemiyle Notebook'un çakışmasını engelliyoruz
runtime_logging.setup_runtime_logging(
    process_name="EXAM_SERVER", 
    log_dir=Path("logs"), 
    capture_stdout=False  # Bunu ekle
)

import os # En üste eklemeyi unutma

async def run_server():
    # --- AYAR: TAM SIFIRLAMA ---
    # True: Her seferinde her şeyi siler (Testler için ideal)
    # False: Çökme sonrası kaldığı yerden devam eder (Gerçek sınav için ideal)
    HARD_RESET = True 

    if HARD_RESET:
        # 1. Disk üzerindeki veritabanı dosyasını sil
        if os.path.exists("server_recovery_db.json"):
            os.remove("server_recovery_db.json")
        
        # 2. RAM'deki listeleri tamamen boşalt
        server_core.active_students.clear()
        server_core.exam_registry.clear()
        print("💥 [SİSTEM] Fabrika ayarlarına dönüldü. Tüm öğrenciler ve cezalar SIFIRLANDI!")
    else:
        # ÇÖKME KURTARMA (CRASH RECOVERY) SİSTEMİ
        kurtarilan_durum = db_manager.load_server_state()
        if kurtarilan_durum:
            server_core.active_students = kurtarilan_durum.get("active_students", {})
            server_core.exam_registry = kurtarilan_durum.get("exam_registry", {})
            print(f"🔄 [RECOVERY] Sistem çökmeden kurtarıldı: {len(server_core.active_students)} öğrenci yüklendi.")
        else:
            server_core.active_students.clear()
            server_core.exam_registry.clear()
            print("🧹 [SİSTEM] Yedek bulunamadı, temiz başlanıyor.")

    server_core.dashboard_counter = 0
    
    # 3. Arka plan görevlerini başlat
    asyncio.create_task(global_timer())
    announcer = discovery.ServerAnnouncer(server_host="127.0.0.1", server_port=8765)
    await announcer.start()

    # Sunucuyu başlat
    async with websockets.serve(handle_client, "0.0.0.0", 8765):
        print("🌐 [SUNUCU] Port 8765 dinleniyor. İstemciler bekleniyor...\n")
        try:
            await asyncio.Future()  
        except asyncio.CancelledError:
            print("🛑 [SİSTEM] Sunucu durduruldu.")
        finally:
            await announcer.stop()

# Sistemi Başlat
#await run_server()
if __name__ == "__main__":
    asyncio.run(run_server())