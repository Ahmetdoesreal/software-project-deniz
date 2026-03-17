# client.py / server.py Analizi

Bu proje akışında `server.py` merkezi servis, `client.py` ise öğrenci istemcisi rolünde çalışır.

## Doğrudan ilişkili çekirdek dosyalar

- `server.py`
  HTTP endpoint'lerini, WebSocket oturumunu, kullanıcı durumunu ve sınav zamanlayıcısını yönetir.
- `client.py`
  Sunucuyu keşfeder, login olur, sınav dosyalarını indirir, WebSocket oturumu açar ve istemci tarafı yardımcı modülleri başlatır.
- `shared.py`
  İki yönlü JSON mesajlaşma için encode/decode ve ortak yardımcı fonksiyonları sağlar.
- `events.py`
  `client.py` ve `server.py` arasında kullanılan event adlarını ve payload üreticilerini içerir.
- `discovery.py`
  Sunucu ilanı ve istemci keşfi için UDP discovery akışını sağlar.

## Çalışma sırasında kullanılan yardımcı dosyalar

- `custommodules/replay_recorder.py`
  `client.py` tarafından import edilir; ekran kaydı/replay mekanizmasını yürütür.
- `custommodules/process_monitor.py`
  `client.py` tarafından import edilir; çalışan süreçleri izler ve loglar.
- `client_gui.py`
  `client.py` tarafından alt süreç olarak açılır; sınav süresini görsel olarak gösterir.
- `server_gui.py`
  `server.py --gui` ile alt süreç olarak açılır; bağlı istemcileri ve komutları gösterir.
- `client_launcher.py`
  `client.py` için GUI tabanlı başlatıcıdır.
- `server_launcher.py`
  `server.py` için GUI tabanlı başlatıcıdır.
- `allowed_users.json`
  `server.py` login doğrulamasında kullanılır.
- `requirements.txt`
  Çekirdek bağımlılıklar: `aiohttp`, `psutil`.
- `setup.py`
  Projenin kurulum/bağımlılık kontrolünü yapar.
- `macos_privacy.py`
  `setup.py` içinden macOS ekran kaydı izni kontrolü için kullanılır.

## İlişkili ama yardımcı/test niteliğinde dosyalar

- `run_demo.py`, `run_demo.sh`, `run_demo.bat`
  `client.py` ve `server.py` için demo başlatma scriptleri.
- `test_auth.py`, `test_comm.py`
  `client.py` ve `server.py` davranışını subprocess ile test eder.
- `test_exam.zip`
  `server.py --exam-files` akışında kullanılabilecek örnek sınav paketi.
- `TEMPLATE_new_event.py`
  `events.py`, `server.py` ve `client.py` arasına yeni event eklemek için rehber şablon.
- `data/`
  Sunucu kullanıcı verisi ve istemci indirme/kayıt çıktıları burada oluşur.

## Ayrı klasöre taşınanlar

Bu öğeler çekirdek çalışma akışında kullanılmıyor ya da ayrı bir demo/arşiv niteliğinde:

- `exam_tls_demo/`
- `exam_tls_demo.zip`
- `CHEATSHEET.md`
- `session_archive/`
- `custommodules/replay_recorder_macos.py`
- `custommodules/replay_recorder_macos_auto.py`

Not:
- `shared.py` çalışma ağacında zaten değişmiş durumdaydı; bu analiz sırasında içeriğine dokunulmadı.
