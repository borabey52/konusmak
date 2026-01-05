import streamlit as st
import os
import json
import pandas as pd
from datetime import datetime
import google.generativeai as genai
import time
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload
import io

# --- 1. AYARLAR ---
st.set_page_config(page_title="Konuşma Sınavı Sistemi", layout="wide", page_icon="🎓")
ADMIN_SIFRESI = "ts527001"

# API Key Kontrolü
try:
    if "GOOGLE_API_KEY" in st.secrets:
        os.environ["GOOGLE_API_KEY"] = st.secrets["GOOGLE_API_KEY"]
        genai.configure(api_key=st.secrets["GOOGLE_API_KEY"])
except Exception as e:
    st.error("API Key bulunamadı.")

# --- 2. GOOGLE DRIVE VE SHEETS BAĞLANTISI (HATA ÇÖZÜMLÜ) ---

@st.cache_resource
def get_gcp_creds():
    scope = [
        'https://spreadsheets.google.com/feeds',
        'https://www.googleapis.com/auth/drive'
    ]
    info = dict(st.secrets["gcp_service_account"])
    
    # --- GÜÇLENDİRİLMİŞ DÜZELTME ---
    # Hem \n karakterlerini düzeltir hem de başta sonda boşluk varsa siler
    key_raw = info["private_key"]
    
    # Eğer kullanıcı BEGIN kısmını yanlışlıkla sildiyse veya kopyalamadıysa hata vermemesi için kontrol:
    if "-----BEGIN PRIVATE KEY-----" not in key_raw:
        st.error("HATA: Secrets ayarlarındaki 'private_key' satırında '-----BEGIN PRIVATE KEY-----' başlığı eksik! Lütfen JSON dosyasından tekrar kopyalayın.")
        st.stop()
        
    info["private_key"] = key_raw.replace("\\n", "\n").strip()
    
    creds = ServiceAccountCredentials.from_json_keyfile_dict(info, scope)
    return creds

# Sesi Google Drive'a Yükleyen Fonksiyon
def upload_audio_to_drive(audio_bytes, dosya_adi):
    creds = get_gcp_creds()
    service = build('drive', 'v3', credentials=creds)
    
    # 'Ses_Kayitlari' klasörünü bul veya oluştur
    folder_id = "1XhYjXeVdKAOrGJlOr3z_-vE4wZwEY7df"
    results = service.files().list(q="name='Ses_Kayitlari' and mimeType='application/vnd.google-apps.folder'", fields="files(id)").execute()
    items = results.get('files', [])
    
    if not items:
        file_metadata = {'name': 'Ses_Kayitlari', 'mimeType': 'application/vnd.google-apps.folder'}
        folder = service.files().create(body=file_metadata, fields='id').execute()
        folder_id = folder.get('id')
    else:
        folder_id = items[0]['id']

    # Dosyayı Yükle
    file_metadata = {'name': dosya_adi, 'parents': [folder_id]}
    media = MediaIoBaseUpload(io.BytesIO(audio_bytes), mimetype='audio/wav')
    file = service.files().create(body=file_metadata, media_body=media, fields='id, webViewLink').execute()
    
    return file.get('webViewLink')

# Sonucu Google Sheets'e Kaydeden Fonksiyon
def save_to_sheet(data_list):
    creds = get_gcp_creds()
    client = gspread.authorize(creds)
    
    try:
        # Drive'da 'Sinav_Sonuclari' adında bir Sheet olmalı
        sheet = client.open("Sinav_Sonuclari").sheet1
    except:
        st.error("Google Drive'da 'Sinav_Sonuclari' adında bir dosya bulunamadı. Lütfen oluşturup paylaşın.")
        return

    # Başlık yoksa ekle
    if not sheet.row_values(1):
        sheet.append_row(["Tarih", "Ad Soyad", "Sınıf", "Okul No", "Konu", "Puan", "Drive Ses Linki", "Transkript", "Yorum"])
        
    sheet.append_row(data_list)

def get_all_results():
    creds = get_gcp_creds()
    client = gspread.authorize(creds)
    try:
        sheet = client.open("Sinav_Sonuclari").sheet1
        data = sheet.get_all_records()
        df = pd.DataFrame(data)
        # Sınıf ve No'ya göre sıralama (Sütun isimleri Sheets ile eşleşmeli)
        if "Sınıf" in df.columns and "Okul No" in df.columns:
             df = df.sort_values(by=["Sınıf", "Okul No"])
        return df
    except:
        return pd.DataFrame()

# --- 3. YARDIMCI FONKSİYONLAR ---
def konulari_getir():
    # Hata almamak için statik veri (Tasarımınızdaki ile aynı)
    return {
        'Teknoloji Bağımlılığı': {'Giriş': 'Bağımlılık tanımı', 'Gelişme': 'Zararları', 'Sonuç': 'Çözüm'},
        'Doğa Sevgisi': {'Giriş': 'Doğanın önemi', 'Gelişme': 'Faydaları', 'Sonuç': 'Özet'}
    }

def sesi_analiz_et(audio_bytes, konu, detaylar, status_container):
    try:
        model = genai.GenerativeModel('gemini-flash-latest')
        status_container.update(label="Sinan Hoca Analiz Ediyor ve Puanlıyor. Bekleyiniz...", state="running")
        
        # Geçici dosya işlemi
        import tempfile
        tfile = tempfile.NamedTemporaryFile(delete=False, suffix=".wav")
        tfile.write(audio_bytes)
        tfile.close()
        
        audio_file = genai.upload_file(tfile.name)
        while audio_file.state.name == "PROCESSING":
            time.sleep(0.5)
            audio_file = genai.get_file(audio_file.name)
            
        prompt = f"""
        Rol: Sen uzman bir Türkçe Öğretmenisin.
        Konu: {konu}. Plan Beklentisi: {detaylar}.
        
        Görev:
        1. Transkript çıkar.
        2. Kriterleri (İçerik, Düzen, Dil, Akıcılık) 1-3 puanla.
        3. Puan = (Toplam/12)*100.
        
        ÖNEMLİ: Sadece aşağıdaki JSON formatını ver.
        {{
            "transkript": "...",
            "kriter_puanlari": {{"konu_icerik":0,"duzen":0,"dil":0,"akicilik":0}},
            "yuzluk_sistem_puani":0,
            "ogretmen_yorumu":"..."
        }}
        """
        response = model.generate_content([audio_file, prompt])
        os.remove(tfile.name)
        
        text = response.text
        start = text.find('{')
        end = text.rfind('}') + 1
        return json.loads(text[start:end])
    except Exception as e:
        return {"yuzluk_sistem_puani": 0, "transkript": f"Hata: {str(e)}", "ogretmen_yorumu": "Analiz yapılamadı."}

# --- 4. ARAYÜZ (TASARIM KORUNDU) ---

if 'admin_logged_in' not in st.session_state: st.session_state['admin_logged_in'] = False

# --- SOL MENÜ ---
with st.sidebar:
    st.title("🔐 Yönetici Paneli")
    
    if not st.session_state['admin_logged_in']:
        sifre = st.text_input("Şifre:", type="password")
        if st.button("Giriş Yap"):
            if sifre == ADMIN_SIFRESI:
                st.session_state['admin_logged_in'] = True
                st.rerun()
            else:
                st.error("Hatalı Şifre!")
    else:
        st.success("Giriş Başarılı")
        secim = st.radio("Sayfa Seçiniz:", ["📝 Sınav Ekranı", "📂 Sonuç Arşivi"])
        if st.button("Çıkış Yap"):
            st.session_state['admin_logged_in'] = False
            st.rerun()

# --- MOD SEÇİMİ ---

# MOD 1: SINAV EKRANI
if not st.session_state['admin_logged_in'] or (st.session_state['admin_logged_in'] and secim == "📝 Sınav Ekranı"):
    
    col_left, col_center, col_right = st.columns([1, 2, 1])
    
    with col_center:
        st.title("🎤 Dijital Konuşma Sınavı")
        st.markdown("---")
        
        # --- Form Alanı (Sizin Tasarımınız) ---
        c1, c2, c3 = st.columns([3, 1.5, 1.5])
        
        with c1: 
            ad = st.text_input("Öğrenci Adı Soyadı")
        with c2: 
            # İsteğiniz üzerine korunan özel liste
            sinif_listesi = ["5/C", "5/D", "5/E", "6/D", "8/D", "Diğer"]
            sinif = st.selectbox("Sınıf / Şube", sinif_listesi, index=None)
        with c3: 
            numara = st.text_input("Okul No")
        
        konular = konulari_getir()
        secilen_konu = st.selectbox("Konu Seçiniz:", list(konular.keys()), index=None)
        
        # PLAN KUTUCUKLARI
        if secilen_konu:
            detay = konular[secilen_konu]
            st.markdown(f"### 📋 {secilen_konu} - Konuşma Planı")
            k1, k2, k3 = st.columns(3)
            with k1: st.info(f"**1. GİRİŞ**\n\n{detay['Giriş']}")
            with k2: st.warning(f"**2. GELİŞME**\n\n{detay['Gelişme']}")
            with k3: st.success(f"**3. SONUÇ**\n\n{detay['Sonuç']}")

        st.markdown("<br>", unsafe_allow_html=True)

        # PUANLAMA TABLOSU (Aynen Korundu)
        rubric_html = """
        <style>
            .rubric-table {width: 100%; border-collapse: collapse; font-size: 0.9em; margin-bottom: 20px;}
            .rubric-table th {background-color: #f8f9fa; border: 1px solid #dee2e6; padding: 8px; text-align: left;}
            .rubric-table td {border: 1px solid #dee2e6; padding: 8px;}
        </style>
        <h4>⚖️ Puanlama Kriterleri</h4>
        <table class="rubric-table">
            <tr><th>Kriter</th><th>Açıklama</th><th>Puan (1-3)</th></tr>
            <tr><td><b>İçerik</b></td><td>Konuya hakimiyet ve plana uyum</td><td>1 - 3</td></tr>
            <tr><td><b>Düzen</b></td><td>Giriş, gelişme ve sonuç bütünlüğü</td><td>1 - 3</td></tr>
            <tr><td><b>Dil</b></td><td>Kelime zenginliği ve gramer</td><td>1 - 3</td></tr>
            <tr><td><b>Akıcılık</b></td><td>Telaffuz ve tonlama</td><td>1 - 3</td></tr>
        </table>
        """
        st.markdown(rubric_html, unsafe_allow_html=True)
        
        st.markdown("### 🎙️ Kaydı Başlat")
        ses = st.audio_input("Mikrofona Tıklayın")
        
        # KAYIT VE PUANLAMA (Bulut Entegrasyonlu)
        if ses and secilen_konu and st.button("Bitir ve Puanla", type="primary", use_container_width=True):
            if not ad: st.warning("Lütfen isim giriniz.")
            elif not sinif: st.warning("Lütfen sınıf seçiniz.")
            elif not numara: st.warning("Lütfen numara giriniz.")
            else:
                with st.status("İşlemler Yapılıyor...", expanded=True) as status:
                    ses_data = ses.getvalue()
                    
                    # 1. Analiz
                    sonuc = sesi_analiz_et(ses_data, secilen_konu, konular[secilen_konu], status)
                    
                    # 2. Drive'a Yükleme
                    status.write("☁️ Ses dosyası Google Drive'a yükleniyor...")
                    dosya_adi = f"{ad}_{sinif}_{numara}_{datetime.now().strftime('%Y%m%d')}.wav"
                    drive_link = upload_audio_to_drive(ses_data, dosya_adi)
                    
                    # 3. Sheets'e Kaydetme
                    status.write("📝 Sonuçlar veritabanına işleniyor...")
                    save_to_sheet([
                        datetime.now().strftime("%Y-%m-%d %H:%M"),
                        ad, sinif, numara, secilen_konu,
                        sonuc.get("yuzluk_sistem_puani"),
                        drive_link,
                        sonuc.get("transkript"),
                        sonuc.get("ogretmen_yorumu")
                    ])
                    
                    status.update(label="Tamamlandı", state="complete")
                    st.balloons()
                    
                    # SONUÇ GÖSTERİMİ
                    st.markdown(f"""
                    <div style="background-color: #dcfce7; border: 2px solid #22c55e; border-radius: 12px; padding: 15px; text-align: center; margin-bottom: 20px;">
                        <h2 style="margin:0; color:#166534;">PUAN: {sonuc.get('yuzluk_sistem_puani')}</h2>
                    </div>
                    """, unsafe_allow_html=True)
                    
                    with st.container(border=True):
                        st.info(f"**Yorum:** {sonuc.get('ogretmen_yorumu')}")
                        st.text_area("Metin", sonuc.get("transkript"), height=150)
                        
                        kp = sonuc.get("kriter_puanlari", {})
                        st.table(pd.DataFrame({
                            "Kriter": ["İçerik", "Düzen", "Dil", "Akıcılık"],
                            "Puan": [kp.get("konu_icerik"), kp.get("duzen"), kp.get("dil"), kp.get("akicilik")]
                        }).set_index("Kriter"))

# MOD 2: ADMİN ARŞİV EKRANI (Google Sheets'ten Çeker)
elif st.session_state['admin_logged_in'] and secim == "📂 Sonuç Arşivi":
    st.title("📂 Arşiv ve Detaylar (Google Drive)")
    df = get_all_results()
    
    if not df.empty:
        event = st.dataframe(
            df,
            selection_mode="single-row",
            on_select="rerun",
            use_container_width=True,
            hide_index=True
        )
        st.info("Veriler doğrudan Google E-Tablolar'dan çekilmektedir.")
    else:
        st.info("Henüz kayıt bulunmamaktadır veya bağlantı kurulamadı.")

# --- FOOTER ---
st.markdown("---")
st.markdown(
    """
    <div style="text-align: center; color: #888; padding: 10px; font-size: 0.9em;">
        © 2026 | Bu uygulama <b>Sinan Sayılır</b> tarafından geliştirilmiş ve kodlanmıştır.
    </div>
    """, 
    unsafe_allow_html=True
)
