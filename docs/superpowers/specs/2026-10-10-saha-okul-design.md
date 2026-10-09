# Saha — Okul, YKS, foto menüsü, sesli komut, hava uyarıları

Kullanıcı seçimi: 5, 6, 10, 11, 12, 13, (14), 16, 23, 28. 22 (İzmirim Kart) yapılamaz: herkese açık bakiye API'si yok.

## 1. Ortak niyet yönlendirici (28)
`app/intents.py`: `route(text) -> "reminder" | "task" | "exam" | "grade" | "absence" | None`. Hem yazılı mesaj hem sesli mesajın yazıya çevrilmiş hali buradan geçer.
- Sesli mesaj: önce yazıya çevrilir; bir niyet çıkarsa o iş yapılır (cevapta "🎤 …" ile ne anlaşıldığı gösterilir), çıkmazsa eskisi gibi not olarak kaydedilir.

## 2. Fotoğraf menüsü (5, 6)
Fotoğraf gelince: `📚 Ders programı` / `📝 Ders notu` / `❓ Soru çöz`.
- Ders programı: mevcut akış (okul / cumartesi / pazar seçimi ile).
- Ders notu: görsel model yazıya çevirir → ders seçimi (okul programındaki ders adları + "Diğer") → `notes` tablosuna `subject` ile kaydedilir.
- Soru çöz: görsel model soruyu metne döker → metin modeli (gpt-oss-120b, reasoning orta) adım adım çözer, sonucu kısa verir.

## 3. Notlar ve ortalama (10)
`grades(id, subject, label, score NUMERIC, created_at)`. "fizik 1. yazılı 85", "kimya performans 90" → LLM ayrıştırma `{subject, label, score 0-100}`.
- Ders ortalaması = notların ortalaması. Dönem ortalaması = ders ortalamalarının haftalık ders saatine göre ağırlıklı ortalaması (saat okul programından sayılır; programda yoksa ağırlık 1).
- `/notlarim`, panelde Okul sekmesi.

## 4. Devamsızlık (11)
`absences(id, day DATE UNIQUE, excused BOOL, half BOOL)`. "bugün okula gitmedim", "dün özürlü devamsızlık", `/devamsizlik`.
- MEB: özürsüz sınır 10 gün, toplam 30 gün; yarım gün 0,5. 8 özürsüz / 25 toplamda uyarı.

## 5. Okul takvimi (12) ve YKS (13, 14, 16)
- `app/calendar_tr.py`: 2026-2027 MEB takvimi sabit veri (1. dönem 14.09.2026–22.01.2027, ara tatil 16–20.11.2026, yarıyıl 25.01–05.02.2027, 2. ara tatil 08–12.03.2027, yıl sonu 25.06.2027).
- Sabah özetinde tek satır: "🎯 YKS'ye 252 gün (tahmini 19 Haziran)" + yaklaşan takvim olayı (14 gün içindeyse) + tatil günü bilgisi.
- Ayarlar: `yks_date` (varsayılan 2027-06-19, tahmini), `target_tyt`, `target_ayt` (boş olabilir).
- `exams(id, kind 'TYT'|'AYT', total NUMERIC, details JSONB, taken DATE)`. "tyt deneme 78 net", "deneme: türkçe 32 mat 28 fen 10 sosyal 8".
- Hedef: son 3 denemenin ortalaması vs hedef → "Hedefe 12 net var".

## 6. Hava uyarıları (23)
Job her 2 saatte (07–21 arası). Bugünün kalan saatleri için: fırtına (WMO ≥ 95), sıcak ≥ 35°, kuvvetli rüzgâr ≥ 50 km/s, sağanak (saatlik yağış ihtimali ≥ 70), ani düşüş (3 saatte ≥ 8°). Her tür günde bir kez (bellekte, gün değişince sıfırlanır). Ayar: `weather_alerts` aç/kapa.

## Panel
Yeni **Okul** sekmesi: YKS geri sayım + deneme grafiği (SVG) + hedef; ders ortalamaları; devamsızlık sayaçları; takvim.

## Hata yönetimi / test
Her ayrıştırıcı saf fonksiyon + birim testi; LLM mock. DB testleri Neon test dalında. Var olan 244 test yeşil kalır.
