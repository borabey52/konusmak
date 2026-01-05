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

# --- 2. GOOGLE BAĞLANTILARI ---

@st.cache_resource
def get_gcp_creds():
    scope = [
        'https://spreadsheets.google.com/feeds',
        'https://www.googleapis.com/auth/drive'
    ]
    info = dict(st.secrets["gcp_service_account"])
    info["private_key"] = info["private_key"].replace("\\n", "\n")
    creds = ServiceAccountCredentials.from_json_keyfile_dict(info, scope)
    return creds

def upload_audio_to_drive(audio_bytes, dosya_adi):
    # NOT: Google Service Account (Robot) kişisel drive hesaplarında kota sorunu yaşayabilir.
    # Bu fonksiyon hata verirse ana program bunu yakalayıp devam edecektir.
    try:
        creds = get_gcp_creds()
        service = build('drive', 'v3', credentials=creds)
        
        # Klasör ID'si (Opsiyonel - Hata verirse kök dizine dener)
        # Buraya kendi klasör ID'nizi yazabilirsiniz ama Robotun kotası yoksa yine hata verebilir.
        file_metadata = {'name': dosya_adi}
        
        media = MediaIoBaseUpload(io.BytesIO(audio_bytes), mimetype='audio/wav')
        
        file = service.files().create(
            body=file_metadata, 
            media_body=media, 
            fields='id, webViewLink'
        ).execute()
        
        return file.get('webViewLink')
    except Exception as e:
        # Hata detayını terminale yazdır ama kullanıcıya gösterme
        print(f"Drive Upload Hatası: {e}")
        return "Yüklenemedi (Kota/Yetki Sorunu)"

def save_to_sheet(data_list):
    try:
        creds = get_gcp_creds()
        client = gspread.authorize(creds)
        
        # Drive'da 'Sinav_Sonuclari' dosyasını açmaya çalış
        try:
            sheet = client.open("Sinav_Sonuclari").sheet1
        except:
            st.error("Google Drive'da 'Sinav_Sonuclari' adında bir E-Tablo bulunamadı.")
            return

        # Başlık kontrolü
        if not sheet.row_values(1):
            sheet.append_row(["Tarih", "Ad Soyad", "Sınıf", "Okul No", "Konu", "Puan", "Ses Linki", "Transkript", "Yorum"])
            
        sheet.append_row(data_list)
    except Exception as e:
        st.error(f"Veritabanı Kayıt Hatası: {str(e)}")

def get_all_results():
    try:
        creds = get_gcp_creds()
        client = gspread.authorize(creds)
        sheet = client.open("Sinav_Sonuclari").sheet1
        data = sheet.get_all_records()
        df = pd.DataFrame(data)
        if "Sınıf" in df.columns and "Okul No" in df.columns:
             df = df.sort_values(by=["Sınıf", "Okul No"])
        return df
    except:
        return pd.DataFrame()

# --- 3. YARDIMCI FONKSİYONLAR ---
def konulari_getir():
    return {
        'Teknoloji Bağımlılığı': {'Giriş': 'Tanım', 'Gelişme': 'Zararlar', 'Sonuç': 'Çözüm'},
        'Doğa Sevgisi': {'Giriş': 'Önem', 'Gelişme': 'Koruma', 'Sonuç': 'Gelecek'},
        'Kitap Okuma Alışkanlığı': {'Giriş': 'Fayda', 'Gelişme': 'Yöntemler', 'Sonuç': 'Tavsiye'}
    }

def sesi_analiz_et(audio_bytes, konu, detaylar, status_container):
    try:
        model = genai.GenerativeModel('gemini-1.5-flash')
        status_container.update(label="Analiz Yapılıyor...", state="running")
        
        import tempfile
        tfile = tempfile.NamedTemporaryFile(delete=False, suffix=".wav")
        tfile.write(audio_bytes)
        tfile.close()
        
        audio_file = genai.upload_file(tfile.name)
        while audio_file.state.name == "PROCESSING":
            time.sleep(0.5)
            audio_file = genai.get_file(audio_file.name)
            
        prompt = f"""
        Rol: Türkçe Öğretmeni.
        Konu: {konu}.
        Görev: Ses kaydını değerlendir.
        Format: SADECE JSON.
        {{
            "transkript": "...",
            "kriter_puanlari": {{ "konu_icerik": 0, "duzen": 0, "dil": 0, "akicilik": 0 }},
            "yuzluk_sistem_puani": 0,
            "ogretmen_yorumu": "..."
        }}
        """
        response = model.generate_content([audio_file, prompt])
        os.remove(tfile.name)
        
        text = response.text
        start = text.find('{')
        end = text.rfind('}') + 1
        return json.loads(text[start:end])
    except Exception as e:
        return {"yuzluk_sistem_puani": 0, "transkript": "Hata", "ogretmen_yorumu": str(e)}

# --- 4. ARAYÜZ ---
if 'admin_logged_in' not in st.session_state: st.session_state['admin_logged_in'] = False

with st.sidebar:
    st.title("🔐 Yönetici")
    if not st.session_state['admin_logged_in']:
        if st.button("Giriş") and st.text_input("Şifre", type="password") == ADMIN_SIFRESI:
            st.session_state['admin_logged_in'] = True
            st.rerun()
    else:
        secim = st.radio("Menü", ["Sınav Ekranı", "Sonuç Arşivi"])
        if st.button("Çıkış"):
            st.session_state['admin_logged_in'] = False
            st.rerun()

# --- EKRANLAR ---
if not st.session_state['admin_logged_in'] or (st.session_state['admin_logged_in'] and secim == "Sınav Ekranı"):
    st.title("🎤 Dijital Konuşma Sınavı")
    st.markdown("---")
    
    c1, c2, c3 = st.columns([3, 1.5, 1.5])
    with c1: ad = st.text_input("Öğrenci Adı Soyadı")
    with c2: sinif = st.selectbox("Sınıf", ["5/A", "5/B", "5/C", "5/D", "5/E", "6/A", "6/D", "7/A", "8/D", "Diğer"])
    with c3: no = st.text_input("No")
    
    konular = konulari_getir()
    secilen_konu = st.selectbox("Konu", list(konular.keys()), index=None)
    
    if secilen_konu:
        detay = konular[secilen_konu]
        k1, k2, k3 = st.columns(3)
        with k1: st.info(f"**Giriş:** {detay['Giriş']}")
        with k2: st.warning(f"**Gelişme:** {detay['Gelişme']}")
        with k3: st.success(f"**Sonuç:** {detay['Sonuç']}")

    st.markdown("<br>", unsafe_allow_html=True)
    st.markdown("### 🎙️ Kaydı Başlat")
    ses = st.audio_input("Mikrofona Tıklayın")
    
    if ses and secilen_konu and st.button("Bitir ve Kaydet", type="primary"):
        if not ad or not sinif or not no:
            st.warning("Lütfen Ad, Sınıf ve Numara bilgilerini doldurunuz.")
        else:
            with st.status("İşlemler yapılıyor...", expanded=True) as status:
                ses_data = ses.getvalue()
                
                # 1. Analiz
                sonuc = sesi_analiz_et(ses_data, secilen_konu, konular[secilen_konu], status)
                
                # 2. Drive'a Yükleme (HATA OLSA BİLE DEVAM EDER)
                status.write("☁️ Ses dosyası işleniyor...")
                drive_link = upload_audio_to_drive(ses_data, f"{ad}_{sinif}_{no}.wav")
                
                # 3. Kayıt
                status.write("📝 Sonuçlar kaydediliyor...")
                save_to_sheet([
                    datetime.now().strftime("%Y-%m-%d %H:%M"),
                    ad, sinif, no, secilen_konu,
                    sonuc.get("yuzluk_sistem_puani"),
                    drive_link,
                    sonuc.get("transkript"),
                    sonuc.get("ogretmen_yorumu")
                ])
                
                status.update(label="Kayıt Başarılı!", state="complete")
                st.balloons()
                
                # Sonuç Kartı
                st.markdown(f"""
                <div style="background-color: #dcfce7; border: 2px solid #22c55e; border-radius: 12px; padding: 15px; text-align: center; margin-bottom: 20px;">
                    <h2 style="margin:0; color:#166534;">PUAN: {sonuc.get('yuzluk_sistem_puani')}</h2>
                </div>
                """, unsafe_allow_html=True)
                
                with st.container(border=True):
                    st.info(f"**Yorum:** {sonuc.get('ogretmen_yorumu')}")
                    st.text_area("Metin", sonuc.get("transkript"), height=100)

elif st.session_state['admin_logged_in'] and secim == "Sonuç Arşivi":
    st.title("📂 Arşiv (Google Sheets)")
    df = get_all_results()
    if not df.empty:
        st.dataframe(df, use_container_width=True)
    else:
        st.info("Kayıt yok.")

# Footer
st.markdown("---")
st.markdown("<div style='text-align: center; color: #888;'>© 2026 | Sinan Sayılır</div>", unsafe_allow_html=True)
