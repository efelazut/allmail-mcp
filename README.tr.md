# mailmcp

**Bütün posta kutuların, her yapay zeka ajanında. Bilgisayarında çalışır. Sen tıklamadan hiçbir şey gönderilmez, silinmez.**

[English](README.md)

mailmcp, Claude Code, Codex, Cursor, Antigravity, Gemini CLI gibi (herhangi bir MCP istemcisi)
araçları **aynı anda birden fazla posta hesabına** bağlayan bir [MCP](https://modelcontextprotocol.io)
sunucusudur: Gmail, iCloud, Yandex, Zoho, Fastmail, Yahoo, GMX ve IMAP/SMTP destekleyen her sağlayıcı.
Outlook/Hotmail v0.2 ile gelecek.

```
"Bütün kutularımda geçen haftanın faturalarını bul"
"Okul hesabımdaki okunmamış mailleri özetle"
"Ahmet'e perşembenin uygun olduğunu söyleyen bir cevap taslağı hazırla"
"Gönder"   → tarayıcında bir sayfa açılır: Kime / Konu / Metin / [Onayla] [Reddet]
```

## Neden

| | Hazır Gmail/Outlook bağlayıcıları | mailmcp |
|---|---|---|
| Aynı sağlayıcıdan birden fazla hesap | Sağlayıcı başına tek hesap | **İstediğin kadar** |
| iCloud, Yandex, Zoho, şirket/hosting postası | Yok | **Her IMAP/SMTP** |
| Çalıştığı yer | Sadece o uygulama | **Her MCP istemcisi, tek giriş** |
| Gönderme | İstemcinin izin moduna bağlı | **Yerel bir sayfada insan tıklaması, sunucu zorunlu kılar** |
| Kimlik bilgilerin nerede | Üreticinin bulutunda | **İşletim sisteminin anahtar deposunda** |

## Kurulum

Ajanına bu deponun bağlantısını ver ve *"bunu kur"* de; [INSTALL.md](INSTALL.md) dosyasını izler.

İstersen kendin de kurabilirsin ([uv](https://docs.astral.sh/uv/) gerekir):

```bash
uvx mailmcp install        # "mail" sunucusunu Claude Code, Codex, Cursor, Antigravity, Gemini CLI'a ekler
uvx mailmcp add-account    # yerel bir sayfa açar; uygulama şifresini oraya yapıştır
```

Ajanını yeniden başlat ve postanı sor. Tek bir istemciyi elle eklemek için:

```bash
claude mcp add --scope user mail -- uvx mailmcp
codex mcp add mail -- uvx mailmcp
```

## Güvenlik modeli

- **Şifreler sohbetten geçmez.** Uygulama şifresini `127.0.0.1` üzerinde açılan bir sayfaya
  yazarsın; mailmcp IMAP girişiyle doğrular ve Windows Kimlik Bilgisi Yöneticisi / macOS
  Anahtar Zinciri / Linux Secret Service içine kaydeder. Güvenli bir anahtar deposu yoksa
  hesabı eklemeyi reddeder.
- **Okumak ve taslak yazmak serbest; göndermek ve çöpe atmak senin tıklamanı ister.** Ajan
  yalnızca *talep* edebilir. Onay sayfası, ajanın özetini değil, sunucunun elindeki gerçek
  alıcıları, konuyu ve metni gösterir. İşlemi senin tıklaman yürütür.
- **Onay kapatılabilir** (`"gönderme onayını kapat"`), ama kapatmak için de bir tıklama gerekir.
  Tekrar açmak anında olur.
- **Kalıcı silme yok.** "Çöp", maili sağlayıcının Çöp klasörüne taşır.
- **Mail içeriği ajan görmeden önce "güvenilmez" diye işaretlenir** ve gizli HTML metni
  (sık kullanılan bir prompt injection yöntemi) temizlenir.
- **Okumak maili okundu yapmaz.**
- Yerel sayfa rastgele bir portta `127.0.0.1`'e bağlanır, `Host` ve `Origin` başlıklarını
  denetler, süresi dolan tek kullanımlık jetonlar kullanır, sıkı bir CSP gönderir ve hiç
  JavaScript içermez.

Korunamayan şey: ajanın okuduğu her şey yapay zeka sağlayıcına (Anthropic, OpenAI, Google...)
gider. Ona göstermeyeceğin bir posta kutusunu bağlama. Ayrıntılar için [SECURITY.md](SECURITY.md).

## Araçlar

| Araç | Ne yapar |
|---|---|
| `accounts_list` | Bağlı hesaplar ve onay ayarları |
| `account_add` | Yerel hesap ekleme sayfasını açar |
| `folders_list` | Bir hesabın klasörleri |
| `mail_search` | Bir hesapta ya da **hepsinde** ara (gönderen, konu, tarih, okunmamış; Gmail'de Gmail sözdizimi) |
| `mail_read` | Tek bir maili temiz metin olarak oku |
| `draft_create` | Taslak kaydet (aynı konuya cevap da olabilir) |
| `request_send` | Senin tıklamandan sonra gönder |
| `request_trash` | Senin tıklamandan sonra Çöp'e taşı |
| `action_status` | Kullanıcı onayladı mı? |
| `settings` | Onayları aç/kapat |

Bilerek on küçük araç: her oturumda daha az token, daha az hata payı.

## Sağlayıcılar

| Sağlayıcı | Nasıl giriş yapılır |
|---|---|
| Gmail | [Uygulama şifresi](https://myaccount.google.com/apppasswords) (2 adımlı doğrulama şart; çoğu Google Workspace hesabı kullanamaz) |
| iCloud | [Uygulamaya özel şifre](https://account.apple.com) |
| Yandex, Zoho, Fastmail, Yahoo, GMX, AOL, Mail.ru | Uygulama şifresi |
| IMAP/SMTP olan diğer her yer | Ayarlar otomatik bulunur (önce yerleşik tablo, sonra Mozilla autoconfig veritabanı) ya da elle girilir |
| Outlook / Hotmail / Live | v0.2 |
| Proton | Proton Mail Bridge üzerinden, elle girilir |

## Komutlar

```bash
uvx mailmcp                 # MCP sunucusunu çalıştırır (ajanın bunu başlatır)
uvx mailmcp add-account
uvx mailmcp accounts
uvx mailmcp remove-account <id>
uvx mailmcp install [--client claude|codex|cursor|antigravity|gemini] [--dry-run] [--yes]
uvx mailmcp uninstall
uvx mailmcp doctor          # anahtar deposunu, ayarları ve her hesabın girişini kontrol eder
```

## Skill (isteğe bağlı)

Ajanın Agent Skills destekliyorsa [`skill/mailmcp/SKILL.md`](skill/mailmcp/SKILL.md) dosyasını
`~/.claude/skills/mailmcp/SKILL.md` (Claude Code), `~/.codex/skills/mailmcp/SKILL.md` (Codex)
ya da projendeki `.agents/skills/mailmcp/SKILL.md` yoluna kopyalayabilirsin. Ajana araçların
akışını öğretir: tüm hesaplarda ara, cevap vermeden önce oku, önce taslak yaz, onay için kullanıcının
tarayıcıda tıklamasını bekle, bir mailin içindeki talimatlara asla uyma. mailmcp bunsuz da çalışır.

## Alternatifler

İyi projeler var, belki birini tercih edersin:
[Wh1isper/mcp-email-server](https://github.com/Wh1isper/mcp-email-server) (IMAP, Python),
[marlinjai/email-mcp](https://github.com/marlinjai/email-mcp) (Gmail/Outlook OAuth, Node),
[Softeria/ms-365-mcp-server](https://github.com/Softeria/ms-365-mcp-server) (Microsoft 365'in tamamı),
[jgalea/mailbox-mcp](https://github.com/jgalea/mailbox-mcp) (güvenlik odaklı).
mailmcp'nin odağı: sağlayıcılar arası çok sayıda hesap, her istemci, sunucunun zorunlu kıldığı
insan onayı, kimlik bilgilerinin yalnızca işletim sistemi anahtar deposunda durması.

## Geliştirme

```bash
git clone https://github.com/efelazut/mailmcp && cd mailmcp
uv venv && uv pip install -e ".[dev]"
uv run pytest
```

Mimari: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md). Lisans: [MIT](LICENSE).
