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
ADMIN_SIFRESI = "1234"

# API Key
try:
    if "GOOGLE_API_KEY" in st.secrets:
        os.environ["GOOGLE_API_KEY"] = st.secrets["GOOGLE_API_KEY"]
        genai.configure(api_key=st.secrets["GOOGLE_API_KEY"])
except:
    st.error("API Key Eksik!")

# --- 2. GOOGLE DRIVE VE SHEETS BAĞLANTISI ---

# Kimlik doğrulama fonksiyonu (Cache ile hızlandırıldı)
@st.cache_resource
def get_gcp_creds():
    scope = [
        'https://spreadsheets.google.com/feeds',
        'https://www.googleapis.com/auth/drive'
    ]
    creds = ServiceAccountCredentials.from_json_keyfile_dict(st.secrets["gcp_service_account"], scope)
    return creds

# Sesi Google Drive'a Yükleyen Fonksiyon
def upload_audio_to_drive(audio_bytes, dosya_adi):
    creds = get_gcp_creds()
    service = build('drive', 'v3', credentials=creds)
    
    # 1. 'Ses_Kayitlari' klasörünün ID'sini bulalım (Yoksa kök dizine atar)
    # Pratik yöntem: Drive'da klasör oluşturun ve linkindeki ID'yi buraya sabit yazın.
    # Örn: drive.google.com/drive/u/0/folders/123456789ABCDE... -> ID: 123456789ABCDE...
    # Şimdilik otomatik bulmayı yazıyorum:
    folder_id = None
    results = service.files().list(q="name='Ses_Kayitlari' and mimeType='application/vnd.google-apps.folder'", fields="files(id)").execute()
    items = results.get('files', [])
    if not items:
        # Klasör yoksa oluştur
        file_metadata = {'name': 'Ses_Kayitlari', 'mimeType': 'application/vnd.google-apps.folder'}
        folder = service.files().create(body=file_metadata, fields='id').execute()
        folder_id = folder.get('id')
    else:
        folder_id = items[0]['id']

    # 2. Dosyayı Yükle
    file_metadata = {'name': dosya_adi, 'parents': [folder_id]}
    media = MediaIoBaseUpload(io.BytesIO(audio_bytes), mimetype='audio/wav')
    file = service.files().create(body=file_metadata, media_body=media, fields='id, webViewLink').execute()
    
    return file.get('webViewLink') # Dosyanın Drive linkini döndürür

# Sonucu Google Sheets'e Kaydeden Fonksiyon
def save_to_sheet(data_list):
    creds = get_gcp_creds()
    client = gspread.authorize(creds)
    
    # 'Sinav_Sonuclari' isimli dosyayı aç
    try:
        sheet = client.open("Sinav_Sonuclari").sheet1
    except:
        st.error("Google Drive'da 'Sinav_Sonuclari' adında bir E-Tablo bulunamadı.")
        return

    # Başlık kontrolü
    if not sheet.row_values(1):
        sheet.append_row(["Tarih", "Ad Soyad", "Sınıf", "No", "Konu", "Puan", "Drive Ses Linki", "Transkript", "Yorum"])
        
    sheet.append_row(data_list)

def get_all_results():
    creds = get_gcp_creds()
    client = gspread.authorize(creds)
    try:
        sheet = client.open("Sinav_Sonuclari").sheet1
        data = sheet.get_all_records()
        return pd.DataFrame(data)
    except:
        return pd.DataFrame()

# --- 3. YARDIMCI FONKSİYONLAR ---
def konulari_getir():
    # Basitlik için statik verelim (Dosya okuma hatalarını önlemek için)
    return {
        'Teknoloji Bağımlılığı': {'Giriş': 'Tanım', 'Gelişme': 'Zararlar', 'Sonuç': 'Çözüm'},
        'Doğa Sevgisi': {'Giriş': 'Doğanın önemi', 'Gelişme': 'Koruma yolları', 'Sonuç': 'Gelecek nesiller'}
    }

def sesi_analiz_et(audio_bytes, konu, detaylar, status_container):
    try:
        model = genai.GenerativeModel('gemini-1.5-flash')
        status_container.update(label="Yapay Zeka Analiz Ediyor...", state="running")
        
        # API'ye göndermek için geçici dosya (Hafızada)
        import tempfile
        tfile = tempfile.NamedTemporaryFile(delete=False, suffix=".wav")
        tfile.write(audio_bytes)
        tfile.close()
        
        audio_file = genai.upload_file(tfile.name)
        while audio_file.state.name == "PROCESSING":
            time.sleep(1)
            audio_file = genai.get_file(audio_file.name)
            
        prompt = f"""
        Rol: Türkçe Öğretmeni. Konu: {konu}.
        Görev: Ses kaydını değerlendir.
        Format: SADECE JSON.
        {{
            "transkript": "...",
            "kriter_puanlari": {{ "konu_icerik": 1, "duzen": 1, "dil": 1, "akicilik": 1 }},
            "yuzluk_sistem_puani": 60,
            "ogretmen_yorumu": "..."
        }}
        """
        response = model.generate_content([audio_file, prompt])
        os.remove(tfile.name) # Temizlik
        
        # JSON Temizleme
        text = response.text
        start = text.find('{')
        end = text.rfind('}') + 1
        return json.loads(text[start:end])
    except Exception as e:
        return {"yuzluk_sistem_puani": 0, "transkript": f"Hata: {str(e)}", "ogretmen_yorumu": "Analiz Hatası"}

# --- 4. ARAYÜZ ---
if 'admin_logged_in' not in st.session_state: st.session_state['admin_logged_in'] = False

with st.sidebar:
    st.title("🔐 Yönetici")
    if not st.session_state['admin_logged_in']:
        if st.button("Giriş") and st.text_input("Şifre", type="password") == ADMIN_SIFRESI:
            st.session_state['admin_logged_in'] = True
            st.rerun()
    else:
        secim = st.radio("Menü", ["Sınav", "Arşiv"])

# EKRANLAR
if not st.session_state['admin_logged_in'] or (st.session_state['admin_logged_in'] and secim == "Sınav"):
    st.title("🎤 Dijital Konuşma Sınavı")
    
    c1, c2, c3 = st.columns([3, 1.5, 1.5])
    with c1: ad = st.text_input("Ad Soyad")
    with c2: sinif = st.selectbox("Sınıf", ["5/A", "5/B", "6/A", "6/B", "7/A", "7/B", "8/A", "8/B"])
    with c3: no = st.text_input("No")
    
    konular = konulari_getir()
    secilen_konu = st.selectbox("Konu", list(konular.keys()))
    
    ses = st.audio_input("Kayıt")
    
    if ses and st.button("Bitir ve Kaydet", type="primary"):
        with st.status("İşlemler yapılıyor...", expanded=True) as status:
            ses_data = ses.getvalue()
            
            # 1. Analiz Et
            status.write("🧠 Yapay zeka analiz ediyor...")
            sonuc = sesi_analiz_et(ses_data, secilen_konu, konular[secilen_konu], status)
            
            # 2. Drive'a Yükle
            status.write("☁️ Ses dosyası Google Drive'a yükleniyor...")
            dosya_adi = f"{ad}_{sinif}_{no}_{datetime.now().strftime('%Y%m%d')}.wav"
            drive_link = upload_audio_to_drive(ses_data, dosya_adi)
            
            # 3. Sheets'e Kaydet
            status.write("📝 Sonuçlar veritabanına işleniyor...")
            save_to_sheet([
                datetime.now().strftime("%Y-%m-%d %H:%M"),
                ad, sinif, no, secilen_konu, 
                sonuc.get("yuzluk_sistem_puani"),
                drive_link,
                sonuc.get("transkript"),
                sonuc.get("ogretmen_yorumu")
            ])
            
            status.update(label="Kayıt Başarılı! ✅", state="complete")
            st.balloons()
            st.success(f"Puan: {sonuc.get('yuzluk_sistem_puani')}")

elif st.session_state['admin_logged_in'] and secim == "Arşiv":
    st.title("📂 Bulut Arşivi (Google Sheets)")
    df = get_all_results()
    if not df.empty:
        st.dataframe(df)
        st.info("Veriler doğrudan Google Drive'dan çekilmektedir.")
    else:
        st.warning("Veri bulunamadı veya bağlantı hatası.")

# Footer
st.markdown("---")
st.caption("© 2026 | Sinan Sayılır")
