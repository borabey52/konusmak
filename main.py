import streamlit as st
import os
import json
import pandas as pd
from datetime import datetime
import google.generativeai as genai
import time
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import io
import openpyxl 

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

# --- 2. GOOGLE SHEETS BAĞLANTISI (Sadece Tablo) ---

@st.cache_resource
def get_gcp_creds():
    scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
    info = dict(st.secrets["gcp_service_account"])
    info["private_key"] = info["private_key"].replace("\\n", "\n")
    creds = ServiceAccountCredentials.from_json_keyfile_dict(info, scope)
    return creds

def save_to_sheet(data_list):
    """
    Sonuçları Google Sheets'e kaydeder.
    """
    try:
        creds = get_gcp_creds()
        client = gspread.authorize(creds)
        
        try:
            sheet = client.open("Sinav_Sonuclari").sheet1
        except:
            st.error("HATA: Google Drive'da 'Sinav_Sonuclari' adında bir tablo bulunamadı.")
            return

        if not sheet.row_values(1):
            sheet.append_row(["Tarih", "Ad Soyad", "Sınıf", "Okul No", "Konu", "Puan", "Puan Detayları", "Transkript", "Öğretmen Yorumu"])
            
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
    dosya_yolu = "konusma_konulari.xlsx"
    if not os.path.exists(dosya_yolu):
        data = {
            'Konu': ['Teknoloji Bağımlılığı', 'Doğa Sevgisi'],
            'Giriş': ['Bağımlılık tanımı', 'Doğanın önemi'],
            'Gelişme': ['Zararları', 'Faydaları'],
            'Sonuç': ['Çözüm', 'Özet']
        }
        try: pd.DataFrame(data).to_excel(dosya_yolu, index=False)
        except: pass

    try:
        df = pd.read_excel(dosya_yolu, engine='openpyxl')
        konular_sozlugu = {}
        for index, row in df.iterrows():
            konular_sozlugu[row['Konu']] = {
                'Giriş': row['Giriş'], 'Gelişme': row['Gelişme'], 'Sonuç': row['Sonuç']
            }
        return konular_sozlugu
    except:
        return {'Teknoloji Bağımlılığı (Yedek)': {'Giriş': 'Tanım', 'Gelişme': 'Zararlar', 'Sonuç': 'Çözüm'}}

def sesi_analiz_et(audio_bytes, konu, detaylar, status_container):
    """
    GÜNCELLENMİŞ FONKSİYON: 
    - JSON hatalarını önler.
    - Hata durumunda programın çökmesini engeller.
    """
    try:
        model = genai.GenerativeModel('gemini-flash-latest')
        status_container.update(label="Sinan Hoca Analiz Ediyor... 🤖", state="running")
        
        import tempfile
        tfile = tempfile.NamedTemporaryFile(delete=False, suffix=".wav")
        tfile.write(audio_bytes)
        tfile.close()
        
        audio_file = genai.upload_file(tfile.name)
        
        # Dosya işlenene kadar bekle
        while audio_file.state.name == "PROCESSING":
            time.sleep(1)
            audio_file = genai.get_file(audio_file.name)
            
        prompt = f"""
        Sen bir Türkçe Öğretmenisin.
        Konu: {konu}. 
        Beklenen Plan: {detaylar}.
        
        GÖREVLER:
        1. Ses kaydının transkriptini çıkar.
        2. Şu kriterlere göre 1-3 arası puan ver: İçerik, Düzen, Dil, Akıcılık.
        3. Toplam puanı 100'lük sisteme çevir.
        4. Öğrenciye motive edici kısa bir yorum yaz.
        
        ÇOK ÖNEMLİ KURAL:
        Cevabı SADECE aşağıdaki JSON formatında ver. Başka hiçbir metin veya markdown (```json gibi) ekleme.
        Anahtarlar (key) mutlaka çift tırnak (") içinde olmalı.
        
        {{
            "transkript": "...",
            "kriter_puanlari": {{
                "konu_icerik": 0,
                "duzen": 0,
                "dil": 0,
                "akicilik": 0
            }},
            "yuzluk_sistem_puani": 0,
            "ogretmen_yorumu": "..."
        }}
        """
        
        # JSON formatını garantiye almak için generation_config kullanıyoruz
        response = model.generate_content(
            [audio_file, prompt],
            generation_config={"response_mime_type": "application/json"}
        )
        
        os.remove(tfile.name)
        
        text = response.text.strip()
        
        # Markdown temizliği
        if text.startswith("```json"): text = text[7:]
        if text.startswith("```"): text = text[3:]
        if text.endswith("```"): text = text[:-3]
            
        return json.loads(text)
        
    except Exception as e:
        return {
            "yuzluk_sistem_puani": 0, 
            "transkript": f"Sistem Hatası oluştu: {str(e)}. Lütfen tekrar deneyin.", 
            "ogretmen_yorumu": "Analiz sırasında teknik bir aksaklık oldu.",
            "kriter_puanlari": {"konu_icerik":0,"duzen":0,"dil":0,"akicilik":0}
        }

# --- 4. ARAYÜZ ---
if 'admin_logged_in' not in st.session_state: st.session_state['admin_logged_in'] = False

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
if not st.session_state['admin_logged_in'] or (st.session_state['admin_logged_in'] and secim == "📝 Sınav Ekranı"):
    
    col_left, col_center, col_right = st.columns([1, 2, 1])
    
    with col_center:
        st.title("🎤 Dijital Konuşma Sınavı")
        st.markdown("---")
        
        c1, c2, c3 = st.columns([3, 1.5, 1.5])
        with c1: ad = st.text_input("Öğrenci Adı Soyadı")
        with c2: 
            sinif_listesi = ["5/C", "5/D", "5/E", "6/D", "8/D", "Diğer"]
            sinif = st.selectbox("Sınıf / Şube", sinif_listesi, index=None)
        with c3: numara = st.text_input("Okul No")
        
        # ------------------ 1. SINAV HAKKI KONTROLÜ (YENİ) ------------------
        sinav_hakki_var = True 
        
        if sinif and numara:
            # 1. Veritabanındaki tüm kayıtları çek
            df_kontrol = get_all_results()
            
            if not df_kontrol.empty:
                # Veri tiplerini string'e çevir
                df_kontrol["Okul No"] = df_kontrol["Okul No"].astype(str)
                
                # 2. Sınıf ve Numaraya göre filtrele
                ogrenci_kayitlari = df_kontrol[
                    (df_kontrol["Sınıf"] == sinif) & 
                    (df_kontrol["Okul No"] == str(numara))
                ]
                
                kullanilan_hak = len(ogrenci_kayitlari)
                
                # 3. Kontrol Et
                if kullanilan_hak >= 2:
                    st.error(f"🛑 DİKKAT: Bu öğrenci ({sinif} - {numara}) 2 sınav hakkını da kullanmıştır.")
                    st.dataframe(ogrenci_kayitlari[["Tarih", "Konu", "Puan"]], hide_index=True)
                    sinav_hakki_var = False
                else:
                    kalan = 2 - kullanilan_hak
                    st.info(f"ℹ️ Öğrencinin şu ana kadar {kullanilan_hak} sınavı var. (Kalan Hak: {kalan})")

        # Eğer hak yoksa kodu durdur
        if not sinav_hakki_var:
            st.warning("Sınav hakkı dolduğu için yeni sınav başlatılamaz.")
            st.stop()
        # --------------------------------------------------------------------
        
        konular = konulari_getir()
        secilen_konu = st.selectbox("Konu Seçiniz:", list(konular.keys()), index=None)
        
        if secilen_konu:
            detay = konular.get(secilen_konu, {})
            st.markdown(f"### 📋 {secilen_konu} - Konuşma Planı")
            k1, k2, k3 = st.columns(3)
            with k1: st.info(f"**1. GİRİŞ**\n\n{detay.get('Giriş','')}")
            with k2: st.warning(f"**2. GELİŞME**\n\n{detay.get('Gelişme','')}")
            with k3: st.success(f"**3. SONUÇ**\n\n{detay.get('Sonuç','')}")

        st.markdown("<br>", unsafe_allow_html=True)

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
        
        if ses and secilen_konu and st.button("Bitir ve Puanla", type="primary", use_container_width=True):
            if not ad: st.warning("Lütfen isim giriniz.")
            elif not sinif: st.warning("Lütfen sınıf seçiniz.")
            elif not numara: st.warning("Lütfen numara giriniz.")
            else:
                with st.status("İşlemler Yapılıyor...", expanded=True) as status:
                    ses_data = ses.getvalue()
                    
                    # 1. Analiz
                    sonuc = sesi_analiz_et(ses_data, secilen_konu, konular.get(secilen_konu,{}), status)
                    
                    # 2. DETAYLARI HAZIRLA
                    kp = sonuc.get("kriter_puanlari", {})
                    detay_metni = f"İçerik: {kp.get('konu_icerik')} | Düzen: {kp.get('duzen')} | Dil: {kp.get('dil')} | Akıcılık: {kp.get('akicilik')}"
                    
                    # 3. KAYIT
                    status.write("📝 Sonuçlar kaydediliyor...")
                    save_to_sheet([
                        datetime.now().strftime("%Y-%m-%d %H:%M"),
                        ad, sinif, numara, secilen_konu,
                        sonuc.get("yuzluk_sistem_puani"),
                        detay_metni,
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
                        
                        st.table(pd.DataFrame({
                            "Kriter": ["İçerik", "Düzen", "Dil", "Akıcılık"],
                            "Puan": [kp.get("konu_icerik"), kp.get("duzen"), kp.get("dil"), kp.get("akicilik")]
                        }).set_index("Kriter"))

elif st.session_state['admin_logged_in'] and secim == "📂 Sonuç Arşivi":
    st.title("📂 Arşiv ve Detaylar")
    df = get_all_results()
    
    if not df.empty:
        event = st.dataframe(
            df,
            selection_mode="single-row",
            on_select="rerun",
            use_container_width=True,
            hide_index=True
        )
    else:
        st.info("Henüz kayıt bulunmamaktadır.")

st.markdown("---")
st.markdown(
    """
    <div style="text-align: center; color: #888; padding: 10px; font-size: 0.9em;">
        © 2026 | Bu uygulama <b>Sinan Sayılır</b> tarafından geliştirilmiş ve kodlanmıştır.
    </div>
    """, 
    unsafe_allow_html=True
)
