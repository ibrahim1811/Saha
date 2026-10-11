# Saha — Partner Modu (İlayda)

## Amaç
Saha'yı İlayda için hafif bir partner profiliyle kullanılabilir yapmak: küstüm/özledim butonları, kişiye özel haber konuları, sabah ve 23:00 özetleri, Kayra'dan not, ortak hatırlatıcı, özel gün sayacı. Kayra'nın kişisel verileri (not, görev, okul) partnere kapalı.

## Bağlama
- Kayra `/davet` → tek kullanımlık, 24 saat geçerli kod; link `t.me/<bot>?start=KOD`.
- İlayda linkle `/start KOD` gönderir → `settings['partner']` kaydı oluşur, Kayra'ya bildirim gider.
- Yanlış/süresi dolmuş kod: bot sessiz kalır.

## Roller
- `gate`: owner veya partner geçer; diğer herkes durdurulur.
- Partner yalnızca partner handler'larını kullanır (butonlar, /start, /panel). Owner komutları partnere kapalı.
- Partner reply keyboard: `😤 Küstüm` (küsken `🕊 Barıştık`), `🥺 Özledim`. Panel menü butonu partner için de ayarlanır.

## Küs / Barış / Özledim
- Küstüm: `settings['kus'] = {since}`; Kayra'ya "🚨 İlayda sana küstü! Hemen gönlünü al 🌹".
- Küsken saatte bir Kayra'ya hatırlatma; 00:00–08:00 sessiz. Yeniden başlatmada durum geri yüklenir.
- Barıştık: durum temizlenir, Kayra'ya "🕊 Barıştınız, N dakika küs kaldı".
- Özledim: iki yönlü; karşı tarafa "🥺 … seni özledi" bildirimi. Kayra için `/ozledim` komutu.

## Özetler
- Partner sabah (varsayılan 07:00): özel gün sayacı, hava (Buca koordinatı), okul programı (ortak), partnerin haber konuları, varsa en eski gönderilmemiş "💌 Kayra'dan not".
- 23:00 (ikisi için): günün haberleri, yarının programı, yarının havası. Owner akşam özetine haber bölümü eklenir.
- Owner sabah özetine özel gün sayacı eklenir; önemli güne 3 gün kala owner'a hatırlatma.

## Haberler
- Konular: gundem (BBC Türkçe), turkiye, dunya, ekonomi, teknoloji, saglik, yasam, egitim, spor, otomobil (NTV kategori RSS; özet içerir — Google News yalnızca başlık verdiği için seçilmedi).
- `news.fetch(http, limit, topics)`: konular paralel çekilir, aynı haberler ayıklanır, hatalı konu atlanır, hepsi hatalıysa hata.
- Owner ayarına `news_topics` (varsayılan `["teknoloji"]`).

## Veri
- `settings` anahtarları: `partner` {id, name, briefing_time, evening_enabled, news_topics}, `kus` {since}, `invite` {code, expires}.
- `reminders.target` TEXT DEFAULT 'owner' CHECK IN ('owner','partner').
- `love_notes` (id, text, created_at, delivered_at NULL).
- `special_days` (id, name, day DATE, yearly BOOL).
- Ortak program yalnızca `okul` türü.

## Panel
- `/api/me` → {role}. Partner yalnızca `/api/me`, `/api/partner/self` (GET/PUT) kullanabilir; diğerleri 403.
- Partner görünümü: "Benim" ekranı (haber konuları, sabah saati, 23:00 açık/kapalı).
- Owner "💕 İlayda" sekmesi: onun ayarları, not bırak + bekleyen notlar, özel günler, küs durumu, davet linki, partneri kaldır.
- Owner Ayarlar: kendi haber konuları.

## Kod yapısı
- `app/partner.py`: davet, ayar doğrulama, küs süresi/sessiz saat, mesaj metinleri (saf).
- `app/love.py`: gün sayacı, yaklaşan özel gün, not biçimi (saf).
- `news.py`: konu desteği. `bot.py`: partner handler'ları ve job'ları (`partner-sabah`, `partner-aksam`, `kus-hatirlat`, `ozel-gun`).

## Hatalar
- Partnere gönderim başarısız → owner'a "İlayda'ya ulaşılamadı".
- Bir haber konusu düşerse diğerleriyle devam.

## Test
Davet akışı, gate rolleri, küs/barış ve sessiz saat, haber konuları ve ayıklama, partner API 403, hedefli hatırlatıcı, gün sayacı.
