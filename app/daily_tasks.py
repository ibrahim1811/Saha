import hashlib
import logging
import random
from datetime import date

log = logging.getLogger(__name__)
START_HOUR = 7
END_HOUR = 23

TASK_POOL = [
    {"theme": "İletişim", "task": "{name}'e bugün en az 3 kez \"seninle konuşmak iyi geliyor\" diye hissettir.", "verification_steps": ["İlk kez içtenlikle söyledin", "İkinci kez içtenlikle söyledin", "Üçüncü kez içtenlikle söyledin"]},
    {"theme": "Şefkat", "task": "{name}'in bugün işini kolaylaştıracak küçük bir yardım yap."},
    {"theme": "Sabır", "task": "Bugün {name}'e kızmadan, 2 dakika dinleyerek cevap ver."},
    {"theme": "Sevgi", "task": "Gün içinde {name}'e 25 kez \"seni seviyorum\" yaz.", "verification_steps": ["İlk 5 mesaj", "6–10 arası mesajlar", "11–15 arası mesajlar", "16–20 arası mesajlar", "Son 5 mesaj"]},
    {"theme": "Boykot", "task": "Bugün hiçbir gerekçeyle boykot veya trip başlatma."},
    {"theme": "Sabah", "task": "Güne {name}'e kısa ve sıcak bir iyi sabahlar mesajıyla başla."},
    {"theme": "Gülümseme", "task": "Bugün {name}'e 3 farklı komik veya içten şey gönder.", "verification_steps": ["İlk paylaşım", "İkinci paylaşım", "Üçüncü paylaşım"]},
    {"theme": "Minnettarlık", "task": "{name}'in yaptığı 3 şeyi bugün açıkça teşekkür ederek belirt.", "verification_steps": ["İlk şey için teşekkür", "İkinci şey için teşekkür", "Üçüncü şey için teşekkür"]},
    {"theme": "Özel mesaj", "task": "Bugün {name}'e 300 karakterden kısa, geçmişteki güzel bir anıyı hatırlatan not yaz."},
    {"theme": "Günlük ritim", "task": "Bugün {name}'in rahatlaması için günü güzelleştiren bir mini sürpriz yap."},
    {"theme": "Destek", "task": "{name}'in karşılaşabileceği bir dert için bugün tek yapıcı çözüm öner."},
    {"theme": "Dürüstlük", "task": "Bugün {name}'e yaşadığın bir duyguyu saklamadan nazikçe anlat."},
    {"theme": "Küçük hediye", "task": "Bugün {name}'e bir emoji, meme, fotoğraf veya küçük sürpriz seç."},
    {"theme": "Affetme", "task": "Bir mesele çıkarsa 10 dakika içinde nazikçe konuşup çözüme odaklan."},
    {"theme": "Birlik", "task": "Bugün {name}'le aynı anda yapabileceğin küçük bir etkinlik planla."},
    {"theme": "Odak", "task": "Telefonu bir kenara koyup {name}'le en az 10 dakika tam dikkat et."},
    {"theme": "Güven", "task": "{name}'e bugün verebileceğin küçük bir söz ver ve günü sonunda yerine getir."},
    {"theme": "İlham", "task": "Bugün {name}'e moral verecek kısa bir söz veya motivasyon gönder."},
    {"theme": "Merak", "task": "{name}'e bugünü nasıl geçirdiğini iyi dinleyerek sor."},
    {"theme": "Özür", "task": "Bir hata yaparsan \"ben suçluyum, seni üzdüm\" diyerek özür dile."},
]

TASK_POOL.extend([
    {"theme": "İletişim", "task": "{name}'e bugün aklındaki güzel bir düşünceyi içtenlikle anlat."},
    {"theme": "İletişim", "task": "{name}'e gün içinde onu düşündüğünü belli eden kısa bir mesaj gönder."},
    {"theme": "İletişim", "task": "{name}'e bugün birlikte konuşmak istediğin bir konu sor."},
    {"theme": "İletişim", "task": "{name}'e bugün seni neyin mutlu ettiğini anlat."},
    {"theme": "İletişim", "task": "{name}'e gününün nasıl geçtiğini sor ve cevabını merakla dinle."},
    {"theme": "İletişim", "task": "{name}'e bugün onunla paylaşmak istediğin küçük bir haber ver."},
    {"theme": "İletişim", "task": "{name}'e içinden geçen bir teşekkür cümlesi yaz."},
    {"theme": "İletişim", "task": "{name}'e bugün birlikte gülmenizi sağlayacak bir soru sor."},
    {"theme": "İletişim", "task": "{name}'e onunla ilgili merak ettiğin zararsız bir şeyi sor."},
    {"theme": "İletişim", "task": "{name}'e bugün konuşmak için uygun olduğu bir zamanı sor."},
    {"theme": "Takdir", "task": "{name}'in sevdiğin bir özelliğini bugün özellikle dile getir."},
    {"theme": "Takdir", "task": "{name}'in son zamanlarda başardığı bir şeyi fark ettiğini söyle."},
    {"theme": "Takdir", "task": "{name}'e hayatına kattığı güzel bir şeyi anlat."},
    {"theme": "Takdir", "task": "{name}'in emeğini gördüğünü belirten kısa bir mesaj gönder."},
    {"theme": "Takdir", "task": "{name}'e onun yanında kendin olabilmeni neden sevdiğini anlat."},
    {"theme": "Takdir", "task": "{name}'in yaptığı küçük bir iyiliği bugün hatırlatıp teşekkür et."},
    {"theme": "Takdir", "task": "{name}'e onda sana ilham veren bir yönünü söyle."},
    {"theme": "Takdir", "task": "{name}'in bugün gösterdiği bir çabayı takdir et."},
    {"theme": "Takdir", "task": "{name}'e onunla gurur duyduğun bir anı hatırlat."},
    {"theme": "Takdir", "task": "{name}'e birlikteyken en sevdiğin küçük alışkanlığını söyle."},
    {"theme": "Dinleme", "task": "{name}'i bugün bölmeden birkaç dakika dinle ve duyduğunu özetle."},
    {"theme": "Dinleme", "task": "{name}'e bugün anlatmak istediği bir şey olup olmadığını sor."},
    {"theme": "Dinleme", "task": "{name}'in anlattığı bir ayrıntıyı daha sonra tekrar hatırla."},
    {"theme": "Dinleme", "task": "{name}'e bir konuda çözüm mü yoksa sadece dinlenmek mi istediğini sor."},
    {"theme": "Dinleme", "task": "{name}'in sevdiği bir konuyu açmasına alan bırak ve merakla eşlik et."},
    {"theme": "Dinleme", "task": "{name}'e son günlerde aklını meşgul eden şeyi nazikçe sor."},
    {"theme": "Dinleme", "task": "{name}'in bir fikrini anlamak için içten bir takip sorusu sor."},
    {"theme": "Dinleme", "task": "{name}'e bugün duygularını paylaşmak isterse yanında olduğunu söyle."},
    {"theme": "Dinleme", "task": "{name}'in anlattığı güzel bir anıyı dikkatle dinleyip bir ayrıntısını sor."},
    {"theme": "Dinleme", "task": "{name}'e konuşurken telefonunu kısa süreliğine kenara bırak."},
    {"theme": "Destek", "task": "{name}'in bugün işini kolaylaştıracak küçük bir şeyi teklif et."},
    {"theme": "Destek", "task": "{name}'e yoğun bir gününde nasıl destek olabileceğini sor."},
    {"theme": "Destek", "task": "{name}'in hedeflerinden biri için bugün cesaret verici bir mesaj gönder."},
    {"theme": "Destek", "task": "{name}'e zorlandığı bir konuda yanında olduğunu hatırlat."},
    {"theme": "Destek", "task": "{name}'in dinlenebilmesi için uygun bir küçük işi üstlenmeyi teklif et."},
    {"theme": "Destek", "task": "{name}'e bugün kendine ayıracağı zaman için onu desteklediğini söyle."},
    {"theme": "Destek", "task": "{name}'in önemli bir işi varsa nasıl geçtiğini sonradan sor."},
    {"theme": "Destek", "task": "{name}'e başarısızlık korkusu olmadan denemesi için moral ver."},
    {"theme": "Destek", "task": "{name}'e bugün ihtiyacı olursa yardım isteyebileceğini söyle."},
    {"theme": "Destek", "task": "{name}'in planlarından birini gerçekleştirmesi için küçük bir adım öner."},
    {"theme": "Birlik", "task": "{name}'le ikinizin de istediği kısa bir etkinlik yapmayı teklif et."},
    {"theme": "Birlik", "task": "{name}'le ortak sevdiğiniz bir şarkıyı dinleyin."},
    {"theme": "Birlik", "task": "{name}'le uygun olduğunuzda kısa bir yürüyüş planlayın."},
    {"theme": "Birlik", "task": "{name}'le birlikte izlemek için ikinizin de seveceği bir şey seçin."},
    {"theme": "Birlik", "task": "{name}'le bugün aynı anda bir kahve ya da çay molası vermeyi öner."},
    {"theme": "Birlik", "task": "{name}'le birlikte denemek istediğiniz yeni bir şeyi konuşun."},
    {"theme": "Birlik", "task": "{name}'le ortak bir anınızı hatırlayıp en sevdiğiniz kısmı paylaşın."},
    {"theme": "Birlik", "task": "{name}'le ikinizin de rahat edeceği küçük bir hafta sonu planı yapın."},
    {"theme": "Birlik", "task": "{name}'le birlikte bir yemek ya da atıştırmalık seçmeyi teklif et."},
    {"theme": "Birlik", "task": "{name}'le gün içinde ikinize de uyan kısa bir sohbet zamanı belirleyin."},
    {"theme": "Neşe", "task": "{name}'e onu güldürebilecek bir karikatür ya da kısa video gönder."},
    {"theme": "Neşe", "task": "{name}'e bugün duyduğun komik ama nazik bir şeyi anlat."},
    {"theme": "Neşe", "task": "{name}'le birbirinize günün en komik anını sorun."},
    {"theme": "Neşe", "task": "{name}'e sadece onun anlayacağı tatlı bir şaka yap."},
    {"theme": "Neşe", "task": "{name}'e birlikte güldüğünüz eski bir anıyı hatırlat."},
    {"theme": "Neşe", "task": "{name}'e gününü anlatan komik bir emoji dizisi gönder."},
    {"theme": "Neşe", "task": "{name}'le birbirinize eğlenceli bir takma ad bulun."},
    {"theme": "Neşe", "task": "{name}'e bugün keyfini yerine getirecek hafif bir öneri sun."},
    {"theme": "Neşe", "task": "{name}'le kısa bir kelime oyunu ya da bilmece paylaş."},
    {"theme": "Neşe", "task": "{name}'e beraber dinleyebileceğiniz neşeli bir şarkı öner."},
    {"theme": "Şefkat", "task": "{name}'e bugün kendine nazik davranmasını hatırlat."},
    {"theme": "Şefkat", "task": "{name}'e iyi dinlenip dinlenmediğini sor ve cevabını önemse."},
    {"theme": "Şefkat", "task": "{name}'e bugün onu düşündüğünü hissettiren sıcak bir selam ver."},
    {"theme": "Şefkat", "task": "{name}'in gününü güzelleştirecek küçük ve düşünceli bir jest yap."},
    {"theme": "Şefkat", "task": "{name}'e yoğun hissediyorsa mola vermesinin sorun olmadığını söyle."},
    {"theme": "Şefkat", "task": "{name}'e bugün kendisi için güzel bir şey yapmasını teşvik et."},
    {"theme": "Şefkat", "task": "{name}'e yanında rahatça kendisi olabileceğini hissettir."},
    {"theme": "Şefkat", "task": "{name}'e bugün iyi dileklerini içeren kısa bir not bırak."},
    {"theme": "Şefkat", "task": "{name}'e günün sonunda nasıl hissettiğini sor."},
    {"theme": "Şefkat", "task": "{name}'in sınırlarına ve bugün istediği alana özen göster."},
    {"theme": "Anı", "task": "{name}'e birlikte yaşadığınız sevdiğin bir anı anlat."},
    {"theme": "Anı", "task": "{name}'le ilk tanıştığınız zamanlardan hoş bir ayrıntıyı paylaş."},
    {"theme": "Anı", "task": "{name}'e birlikte çekildiğiniz sevdiğin bir fotoğrafı gönder."},
    {"theme": "Anı", "task": "{name}'e birlikte ilk kez güldüğünüz anlardan birini hatırlat."},
    {"theme": "Anı", "task": "{name}'le geçmişte yaptığınız ve yine yapmak istediğin bir şeyi konuş."},
    {"theme": "Anı", "task": "{name}'e onun söylediği ve aklında kalan güzel bir cümleyi söyle."},
    {"theme": "Anı", "task": "{name}'le ilişkinizde seni mutlu eden küçük bir dönüm noktasını paylaş."},
    {"theme": "Anı", "task": "{name}'e birlikte dinlediğiniz bir şarkının sende uyandırdığı anıyı anlat."},
    {"theme": "Anı", "task": "{name}'le unutamadığınız güzel bir günü tekrar konuşun."},
    {"theme": "Anı", "task": "{name}'e birlikte biriktirmek istediğin yeni bir anı fikri söyle."},
    {"theme": "İlgi", "task": "{name}'in bu aralar sevdiği bir şeyi öğrenip onun hakkında sohbet et."},
    {"theme": "İlgi", "task": "{name}'e bugün onu heyecanlandıran bir şey olup olmadığını sor."},
    {"theme": "İlgi", "task": "{name}'in sevdiği bir sanatçıdan yeni bir şarkı keşfet."},
    {"theme": "İlgi", "task": "{name}'e şu sıralar okumak ya da izlemek istediği şeyi sor."},
    {"theme": "İlgi", "task": "{name}'in sevdiği bir yemeği ya da içeceği hatırladığını göster."},
    {"theme": "İlgi", "task": "{name}'e bugün tercih ettiği küçük bir şeyi seçme fırsatı ver."},
    {"theme": "İlgi", "task": "{name}'in gün içinde önemli olan bir planını hatırlayıp nasıl geçtiğini sor."},
    {"theme": "İlgi", "task": "{name}'e son zamanlarda öğrendiği ilginç bir şeyi anlatmasını teklif et."},
    {"theme": "İlgi", "task": "{name}'in sevdiği bir konu hakkında senden bir şey öğretmesini iste."},
    {"theme": "İlgi", "task": "{name}'e bugün onu özel hissettiren küçük bir ayrıntı fark ettiğini söyle."},
    {"theme": "Planlama", "task": "{name}'le ikinizin de uygun olduğu bir buluşma zamanı belirleyin."},
    {"theme": "Planlama", "task": "{name}'le birlikte denemek istediğiniz bir mekânı araştırın."},
    {"theme": "Planlama", "task": "{name}'e gelecek hafta için birlikte yapabileceğiniz bir etkinlik öner."},
    {"theme": "Planlama", "task": "{name}'le bir sonraki görüşmenizde yapmak istediğiniz iki şeyi konuşun."},
    {"theme": "Planlama", "task": "{name}'le ikinizin de sevdiği bir yemek için uygun bir gün seçin."},
    {"theme": "Planlama", "task": "{name}'le yağmurlu bir günde evde yapabileceğiniz bir etkinlik düşünün."},
    {"theme": "Planlama", "task": "{name}'e birlikte görmek istediğiniz bir yeri sor."},
    {"theme": "Planlama", "task": "{name}'le önümüzdeki günlerde kısa bir dinlenme molası planlayın."},
    {"theme": "Planlama", "task": "{name}'le ikiniz için de bütçeye uygun bir aktivite fikri bulun."},
    {"theme": "Planlama", "task": "{name}'le bu ay birlikte kutlamak istediğiniz küçük bir şeyi seçin."},
    {"theme": "İletişim", "task": "Bugün {name}'e gün içinde 3 farklı zamanda içten bir mesaj gönder.", "verification_steps": ["İlk mesaj", "İkinci mesaj", "Üçüncü mesaj"]},
    {"theme": "Takdir", "task": "Bugün {name}'e 3 farklı özelliği ya da emeği için iltifat et.", "verification_steps": ["İlk iltifat", "İkinci iltifat", "Üçüncü iltifat"]},
    {"theme": "Merak", "task": "Bugün {name}'e 3 açık uçlu soru sor ve cevaplarını dinle.", "verification_steps": ["İlk soruyu sordun ve dinledin", "İkinci soruyu sordun ve dinledin", "Üçüncü soruyu sordun ve dinledin"]},
    {"theme": "Destek", "task": "Bugün {name}'e iyi gelebilecek 3 küçük destek sun.", "verification_steps": ["İlk desteği sundun", "İkinci desteği sundun", "Üçüncü desteği sundun"]},
    {"theme": "Neşe", "task": "Bugün {name}'le 3 ayrı küçük neşe anı paylaş.", "verification_steps": ["İlk neşe anı", "İkinci neşe anı", "Üçüncü neşe anı"]},
    {"theme": "Birlik", "task": "{name}'le birlikte yapabileceğiniz 3 etkinlik fikri üret.", "verification_steps": ["İlk etkinlik fikri", "İkinci etkinlik fikri", "Üçüncü etkinlik fikri"]},
    {"theme": "Anı", "task": "{name}'le ilişkinizden 3 güzel anıyı paylaş.", "verification_steps": ["İlk anıyı paylaştın", "İkinci anıyı paylaştın", "Üçüncü anıyı paylaştın"]},
    {"theme": "Minnettarlık", "task": "Bugün {name}'e yaptığı 3 küçük şey için teşekkür et.", "verification_steps": ["İlk teşekkür", "İkinci teşekkür", "Üçüncü teşekkür"]},
])

PENALTIES = [
    "Akşam birlikte 10 dakikalık samimi bir sohbet yap.",
    "Karşı tarafa içten bir teşekkür notu gönder.",
    "Karşı taraf için sevdiği bir şarkıyı seçip gönder.",
    "Birlikte kısa bir yürüyüş yapmayı teklif et.",
    "Karşı tarafa gününü güzelleştirecek bir meme gönder.",
    "Karşı tarafın seçtiği bir konuyu 10 dakika dikkatle dinle.",
    "Birlikte izlemek için kısa ve eğlenceli bir video seç.",
    "Karşı tarafa sevdiğin üç özelliğini yaz.",
    "Birlikte çay veya kahve molası vermeyi teklif et.",
    "Karşı tarafa güzel bir anınızı anlatan kısa bir mesaj gönder.",
    "Karşı tarafın seçtiği bir şarkıyı birlikte dinle.",
    "Birlikte yeni bir tatlı ya da içecek denemeyi öner.",
    "Karşı tarafa gün içinde onu düşündüğünü söyle.",
    "Karşı taraf için içten bir iltifat içeren sesli mesaj gönder.",
    "Birlikte 10 dakikalık telefonsuz sohbet yap.",
    "Karşı tarafa sevdiği bir fotoğrafınızı gönder.",
    "Bir sonraki buluşma için iki seçenek hazırlayıp ona sor.",
    "Karşı tarafa bugün yaptığı güzel bir şeyi takdir ettiğini söyle.",
    "Birlikte kısa bir kelime oyunu oynayın.",
    "Karşı tarafın seçtiği bir konuda ona meraklı bir soru sor.",
    "Karşı tarafa gününün en güzel anını sor ve cevabını dinle.",
    "Birlikte komik bir anınızı hatırlayıp gülümseyin.",
    "Karşı tarafa moral veren kısa bir not yaz.",
    "Karşı tarafın sevdiği bir içeceği hazırlamayı teklif et.",
    "Birlikte gelecek hafta için küçük bir plan yapın.",
    "Karşı tarafa onu güldüren bir anını hatırlat.",
    "Karşı tarafın seçtiği bir filmi ya da diziyi izlemeyi planlayın.",
    "Birlikte sevdiğiniz bir şarkı için mini bir çalma listesi oluşturun.",
    "Karşı tarafa bugün için içten bir iyi dilek mesajı gönder.",
    "Karşı tarafın bir hedefi için cesaret verici bir cümle yaz.",
    "Birlikte 10 dakikalık sessiz dinlenme molası verin.",
    "Karşı tarafa onunla ilgili aklında kalan güzel bir ayrıntıyı söyle.",
    "Karşı tarafın seçtiği bir atıştırmalığı paylaşmayı teklif et.",
    "Birlikte eski bir fotoğrafa bakıp anınızı konuşun.",
    "Karşı tarafa yaptığı küçük bir iyilik için teşekkür et.",
    "Bir sonraki sohbetinizde karşı tarafın seçtiği konuyu konuşun.",
    "Karşı tarafa gün içinde kullanabileceği sevimli bir emoji gönder.",
    "Birlikte yeni bir tarif ya da yemek fikri seçin.",
    "Karşı tarafa bugün kendine zaman ayırmasını teşvik eden bir mesaj yaz.",
    "Karşı tarafın sevdiği bir konuda kısa bir bilgi araştırıp paylaş.",
    "Birlikte gökyüzünü ya da gün batımını izlemeyi teklif et.",
    "Karşı tarafa onun yanında en rahat hissettiğin anı anlat.",
    "Karşı tarafın seçtiği bir oyunu kısa süre birlikte oynayın.",
    "Birlikte birbirinize günün en iyi haberini anlatın.",
    "Karşı tarafa küçük bir sürpriz fikri sor ve uygun olanı yap.",
    "Karşı tarafın dinlenmesine yardımcı olacak bir işi üstlenmeyi teklif et.",
    "Birlikte kısa bir çevrim içi müze ya da gezi videosu keşfedin.",
    "Karşı tarafa son zamanlarda başardığı bir şeyi hatırlat.",
    "Birlikte 5 dakikalık esneme ya da nefes molası yapmayı öner.",
    "Karşı tarafa sevdiği bir renk ya da tema ile küçük bir dijital kart hazırla.",
    "Bir sonraki görüşmeniz için ikinizin de sevdiği bir atıştırmalık seçin.",
    "Karşı tarafa onunla ilgili öğrendiğin yeni bir şeyi söyle.",
    "Birlikte birbirinize üç kısa bilmece sorun.",
    "Karşı tarafın istediği bir fotoğrafı ya da manzarayı paylaş.",
    "Karşı tarafa bugün onu dinlemeye hazır olduğunu hatırlat.",
    "Birlikte kısa bir kahkaha molası için komik hikâyeler paylaşın.",
    "Karşı tarafa sevdiği bir kitabı, filmi ya da şarkıyı neden sevdiğini sor.",
    "Birlikte bir sonraki boş gününüz için düşük bütçeli bir etkinlik bulun.",
    "Karşı tarafa bugünkü emeğini fark ettiğini söyle.",
    "Karşı tarafın seçtiği bir konuda küçük bir yardım öner.",
    "Birlikte çocukluğunuzdan komik bir anı paylaşın.",
    "Karşı tarafa kısa bir iyi geceler ya da iyi sabahlar mesajı gönder.",
    "Birlikte sevdiğiniz bir mekânın menüsüne göz atıp bir şey seçin.",
    "Karşı tarafa onunla konuşmayı neden sevdiğini bir cümleyle anlat.",
    "Karşı tarafın seçtiği bir şarkının nakaratını birlikte dinleyin.",
    "Birlikte birbirinize günün küçük bir hedefini sorun.",
    "Karşı tarafa onu rahatlatan bir şeyi hatırlat.",
    "Bir sonraki ortak etkinliğiniz için karşı tarafın fikrini öncelikle sor.",
    "Karşı tarafa kısa ve samimi bir sesli selam gönder.",
    "Birlikte beş dakikalığına telefonları kenara bırakın.",
    "Karşı tarafın sevdiği bir hayvanın fotoğrafını ya da videosunu paylaş.",
    "Birlikte yeni bir hobi ya da etkinlik fikri üzerine konuşun.",
    "Karşı tarafa bugün ona iyi gelen bir şeyi sor.",
    "Birlikte en sevdiğiniz üç şarkıyı sırayla paylaşın.",
    "Karşı tarafa onun için yapabileceğin küçük bir şeyi teklif et.",
    "Bir sonraki sohbetinizde sadece güzel haberleri paylaşmayı deneyin.",
    "Karşı tarafa ilişkinizde değer verdiğin bir alışkanlığı söyle.",
    "Birlikte kısa bir çevrim içi bulmaca çözün.",
    "Karşı tarafa komik bir çocukluk anını anlat.",
    "Birlikte izlemek için doğa ya da seyahat videosu seçin.",
    "Karşı tarafa sevdiği bir atıştırmalığı almayı ya da hazırlamayı teklif et.",
    "Birlikte ikinizin de merak ettiği bir konuyu araştırın.",
    "Karşı tarafa bugün için küçük bir motivasyon cümlesi gönder.",
    "Birlikte birbirinize birer şarkı önerip neden seçtiğinizi anlatın.",
    "Karşı tarafa onunla ilgili sevdiğin bir ayrıntıyı fark ettiğini söyle.",
    "Bir sonraki buluşmanızda yapılacak ilk şeyi birlikte seçin.",
    "Karşı tarafa kısa bir teşekkür videosu ya da ses kaydı gönder.",
    "Birlikte komik bir filtreyle fotoğraf çekmeyi teklif et.",
    "Karşı tarafa yoğun gününde yardımcı olabilecek bir seçenek sun.",
    "Birlikte 10 dakika boyunca gününüzü sırayla anlatın.",
    "Karşı tarafın seçtiği bir konuda küçük bir öneri listesi hazırla.",
    "Birlikte en sevdiğiniz mevsim ve nedenleri hakkında konuşun.",
    "Karşı tarafa onunla gurur duyduğun bir özelliğini söyle.",
    "Bir sonraki dinlenme molanızda karşı tarafın seçtiği müziği açın.",
    "Karşı tarafa sevdiği bir kelimeyi kullanarak kısa bir not yaz.",
    "Birlikte bir sonraki tatil ya da gezi için hayalî bir rota çizin.",
    "Karşı tarafa günün sonunda nasıl hissettiğini sor ve dikkatle dinle.",
    "Birlikte birbirinize bugün öğrendiğiniz yeni bir şeyi anlatın.",
    "Karşı tarafın seçtiği bir konuda kısa bir çizim ya da karalama yap.",
    "Karşı tarafa bugün gülümsemesini sağlayan bir şey söyle.",
    "Birlikte sevdiğiniz bir diziden kısa bir sahneyi izleyin.",
    "Karşı tarafa onunla paylaşmak istediğin küçük bir hedefini anlat.",
    "Birlikte bir sonraki hafta için ortak bir hatırlatma ya da plan belirleyin.",
    "Karşı tarafa onun rahat etmesi için neye ihtiyacı olduğunu sor.",
    "Birlikte günün sonunda birbirinize birer güzel dilek söyleyin.",
]


def _seed(today: date, role: str) -> int:
    raw = f"{today.isoformat()}:{role}".encode()
    return int(hashlib.sha256(raw).hexdigest()[:16], 16)


def select_task(today: date, role: str, name: str) -> dict:
    rng = random.Random(_seed(today, role))
    item = rng.choice(TASK_POOL)
    text = item["task"].replace("{name}", name)
    task = {"theme": item["theme"], "text": text, "status": "pending", "outcome": None}
    if item.get("verification_steps"):
        task["verification_steps"] = [
            step.replace("{name}", name) for step in item["verification_steps"]
        ]
        task["verified_steps"] = []
    return task


def progress_percent(task: dict) -> int:
    steps = task.get("verification_steps") or []
    if not steps:
        return 100 if task.get("status") == "completed" else 0
    verified = {
        index for index in task.get("verified_steps", [])
        if isinstance(index, int) and 0 <= index < len(steps)
    }
    return round(len(verified) * 100 / len(steps))


def select_penalties(today: date, role: str) -> list[str]:
    rng = random.Random(_seed(today, f"penalty:{role}"))
    return rng.sample(PENALTIES, 3)


def ensure_day(state: dict | None, today: date, owner_name: str, partner_name: str) -> dict:
    state = state or {}
    day = today.isoformat()
    data = state.setdefault("days", {})
    day_data = data.setdefault(day, {})
    day_data.setdefault("owner", select_task(today, "owner", partner_name))
    day_data.setdefault("partner", select_task(today, "partner", owner_name))
    state["current"] = day
    return state


async def select_ai(llm, today: date, role: str, name: str) -> dict | None:
    prompt = (
        f"{today.isoformat()} için bugün {name} kişisine verilebilecek kısa, güvenli, "
        "romantik ama özgün bir günlük görev seç. Aynı konuya bağlı kalma. "
        "Sevgi, iletişim, destek, sabır, sürpriz, güven, özür veya mizah tema olsun. "
        "JSON: {\"theme\":\"tema\",\"text\":\"görev metni\"}"
    )
    try:
        result = await llm.ask_json(prompt, "Romantik ilişki günlük görevleri üret. Kişisel veya zararlı istekler verme.", max_tokens=220)
        theme = str(result.get("theme", "")).strip()[:40]
        text = str(result.get("text", "")).strip()[:220]
        if theme and text:
            return {"theme": theme, "text": text, "status": "pending", "outcome": None}
    except Exception:
        log.exception("AI günlük görev seçemedi (%s, %s)", role, today)
    return None


async def assign_day(db, llm, today: date, owner_name: str, partner_name: str) -> dict:
    state = ensure_day(await db.get_kv("daily_tasks"), today, owner_name, partner_name)
    day = state["days"][today.isoformat()]
    if not day.get("ai_selected"):
        if llm:
            owner_task = await select_ai(llm, today, "owner", partner_name)
            partner_task = await select_ai(llm, today, "partner", owner_name)
            if owner_task:
                day["owner"] = owner_task
            if partner_task:
                day["partner"] = partner_task
        day["ai_selected"] = True
    await db.set_kv("daily_tasks", state)
    return state
